import hashlib
import json
import logging
import math

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_receipt_enqueue_error = fields.Char(readonly=True, copy=False)
    baseer_merged_into_order_id = fields.Many2one(
        'pos.order', readonly=True, copy=False, index=True,
        string='Merged into POS order',
    )
    baseer_merge_destination_id = fields.Many2one(
        'pos.order', readonly=True, copy=False,
        string='Pending restaurant merge destination',
    )
    baseer_merge_expected_quantities = fields.Json(readonly=True, copy=False)
    baseer_merge_expected_total = fields.Monetary(currency_field='currency_id', readonly=True, copy=False)
    baseer_merge_request_digest = fields.Char(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        protected_fields = {
            'baseer_merged_into_order_id',
            'baseer_merge_destination_id',
            'baseer_merge_expected_quantities',
            'baseer_merge_expected_total',
            'baseer_merge_request_digest',
        }
        if any(protected_fields.intersection(vals) for vals in vals_list):
            raise AccessError(_('Restaurant merge links can only be recorded by the protected merge workflow.'))
        return super().create(vals_list)

    @api.model
    def sync_from_ui(self, orders):
        merge = self.env.context.get('baseer_restaurant_merge')
        if not merge:
            return super().sync_from_ui(orders)
        if not isinstance(merge, dict) or len(orders) != 1:
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        destination = self._get_open_order(orders[0])
        if not destination or destination.state != 'draft' or merge.get('destination_id') != destination.id:
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        # Native synchronization mutates the order payload before _process_order.
        # Bind the durable receipt to the original request.
        digest = hashlib.sha256(json.dumps([merge, orders], sort_keys=True).encode()).hexdigest()
        return super(PosOrder, self.with_context(baseer_restaurant_merge_digest=digest)).sync_from_ui(orders)

    @api.model
    def _process_order(self, order, existing_order):
        merge = self.env.context.get('baseer_restaurant_merge')
        if merge:
            return self._baseer_process_restaurant_merge(order, existing_order, merge)
        self._baseer_strip_merge_sync_echo(order, existing_order)
        raw_action = order.pop('baseer_preparation_action', False)
        if not raw_action:
            return super()._process_order(order, existing_order)

        State = self.env['baseer.print.preparation.state']
        Event = self.env['baseer.print.preparation.event']
        Attempt = self.env['baseer.print.preparation.attempt']
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can submit kitchen changes.'))
        action = State._normalize_action(raw_action)
        if order.get('state', 'draft') != 'draft':
            raise AccessError(_('Kitchen changes cannot be submitted while paying or closing an order.'))

        # Both resolution and original sync take this lock before row locks or
        # creation. A retired payload can never recreate a deleted draft.
        Attempt._lock_action(action['action_uuid'])
        receipt = Attempt._for_action(action['action_uuid'])
        if receipt:
            original = receipt._assert_identity(
                order.get('uuid'), session_id=order.get('session_id'),
                order=existing_order, action=action,
            )
            return original.id

        if existing_order:
            State._lock_order_state(existing_order)
        retry_events = Event._retry_events(action)
        if retry_events:
            retry_orders = self.env['pos.order'].browse(retry_events.order_id.ids)
            if len(retry_orders) != 1 or not retry_orders.exists():
                raise ValidationError(_('The previous kitchen action no longer has a valid order.'))
            retry_order = retry_orders.ensure_one()
            retry_order.check_access_rights('read')
            retry_order.check_access_rule('read')
            if (retry_order.company_id not in self.env.companies
                    or (existing_order and retry_order != existing_order)
                    or retry_order.uuid != order.get('uuid')
                    or retry_order.session_id.id != order.get('session_id')):
                raise AccessError(_('This kitchen action does not belong to the synchronized order.'))
            return retry_order.id

        if existing_order:
            State._assert_order_can_prepare(existing_order)
            State._validate_expected_quantities(existing_order, action)
        elif any(line['expected_quantity'] for line in action['lines']):
            raise ValidationError(_('A new order cannot have an existing kitchen quantity.'))

        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id).exists()
        if not pos_order:
            raise ValidationError(_('The synchronized point of sale order was not found.'))
        if not existing_order:
            State._lock_order_state(pos_order)
        State._apply_action(pos_order, action)
        Attempt._record_decision(pos_order, action, 'accepted')
        return order_id

    @api.model
    def _baseer_strip_merge_sync_echo(self, order, existing_order):
        """Native POS serializes readonly fields too; echoes grant no write.

        Keep the ORM guards intact. Only discard proven unchanged native
        values at the sync boundary, never client changes or context claims.
        No extra row lock: preparation retains its action/order lock ordering.
        """
        names = ('baseer_merged_into_order_id', 'baseer_merge_destination_id',
                 'baseer_merge_expected_quantities', 'baseer_merge_expected_total', 'baseer_merge_request_digest')
        present = [name for name in names if name in order]
        if not present:
            return
        if existing_order:
            existing_order.check_access('read')
            if (existing_order.company_id not in self.env.companies
                    or order.get('uuid') != existing_order.uuid):
                raise AccessError(_('The merge field echo does not belong to this POS order.'))
            existing_order.invalidate_recordset(names)
        for name in present:
            kind = self._fields[name].type
            expected = existing_order[name] if existing_order else (0 if kind == 'monetary' else False)
            value = order[name]
            if kind == 'many2one':
                expected = expected.id if expected else False
                matches = value is False if expected is False else type(value) is int and value == expected
            elif kind == 'monetary':
                matches = ((value is False and expected == 0)
                           or (type(value) in (int, float) and value == expected and math.isfinite(value)))
            elif kind == 'char':
                matches = type(value) is type(expected) and value == expected
            else:
                # This field is a native product-ID -> quantity map. JS
                # echoes 1.0 as 1; that is exact numeric equality, not a
                # rounding tolerance. Booleans/strings are never quantities.
                matches = ((value is False and expected is False) or (
                    type(value) is dict and type(expected) is dict
                    and value.keys() == expected.keys()
                    and all(type(key) is str and type(value[key]) in (int, float)
                            and type(expected[key]) in (int, float)
                            and value[key] == expected[key]
                            and math.isfinite(value[key]) and math.isfinite(expected[key])
                            for key in value)))
            if not matches:
                raise AccessError(_('Restaurant merge links can only be recorded by the protected merge workflow.'))
        for name in present:
            order.pop(name)

    def baseer_resolve_preparation_action(self, raw_action):
        """Retire an unaccepted send without changing the order or print jobs."""
        self.ensure_one()
        State = self.env['baseer.print.preparation.state']
        Event = self.env['baseer.print.preparation.event']
        Attempt = self.env['baseer.print.preparation.attempt']
        action = State._normalize_action(raw_action)
        # Validate access before waiting; validate the draft again under locks.
        State._assert_order_can_prepare(self)
        if self.session_id.state not in ('opened', 'closing_control'):
            raise AccessError(_('The point of sale session is not active.'))
        Attempt._lock_action(action['action_uuid'])
        State._lock_order_state(self)
        self.invalidate_recordset()
        State._assert_order_can_prepare(self)
        self.session_id.invalidate_recordset(['state'])
        if self.session_id.state not in ('opened', 'closing_control'):
            raise AccessError(_('The point of sale session is not active.'))
        receipt = Attempt._for_action(action['action_uuid'])
        if receipt:
            receipt._assert_identity(self.uuid, session_id=self.session_id.id, order=self, action=action)
        else:
            events = Event._retry_events(action)
            if events and (events.order_id != self or events.company_id != self.company_id
                           or events.session_id != self.session_id):
                raise AccessError(_('This kitchen action does not belong to the synchronized order.'))
            Attempt._record_decision(self, action, 'accepted' if events else 'skipped')
        return Event.baseer_action_status(action['action_uuid'], self.uuid)

    def _baseer_assert_cancellation_batch(self, session_id):
        if not self or not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can cancel a kitchen order.'))
        self.check_access('read')
        if any(order.company_id not in self.env.companies for order in self):
            raise AccessError(_('This kitchen order does not belong to an allowed company.'))
        if len(self.company_id) != 1 or len(self.config_id) != 1 or len(self.session_id) != 1:
            raise ValidationError(_('Kitchen cancellations must contain orders from one point of sale session.'))
        session = self.env['pos.session'].browse(session_id).exists()
        if not session:
            raise AccessError(_('The point of sale session was not found.'))
        session.check_access_rights('read')
        session.check_access_rule('read')
        if (session != self.session_id or session.config_id != self.config_id
                or session.config_id.company_id != self.company_id or session.state not in ('opened', 'closing_control')):
            raise AccessError(_('The kitchen cancellation session is not active for these orders.'))
        if any(order.state != 'draft' for order in self):
            raise ValidationError(_('Only draft point of sale orders can be cancelled from the kitchen workflow.'))
        if any(order.payment_ids or order.account_move or order.is_refund
               or not order.currency_id.is_zero(order.amount_paid)
               or not order.currency_id.is_zero(order.amount_return) for order in self):
            raise ValidationError(_(
                'An order with payments, refunds or an invoice cannot be cancelled from the kitchen workflow. Resolve it through the native payment or refund workflow.'
            ))
        if not self.config_id.baseer_direct_print_enabled:
            raise AccessError(_('Baseer direct kitchen printing is disabled for this point of sale.'))
        return session

    def _baseer_preparation_states(self):
        return self.env['baseer.print.preparation.state']._states_for_orders(self)

    def baseer_preview_preparation_cancellations(self, session_id):
        self._baseer_assert_cancellation_batch(session_id)
        states = self._baseer_preparation_states()
        return {
            'order_ids': sorted(set(states.order_id.ids)),
            'count': len(set(states.order_id.ids)),
        }

    def baseer_cancel_with_preparation(self, session_id, reason_code, reason_note=False):
        return self.baseer_cancel_with_preparation_reasons(session_id, {
            str(order.id): {'reason_code': reason_code, 'reason_note': reason_note or ''}
            for order in self
        })

    def baseer_cancel_with_preparation_reasons(self, session_id, reasons_by_order):
        self._baseer_assert_cancellation_batch(session_id)
        Cancellation = self.env['baseer.print.cancellation']
        if not isinstance(reasons_by_order, dict) or set(reasons_by_order) != {str(order.id) for order in self}:
            raise ValidationError(_('Choose one cancellation reason for every kitchen order.'))
        normalized_reasons = {}
        for order in self:
            reason = reasons_by_order.get(str(order.id))
            if not isinstance(reason, dict):
                raise ValidationError(_('Choose one cancellation reason for every kitchen order.'))
            normalized_reasons[order.id] = Cancellation._normalized_reason(
                reason.get('reason_code'), reason.get('reason_note'),
            )
        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(self)
        # Refresh after the ordered locks so two overlapping cancellation batches
        # cannot create different records or printer jobs for the same order.
        orders = self.browse(sorted(self.ids)).exists()
        orders.invalidate_recordset()
        orders._baseer_assert_cancellation_batch(session_id)
        states = State._states_for_orders(orders)
        if set(states.order_id.ids) != set(orders.ids):
            raise ValidationError(_('Every order in this cancellation must already have a kitchen ticket.'))
        events = Cancellation
        jobs = self.env['baseer.print.job']
        for order in orders:
            order_states = states.filtered(lambda state: state.order_id == order)
            reason_code, reason_note = normalized_reasons[order.id]
            event = Cancellation._get_or_create_for_order(order, order_states, reason_code, reason_note)
            events |= event
            jobs |= State._enqueue_cancellation_jobs(order, event, order_states)
        # Native Odoo cancellation is deliberately invoked inside this same ORM
        # transaction. A failure rolls back the immutable audit event and jobs.
        orders._baseer_native_action_pos_order_cancel()
        return {
            'cancellation_ids': events.ids,
            'job_ids': jobs.ids,
            'pending': bool(jobs.filtered(lambda job: job.state == 'pending')),
        }

    def _baseer_native_action_pos_order_cancel(self):
        return super().action_pos_order_cancel()

    def _baseer_requires_cancellation_event(self):
        states = self.env['baseer.print.preparation.state'].sudo().search([('order_id', 'in', self.ids)])
        return states.mapped('order_id')

    def _baseer_assert_cancellation_events_exist(self):
        protected = self._baseer_requires_cancellation_event().filtered(
            lambda order: order.state == 'draft' and not order.baseer_merged_into_order_id
        )
        if not protected:
            return
        events = self.env['baseer.print.cancellation'].sudo().search([('order_id', 'in', protected.ids)])
        missing = protected - events.mapped('order_id')
        if missing:
            raise AccessError(_('A kitchen order must be cancelled through the documented kitchen cancellation workflow.'))

    def _baseer_assert_restaurant_merge_destination(self, destination):
        self.ensure_one()
        if (destination == self or destination.state != 'draft'
                or destination.company_id != self.company_id
                or destination.config_id != self.config_id
                or destination.session_id != self.session_id):
            raise ValidationError(_('The restaurant merge destination must be a draft order in the same POS session.'))

    def _baseer_merge_line_quantities(self):
        self.ensure_one()
        quantities = {}
        for line in self.lines:
            # Native restaurant merging can fold a source line into an existing
            # destination line. Product quantity is the durable common
            # identity in both that case and the retained-separate-line case.
            key = str(line.product_id.id)
            quantities[key] = quantities.get(key, 0.0) + line.qty
        return quantities

    def _baseer_restaurant_merge_baseline(self):
        """Fingerprint both saved orders and their frozen kitchen destinations."""
        self.invalidate_recordset()
        lines = self.lines
        lines.invalidate_recordset()
        states = self._baseer_preparation_states()
        states.invalidate_recordset()
        baseline = [
            self.sorted('id').read(['uuid', 'state', 'write_date', 'amount_total', 'lines']),
            lines.sorted('id').read(['uuid', 'write_date', 'qty']),
            [self._baseer_merge_line_key(line) for line in lines.sorted('id')],
            states.sorted('id').read(['order_id', 'line_uuid', 'printer_id', 'copies', 'quantity', 'details']),
        ]
        return hashlib.sha256(json.dumps(baseline, default=str, sort_keys=True).encode()).hexdigest()

    @api.model
    def _baseer_merge_line_key(self, line):
        parent = line.combo_parent_id
        return (
            line.product_id.id, line.product_uom_id.id, line.full_product_name or '',
            line.note or '', line.customer_note or '', line.price_unit, line.discount,
            tuple(sorted(line.tax_ids.ids)), tuple(sorted(line.attribute_value_ids.ids)),
            tuple(sorted((value.custom_product_template_attribute_value_id.id, value.custom_value or '')
                         for value in line.custom_attribute_value_ids)),
            line.combo_item_id.id, parent.product_id.id, tuple(sorted(parent.attribute_value_ids.ids)),
            tuple(sorted(lot.lot_name or '' for lot in line.pack_lot_ids)),
        )

    def _baseer_merge_item_quantities(self):
        quantities = {}
        for line in self.lines:
            key = self._baseer_merge_line_key(line)
            quantities[key] = quantities.get(key, 0.0) + line.qty
        return quantities

    @api.model
    def _baseer_process_restaurant_merge(self, order, destination, merge):
        if (
            not isinstance(merge, dict)
            or type(merge.get('source_id')) is not int
            or not destination
            or merge.get('destination_id') != destination.id
            or order.get('uuid') != destination.uuid
            or order.get('session_id') != destination.session_id.id
            or order.get('state', 'draft') != 'draft'
            or order.get('payment_ids')
            or order.get('baseer_preparation_action')
        ):
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        source = self.browse(merge['source_id']).exists()
        if not source or source == destination:
            raise ValidationError(_('The restaurant merge orders are no longer available.'))
        orders = source | destination
        orders.check_access('write')
        if not self.env.user.has_group('point_of_sale.group_pos_user') or any(
            candidate.company_id not in self.env.companies for candidate in orders
        ):
            raise AccessError(_('This kitchen order does not belong to an allowed company.'))
        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(orders)
        orders.invalidate_recordset()
        digest = self.env.context.get('baseer_restaurant_merge_digest')
        if not digest:
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        if source.baseer_merged_into_order_id == destination and source.state == 'cancel':
            if source.baseer_merge_request_digest != digest:
                raise ValidationError(_('This restaurant merge has already been completed with different order data.'))
            return destination.id
        orders._baseer_assert_cancellation_batch(source.session_id.id)
        source._baseer_assert_restaurant_merge_destination(destination)
        if not source._baseer_preparation_states() or merge.get('baseline') != orders._baseer_restaurant_merge_baseline():
            raise ValidationError(_('The restaurant orders changed. Reload both orders before merging again.'))

        expected_quantities = orders._baseer_merge_item_quantities()
        expected_total = destination.amount_total + source.amount_total
        self._baseer_strip_merge_sync_echo(order, destination)
        order_id = super()._process_order(order, destination)
        destination.invalidate_recordset()
        orders._baseer_assert_cancellation_batch(source.session_id.id)
        source._baseer_assert_restaurant_merge_destination(destination)
        quantities = destination._baseer_merge_item_quantities()
        if (
            order_id != destination.id
            or set(quantities) != set(expected_quantities)
            or any(abs(quantities[product] - quantity) > 0.000001 for product, quantity in expected_quantities.items())
            or not destination.currency_id.is_zero(destination.amount_total - expected_total)
        ):
            raise ValidationError(_('The restaurant merge destination does not retain the source order total.'))
        source._baseer_transfer_restaurant_merge_states(destination, merge.get('line_uuid_map'))
        source._baseer_complete_restaurant_merge(destination, digest)
        return order_id

    def baseer_begin_restaurant_merge(self, destination_id, atomic=False):
        """Record the destination baseline before native POS moves the lines."""
        self.ensure_one()
        self.check_access('write')
        if not isinstance(destination_id, int):
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        destination = self.browse(destination_id).exists()
        if not destination:
            raise ValidationError(_('The restaurant merge destination was not found.'))
        destination.check_access('read')

        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(self | destination)
        source = self.browse(self.id).exists()
        destination = self.browse(destination.id).exists()
        if not source or not destination:
            raise ValidationError(_('The restaurant merge orders are no longer available.'))
        states = source._baseer_preparation_states()
        if not states:
            return {'requires_transfer': False}
        source._baseer_assert_cancellation_batch(source.session_id.id)
        source._baseer_assert_restaurant_merge_destination(destination)
        if atomic is True:
            (source | destination)._baseer_assert_cancellation_batch(source.session_id.id)
            destination.check_access('write')
            return {
                'requires_transfer': True,
                'preparation_line_uuids': sorted(set(states.mapped('line_uuid'))),
                'baseline': (source | destination)._baseer_restaurant_merge_baseline(),
            }
        # Existing browser tabs can still use the old two-request workflow.
        # Do not let them start a transfer they cannot roll back safely.
        signatures = {(state.printer_id.id, state.copies)
                      for state in (source | destination)._baseer_preparation_states()}
        if len(signatures) > 1:
            raise ValidationError(_('Reload Point of Sale before merging orders sent to different printers or copy settings.'))
        expected_quantities = destination._baseer_merge_line_quantities()
        for key, quantity in source._baseer_merge_line_quantities().items():
            expected_quantities[key] = expected_quantities.get(key, 0.0) + quantity
        super(PosOrder, source).write({
            'baseer_merge_destination_id': destination.id,
            'baseer_merge_expected_quantities': expected_quantities,
            'baseer_merge_expected_total': destination.amount_total + source.amount_total,
        })
        return {'requires_transfer': True, 'preparation_line_uuids': sorted(set(states.mapped('line_uuid')))}

    def _baseer_assert_restaurant_merge_transfer(self, destination):
        self.ensure_one()
        if self.baseer_merge_destination_id != destination or not self.baseer_merge_expected_quantities:
            raise ValidationError(_('The restaurant merge was not prepared before the order changed.'))
        destination_quantities = destination._baseer_merge_line_quantities()
        if any(destination_quantities.get(key, 0.0) + 0.000001 < quantity
               for key, quantity in self.baseer_merge_expected_quantities.items()):
            raise ValidationError(_('The restaurant merge destination does not contain the transferred source order lines.'))
        if not self.currency_id.is_zero(destination.amount_total - self.baseer_merge_expected_total):
            raise ValidationError(_('The restaurant merge destination does not retain the source order total.'))

    def _baseer_transfer_restaurant_merge_states(self, destination, line_uuid_map):
        """Move preparation state to the native destination line identities."""
        self.ensure_one()
        State = self.env['baseer.print.preparation.state']
        source_states = State._states_for_orders(self)
        if not isinstance(line_uuid_map, dict):
            raise ValidationError(_('The restaurant merge line transfer is invalid.'))
        destination_lines = {line.uuid: line for line in destination.lines}
        required_uuids = set(source_states.mapped('line_uuid'))
        if any(not isinstance(line_uuid_map.get(uuid), str) or len(line_uuid_map[uuid]) > 128
               for uuid in required_uuids):
            raise ValidationError(_('The restaurant merge is missing a transferred kitchen line.'))
        destination_states = State._states_for_orders(destination)
        # Validate all groups before moving any state. A line sent to different
        # printers cannot be folded into one line without leaving inconsistent
        # per-printer quantities, even if the native POS would merge it.
        source_groups = {}
        for state in source_states:
            source_groups.setdefault(state.line_uuid, State.sudo().browse())
            source_groups[state.line_uuid] |= state
        destination_signatures = {}
        target_quantities = {}
        for source_uuid, group in source_groups.items():
            target_uuid = line_uuid_map[source_uuid]
            target_line = destination_lines.get(target_uuid)
            if not target_line or not State._same_logical_line(group[0], State._line_details(target_line)):
                raise ValidationError(_('The restaurant merge kitchen line does not match its destination.'))
            signature = frozenset((state.printer_id.id, state.copies) for state in group)
            existing_states = destination_states.filtered(lambda state: state.line_uuid == target_uuid)
            existing_signature = frozenset((state.printer_id.id, state.copies) for state in existing_states)
            unequal_source = any(abs(state.quantity - group[0].quantity) > 0.000001 for state in group)
            unequal_target = existing_states and any(
                abs(state.quantity - existing_states[0].quantity) > 0.000001 for state in existing_states
            )
            if unequal_source or unequal_target or (existing_states and signature != existing_signature) or (
                    target_uuid in destination_signatures and destination_signatures[target_uuid] != signature):
                raise ValidationError(_(
                    'These kitchen items cannot be merged because they were sent to different printers or copy settings. '
                    'Keep them as separate items.'
                ))
            destination_signatures[target_uuid] = signature
            target_quantities[target_uuid] = target_quantities.get(
                target_uuid, existing_states[0].quantity if existing_states else 0
            ) + group[0].quantity
            if target_quantities[target_uuid] - State._kitchen_quantity(target_line) > 0.000001:
                raise ValidationError(_('The restaurant merge kitchen line does not match its destination.'))
        for source_state in source_states:
            destination_line = destination_lines.get(line_uuid_map[source_state.line_uuid])
            details = State._line_details(destination_line) if destination_line else False
            if not destination_line or not State._same_logical_line(source_state, details):
                raise ValidationError(_('The restaurant merge kitchen line does not match its destination.'))
            existing = destination_states.filtered(
                lambda state: state.line_uuid == destination_line.uuid
                and state.printer_id == source_state.printer_id
            )
            if existing:
                existing.ensure_one().write({
                    'quantity': existing.quantity + source_state.quantity,
                    'order_line_id': destination_line.id,
                    'details': details,
                })
                source_state.unlink()
            else:
                source_state.write({
                    'order_id': destination.id,
                    'order_line_id': destination_line.id,
                    'line_uuid': destination_line.uuid,
                    'details': details,
                })
                destination_states |= source_state

    def baseer_finalize_restaurant_merge(self, destination_id, line_uuid_map):
        """Close a kitchen order only after its restaurant merge is durable.

        Odoo synchronizes the destination before it cancels the source.  A
        kitchen-sent source is intentionally protected from ordinary
        cancellation, but a verified merge is a transfer rather than a kitchen
        cancellation: emitting a cancellation ticket here would be incorrect.
        """
        self.ensure_one()
        self.check_access('write')
        if not isinstance(destination_id, int):
            raise ValidationError(_('The restaurant merge destination is invalid.'))
        destination = self.browse(destination_id).exists()
        if not destination:
            raise ValidationError(_('The restaurant merge destination was not found.'))
        destination.check_access('read')

        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(self | destination)
        source = self.browse(self.id).exists()
        destination = self.browse(destination.id).exists()
        if not source or not destination:
            raise ValidationError(_('The restaurant merge orders are no longer available.'))
        source.invalidate_recordset()
        destination.invalidate_recordset()
        source._baseer_assert_cancellation_batch(source.session_id.id)
        if not source._baseer_preparation_states():
            raise ValidationError(_('The restaurant source order has no kitchen preparation state.'))
        source._baseer_assert_restaurant_merge_destination(destination)
        source._baseer_assert_restaurant_merge_transfer(destination)
        source._baseer_transfer_restaurant_merge_states(destination, line_uuid_map)
        return source._baseer_complete_restaurant_merge(destination)

    def _baseer_complete_restaurant_merge(self, destination, digest=False):
        # This link is immutable from regular ORM writes.  It is both an audit
        # trail and the narrowly-scoped proof that the following native cancel
        # is a restaurant merge, not a silent kitchen cancellation.
        super(PosOrder, self).write({
            'baseer_merged_into_order_id': destination.id,
            'baseer_merge_destination_id': False,
            'baseer_merge_expected_quantities': False,
            'baseer_merge_expected_total': False,
            'baseer_merge_request_digest': digest,
        })
        return self._baseer_native_action_pos_order_cancel()

    def _baseer_assert_payment_source_integrity(self):
        """Prove synchronized headers from native taxes before accepting payment.

        Reading the tax pipeline must not repair an incomplete order: the
        cashier needs the original lines to recover it before paying again.
        """
        AccountTax = self.env['account.tax']
        for order in self:
            currency = order.currency_id
            # A record rule may hide part of an order. Visible rows alone
            # cannot prove either its financial source or its empty tenders.
            for model, inverse, records in (
                    ('pos.order.line', 'order_id', order.lines),
                    ('pos.payment', 'pos_order_id', order.payment_ids)):
                source = self.env[model]
                source.flush_model([inverse])
                self.env.cr.execute(
                    'SELECT id FROM "%s" WHERE "%s" = %%s' % (source._table, inverse),
                    [order.id],
                )
                if {row[0] for row in self.env.cr.fetchall()} != set(records.ids):
                    raise AccessError(_(
                        'The complete order items and payments must be accessible before accepting payment.'
                    ))
                records.check_access('read')
            if not order.lines and (
                    any(not currency.is_zero(order[field]) for field in (
                        'amount_total', 'amount_tax', 'amount_paid', 'amount_return'))
                    or any(not currency.is_zero(payment.amount) for payment in order.payment_ids)):
                raise ValidationError(_(
                    'This order has amounts but no items. Restore its items before accepting payment.'
                ))

            # A hidden direct tax can disappear from the line's many-to-many
            # field before native fiscal mapping even prepares the base line.
            order.lines.flush_recordset(['tax_ids'])
            tax_field = self.env['pos.order.line']._fields['tax_ids']
            self.env.cr.execute(
                'SELECT "%s" FROM "%s" WHERE "%s" = ANY(%%s)' % (
                    tax_field.column2, tax_field.relation, tax_field.column1,
                ),
                [order.lines.ids],
            )
            source_tax_ids = {row[0] for row in self.env.cr.fetchall()}
            AccountTax.browse(sorted(source_tax_ids)).check_access('read')
            order.fiscal_position_id.check_access('read')

            # Preserve native extension hooks, including trusted summary lines.
            base_lines = order._prepare_tax_base_line_values()
            pending_taxes = AccountTax
            for base in base_lines:
                base['tax_ids'].check_access('read')
                pending_taxes |= base['tax_ids']
            # Native tax expansion can filter out a hidden group child. Prove
            # access to the complete hierarchy before using that expansion.
            child_field = AccountTax._fields['children_tax_ids']
            AccountTax.flush_model(['children_tax_ids'])
            checked_tax_ids = set()
            while pending_taxes:
                pending_taxes.check_access('read')
                checked_tax_ids.update(pending_taxes.ids)
                groups = pending_taxes.filtered(lambda tax: tax.amount_type == 'group')
                if not groups:
                    break
                self.env.cr.execute(
                    'SELECT "%s" FROM "%s" WHERE "%s" = ANY(%%s)' % (
                        child_field.column2, child_field.relation, child_field.column1,
                    ),
                    [groups.ids],
                )
                child_ids = {row[0] for row in self.env.cr.fetchall()} - checked_tax_ids
                pending_taxes = AccountTax.browse(sorted(child_ids))
            AccountTax._add_tax_details_in_base_lines(base_lines, order.company_id)
            for base in base_lines:
                for tax_data in base['tax_details']['taxes_data']:
                    tax_data['tax'].check_access('read')
            AccountTax._round_base_lines_tax_details(base_lines, order.company_id)
            cash_rounding = (
                order.config_id.rounding_method if order.config_id.cash_rounding else None
            )
            backend_rounding = (
                cash_rounding if not order.config_id.only_round_cash_method else None
            )
            backend = AccountTax._get_tax_totals_summary(
                base_lines=base_lines, currency=currency, company=order.company_id,
                cash_rounding=backend_rounding,
            )
            candidates = [(backend['total_amount_currency'], backend['tax_amount_currency'])]
            if cash_rounding:
                # Odoo 19 setOrderPrices stores priceIncl before the added cash
                # rounding line; its tax amount comes from the same summary.
                # Keep each native (gross, tax) pair together (biggest_tax).
                ui = AccountTax._get_tax_totals_summary(
                    base_lines=base_lines, currency=currency, company=order.company_id,
                    cash_rounding=cash_rounding,
                )
                candidates.append((
                    ui['total_amount_currency'] - ui.get('cash_rounding_base_amount_currency', 0.0),
                    ui['tax_amount_currency'],
                ))
            refund_factor = -1 if (order.is_refund or order.amount_total < 0.0) else 1
            if not any(
                    currency.compare_amounts(order.amount_total, refund_factor * gross) == 0
                    and currency.compare_amounts(order.amount_tax, refund_factor * tax) == 0
                    for gross, tax in candidates):
                raise ValidationError(_(
                    'The order totals no longer match its items. Reload the order and review its items before accepting payment.'
                ))

    def action_pos_order_paid(self):
        self._baseer_assert_payment_source_integrity()
        result = super().action_pos_order_paid()
        for order in self:
            if (order.config_id.baseer_direct_print_enabled
                    and not order.config_id.baseer_native_receipt_enabled):
                # A printer failure must never roll back native payment.
                try:
                    with self.env.cr.savepoint():
                        job = self.env['baseer.print.job']._enqueue_receipt(order)
                        if not job:
                            raise ValidationError(_('The customer receipt printer is not ready.'))
                        order.baseer_receipt_enqueue_error = False
                except Exception as error:
                    _logger.exception('Customer receipt enqueue failed for POS order %s', order.id)
                    order.baseer_receipt_enqueue_error = (
                        str(error) if isinstance(error, UserError)
                        else _('The receipt service failed. Ask a manager to inspect the server log.')
                    )
        return result

    def baseer_customer_receipt_status(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can print customer receipts.'))
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('This order does not belong to an allowed company.'))
        job = self.env['baseer.print.job'].sudo().search([
            ('source_order_id', '=', self.id), ('ticket_type', '=', 'receipt'),
        ], order='id desc', limit=1)
        return {'job_id': job.id, 'state': job.state,
                'error': self.baseer_receipt_enqueue_error or False}

    def baseer_enqueue_native_receipt(self, jpeg_base64):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can print customer receipts.'))
        self.check_access_rights('read')
        self.check_access_rule('read')
        job = self.env['baseer.print.job']._enqueue_native_receipt(self, jpeg_base64)
        return {'job_id': job.id, 'state': job.state}

    def action_pos_order_cancel(self):
        self._baseer_assert_cancellation_events_exist()
        return super().action_pos_order_cancel()

    def write(self, vals):
        if {
            'baseer_merged_into_order_id',
            'baseer_merge_destination_id',
            'baseer_merge_expected_quantities',
            'baseer_merge_expected_total',
            'baseer_merge_request_digest',
        }.intersection(vals):
            raise AccessError(_('Restaurant merge links can only be recorded by the protected merge workflow.'))
        if vals.get('state') == 'cancel':
            self._baseer_assert_cancellation_events_exist()
        return super().write(vals)

    def unlink(self):
        self._baseer_assert_cancellation_events_exist()
        return super().unlink()

    def baseer_enqueue_preparation_jobs(
            self, client_event_uuid=False, reason_code=False, reason_note=False):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can send preparation tickets.'))
        return self.env['baseer.print.preparation.state']._enqueue_order(
            self, client_event_uuid, reason_code, reason_note,
        )
