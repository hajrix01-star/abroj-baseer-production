import math
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerPrintPreparationState(models.Model):
    _name = 'baseer.print.preparation.state'
    _description = 'Baseer Preparation Print State'
    _order = 'order_id, line_uuid, printer_id, id'
    _check_company_auto = False

    company_id = fields.Many2one('res.company', required=True, index=True)
    order_id = fields.Many2one('pos.order', required=True, ondelete='cascade', index=True)
    order_line_id = fields.Many2one('pos.order.line', ondelete='set null', index=True)
    line_uuid = fields.Char(required=True, index=True)
    product_id = fields.Many2one('product.product', required=True, ondelete='restrict')
    printer_id = fields.Many2one('baseer.print.printer', required=True, ondelete='restrict', index=True)
    route_id = fields.Many2one('baseer.print.route', ondelete='set null')
    copies = fields.Integer(required=True, default=1)
    quantity = fields.Float(required=True)
    details = fields.Json(required=True, readonly=True)

    _order_line_printer_unique = models.Constraint(
        'unique(order_id, line_uuid, printer_id)', 'A preparation line may only have one state per printer.')

    @api.constrains('company_id', 'order_id', 'order_line_id', 'printer_id', 'route_id', 'copies')
    def _check_links(self):
        for record in self:
            if record.order_id.company_id != record.company_id or (
                    record.order_line_id and record.order_line_id.order_id != record.order_id):
                raise AccessError(_('Preparation state companies do not match.'))
            if not 1 <= record.copies <= 10 or not record.printer_id._allows_company(record.company_id):
                raise AccessError(_('Preparation state printer configuration is not valid.'))

    @api.model
    def _kitchen_quantity(self, line):
        # Accepted financial replacements are silent. Only quantities above
        # that immutable allowance may become subsequent kitchen additions.
        silent = (line.baseer_substitution_silent_quantity
                  if 'baseer_substitution_silent_quantity' in line._fields else 0.0)
        return max(0.0, line.qty - silent)

    @api.model
    def _line_details(self, line):
        return {'line_uuid': line.uuid, 'product_id': line.product_id.id,
                'name': line.full_product_name or line.product_id.display_name, 'quantity': self._kitchen_quantity(line),
                'note': line.note or '', 'customer_note': line.customer_note or ''}

    @api.model
    def _same_logical_line(self, state, details):
        """Recover a POS line only when its server UUID was regenerated.

        Odoo's POS sync normally preserves line UUIDs.  A stale/reloaded client
        can nevertheless submit a replacement line for the same product.  Its
        database row and UUID then differ even though the kitchen item did not.
        Match that replacement only when one prior state exists for the product;
        ambiguous duplicate-product lines deliberately remain unmatched instead
        of guessing and potentially cancelling the wrong food item.
        """
        previous = state.details
        return all(previous.get(key) == details.get(key)
                   for key in ('product_id', 'name', 'note', 'customer_note'))

    @api.model
    def _details_changed(self, state, details):
        previous = dict(state.details)
        current = dict(details)
        # UUID is transport identity, not a kitchen change.  Quantity remains
        # compared separately so the update delta is always exact.
        previous.pop('line_uuid', None)
        previous.pop('quantity', None)
        current.pop('line_uuid', None)
        current.pop('quantity', None)
        return previous != current

    @api.model
    def _lock_order_state(self, order):
        self.env.cr.execute('SELECT id FROM pos_order WHERE id = %s FOR UPDATE', [order.id])
        self.env.cr.execute('SELECT id FROM baseer_print_preparation_state WHERE order_id = %s FOR UPDATE', [order.id])

    @api.model
    def _lock_orders_states(self, orders):
        order_ids = sorted(orders.ids)
        if not order_ids:
            return
        self.env.cr.execute('SELECT id FROM pos_order WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(order_ids)])
        self.env.cr.execute('''SELECT id FROM baseer_print_preparation_state
            WHERE order_id IN %s ORDER BY order_id, id FOR UPDATE''', [tuple(order_ids)])

    @api.model
    def _states_for_orders(self, orders):
        return self.sudo().search([('order_id', 'in', orders.ids)], order='order_id, printer_id, copies, id')

    @api.model
    def _normalize_action(self, raw_action):
        if not isinstance(raw_action, dict):
            raise ValidationError(_('The kitchen action is invalid.'))
        action_uuid = self.env['baseer.print.preparation.event']._canonical_uuid(raw_action.get('action_uuid'))
        action_type = raw_action.get('action_type')
        if action_type not in ('send', 'line_change'):
            raise ValidationError(_('The kitchen action type is invalid.'))
        raw_lines = raw_action.get('lines')
        if not isinstance(raw_lines, list) or not raw_lines or len(raw_lines) > 500:
            raise ValidationError(_('The kitchen action must contain valid lines.'))
        lines = []
        seen = set()
        for raw_line in raw_lines:
            if not isinstance(raw_line, dict):
                raise ValidationError(_('The kitchen action line is invalid.'))
            line_uuid = raw_line.get('line_uuid')
            if not isinstance(line_uuid, str) or not line_uuid.strip() or len(line_uuid) > 128:
                raise ValidationError(_('The kitchen line identifier is invalid.'))
            line_uuid = line_uuid.strip()
            if line_uuid in seen:
                raise ValidationError(_('The kitchen action contains a duplicate line.'))
            seen.add(line_uuid)
            expected = raw_line.get('expected_quantity')
            target = raw_line.get('new_quantity')
            if (isinstance(expected, bool) or isinstance(target, bool)
                    or not isinstance(expected, (int, float)) or not isinstance(target, (int, float))
                    or not math.isfinite(expected) or not math.isfinite(target)
                    or expected < 0 or target < 0):
                raise ValidationError(_('The kitchen action quantities are invalid.'))
            reason_code = raw_line.get('reason_code') or False
            reason_note = raw_line.get('reason_note') or ''
            if (reason_code and not isinstance(reason_code, str)) or not isinstance(reason_note, str):
                raise ValidationError(_('The kitchen cancellation reason is invalid.'))
            lines.append({
                'line_uuid': line_uuid,
                'expected_quantity': float(expected),
                'new_quantity': float(target),
                'reason_code': reason_code,
                'reason_note': reason_note,
            })
        return {'action_uuid': action_uuid, 'action_type': action_type, 'lines': lines}

    @api.model
    def _assert_order_can_prepare(self, order):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can send preparation tickets.'))
        if (not order.exists() or order.company_id not in self.env.companies
                or not order.config_id.baseer_direct_print_enabled
                or order.state != 'draft' or order.is_refund
                or any(line.qty < 0 for line in order.lines)):
            raise AccessError(_('This order cannot be sent to preparation.'))
        order.check_access_rights('read')
        order.check_access_rule('read')
        order.session_id.check_access_rights('read')
        order.session_id.check_access_rule('read')
        if (order.session_id.config_id != order.config_id
                or order.session_id.company_id != order.company_id):
            raise AccessError(_('The order POS session does not match its point of sale.'))

    @api.model
    def _validate_expected_quantities(self, order, action):
        states = self.sudo().search([('order_id', '=', order.id)])
        by_uuid = {state.line_uuid: state for state in states}
        lines_by_uuid = {line.uuid: line for line in order.lines}
        for requested in action['lines']:
            current = by_uuid.get(requested['line_uuid'])
            if not current and requested['expected_quantity']:
                line = lines_by_uuid.get(requested['line_uuid'])
                if not line:
                    # A non-routed line removed by Odoo has no preparation
                    # state and is intentionally outside this workflow.
                    continue
                categories = line.product_id.product_tmpl_id.pos_categ_ids
                if not self.env['baseer.print.route']._select_binding(order.config_id, categories):
                    continue
            current_quantity = current.quantity if current else 0.0
            if abs(current_quantity - requested['expected_quantity']) > 0.000001:
                raise ValidationError(_(
                    'This kitchen item changed on another device. Refresh the order and try again.'
                ))

    @api.model
    def _action_name(self, previous, target):
        if previous == 0 and target > 0:
            return 'new'
        if target > previous:
            return 'add'
        if previous > 0 and target == 0:
            return 'cancel'
        if 0 < target < previous:
            return 'reduce'
        raise ValidationError(_('The kitchen action does not change the item quantity.'))

    @api.model
    def _event_snapshot(self, order, line, old, printer, binding, copies, action, previous, target,
                        reason_code=False, reason_note='', action_type='line_change',
                        request_fingerprint=False):
        details = self._line_details(line) if line else dict(old.details)
        return {
            'schema': 1,
            'order': {
                'id': order.id,
                'uuid': order.uuid,
                'reference': order.pos_reference or order.name or str(order.id),
            },
            'line': {
                'uuid': details.get('line_uuid') or (line.uuid if line else old.line_uuid),
                'product_id': details.get('product_id') or (line.product_id.id if line else old.product_id.id),
                'name': details.get('name') or (line.product_id.display_name if line else old.product_id.display_name),
                'note': details.get('note', ''),
                'customer_note': details.get('customer_note', ''),
            },
            'change': {
                'action': action,
                'previous_quantity': previous,
                'delta_quantity': target - previous,
                'new_quantity': target,
                'reason_code': reason_code or '',
                'reason_note': reason_note or '',
            },
            'destination': {
                'printer_id': printer.id,
                'printer_name': printer.display_name,
                'route_id': binding.id if binding else False,
                'copies': copies,
            },
            'request_action_type': action_type,
            'request_fingerprint': request_fingerprint or False,
        }

    @api.model
    def _record_quantity_event(self, order, line, old, printer, binding, copies, action_uuid,
                               previous, target, reason_code=False, reason_note='',
                               action_type='line_change', request_fingerprint=False,
                               enqueue_job=True):
        action = self._action_name(previous, target)
        if action == 'cancel':
            if not reason_code:
                raise ValidationError(_('Choose a reason before cancelling a kitchen item.'))
            reason_code, reason_note = self.env['baseer.print.cancellation']._normalized_reason(
                reason_code, reason_note,
            )
        elif reason_code or reason_note:
            raise ValidationError(_('A cancellation reason is only valid when cancelling a kitchen item.'))
        details = self._line_details(line) if line else dict(old.details)
        line_uuid = line.uuid if line else old.line_uuid
        product = line.product_id if line else old.product_id
        snapshot = self._event_snapshot(
            order, line, old, printer, binding, copies, action, previous, target,
            reason_code, reason_note, action_type, request_fingerprint,
        )
        cashier = (
            order.employee_id
            if 'employee_id' in order._fields and order.employee_id
            else order.user_id
        )
        event = self.env['baseer.print.preparation.event']._create_once({
            'company_id': order.company_id.id,
            'pos_config_id': order.config_id.id,
            'session_id': order.session_id.id,
            'order_id': order.id,
            'order_reference': order.pos_reference or order.name or str(order.id),
            'order_line_id': line.id if line else old.order_line_id.id,
            'line_uuid': line_uuid,
            'product_id': product.id,
            'action': action,
            'previous_quantity': previous,
            'delta_quantity': target - previous,
            'new_quantity': target,
            'reason_code': reason_code or False,
            'reason_note': reason_note or False,
            'cashier_name': cashier.display_name or self.env.user.display_name,
            'requested_by': self.env.user.id,
            'action_uuid': action_uuid,
            'snapshot': snapshot,
        })
        change = {
            **details,
            'action': action,
            'previous_quantity': previous,
            'delta_quantity': target - previous,
            'new_quantity': target,
            'quantity': target,
        }
        job = (
            self.env['baseer.print.job']._enqueue_preparation(
                order, printer, binding, change, copies, event=event,
            )
            if enqueue_job else self.env['baseer.print.job']
        )
        return event, job

    @api.model
    def _finish_empty_preparation_order(self, order):
        """An acknowledged kitchen cancel is not permission to erase money."""
        self._lock_order_state(order)
        order.invalidate_recordset()
        if (order.state != 'draft' or order.lines or order.payment_ids
                or order.account_move or order.is_refund
                or order.session_id.state not in ('opened', 'closing_control')):
            return False
        if any(not order.currency_id.is_zero(value) for value in (
                order.amount_total, order.amount_paid, order.amount_return)):
            return False
        if order._baseer_has_native_preparation_obligation():
            return False
        if self.sudo().search_count([('order_id', '=', order.id), ('quantity', '!=', 0)], limit=1):
            return False
        order._baseer_native_action_pos_order_cancel()
        return True

    @api.model
    def _apply_action(self, order, action):
        self._assert_order_can_prepare(order)
        self._validate_expected_quantities(order, action)
        states = self.sudo().search([('order_id', '=', order.id)])
        by_uuid = {state.line_uuid: state for state in states}
        lines_by_uuid = {line.uuid: line for line in order.lines}
        events = self.env['baseer.print.preparation.event']
        jobs = self.env['baseer.print.job']
        request_fingerprint = events._action_request_fingerprint(action)
        print_groups = {}
        for requested in action['lines']:
            old = by_uuid.get(requested['line_uuid'])
            line = lines_by_uuid.get(requested['line_uuid'])
            previous = requested['expected_quantity']
            target = requested['new_quantity']
            actual = self._kitchen_quantity(line) if line else 0.0
            if abs(actual - target) > 0.000001 or (target > 0 and not line):
                raise ValidationError(_('The synchronized kitchen item quantity does not match the requested change.'))
            if old:
                printer, binding, copies = old.printer_id, old.route_id, old.copies
            else:
                if not line:
                    # No durable preparation baseline means this was never a
                    # kitchen-routed item; ignore the browser's generic delta.
                    continue
                categories = line.product_id.product_tmpl_id.pos_categ_ids
                binding = self.env['baseer.print.route']._select_binding(order.config_id, categories)
                if not binding:
                    continue
                printer, copies = binding.printer_id, binding.copies
                if previous:
                    raise ValidationError(_('The kitchen item baseline is missing. Refresh the order and try again.'))
            event, job = self._record_quantity_event(
                order, line, old, printer, binding, copies, action['action_uuid'], previous, target,
                requested['reason_code'], requested['reason_note'], action['action_type'],
                request_fingerprint, enqueue_job=False,
            )
            events |= event
            jobs |= job
            details = self._line_details(line) if line else dict(old.details)
            group = print_groups.setdefault(
                (printer.id, copies),
                {'printer': printer, 'binding': binding, 'events': events.browse(), 'changes': []},
            )
            group['events'] |= event
            group['changes'].append(details)
            if target == 0:
                old.unlink()
                continue
            details = self._line_details(line)
            vals = {
                'company_id': order.company_id.id,
                'order_id': order.id,
                'order_line_id': line.id,
                'line_uuid': line.uuid,
                'product_id': line.product_id.id,
                'printer_id': printer.id,
                'route_id': binding.id if binding else False,
                'copies': copies,
                'quantity': target,
                'details': details,
            }
            if old:
                old.write(vals)
            else:
                self.sudo().create(vals)
        for group in print_groups.values():
            jobs |= self.env['baseer.print.job']._enqueue_preparation_batch(
                order, group['printer'], group['binding'], group['changes'], copies=group['events'][0].snapshot[
                    'destination'
                ]['copies'], events=group['events'],
            )
        zero_lines = order.lines.filtered(lambda candidate: candidate.qty == 0)
        if zero_lines:
            zero_lines.unlink()
        self._finish_empty_preparation_order(order)
        return {'event_ids': events.ids, 'job_ids': jobs.ids, 'accepted': True}

    @api.model
    def _enqueue_cancellation_jobs(self, order, cancellation, states):
        grouped = {}
        for state in states:
            grouped.setdefault((state.printer_id.id, state.copies), self.browse())
            grouped[(state.printer_id.id, state.copies)] |= state
        Job = self.env['baseer.print.job']
        jobs = self.env['baseer.print.job']
        for (printer_id, copies), grouped_states in grouped.items():
            printer = self.env['baseer.print.printer'].browse(printer_id)
            if not printer.active or not printer._allows_company(order.company_id):
                raise AccessError(_('The original kitchen printer is no longer authorized for this company.'))
            jobs |= Job._enqueue_preparation_cancellation(order, cancellation, printer, grouped_states, copies)
        return jobs

    @api.model
    def _enqueue_order(self, order, client_event_uuid=False, reason_code=False, reason_note=False):
        self._assert_order_can_prepare(order)
        self._lock_order_state(order)
        State = self.sudo()
        existing = State.search([('order_id', '=', order.id)])
        prior_by_line = {state.line_uuid: state for state in existing}
        Job = self.env['baseer.print.job']
        Event = self.env['baseer.print.preparation.event']
        events = Event
        jobs = Job
        if client_event_uuid:
            try:
                action_uuid = Event._canonical_uuid(client_event_uuid)
            except ValidationError:
                action_uuid = str(uuid5(NAMESPACE_URL, 'baseer-preparation:%s:%s' % (
                    order.uuid, client_event_uuid,
                )))
        else:
            action_uuid = str(uuid4())
        for line in order.lines:
            details = self._line_details(line)
            kitchen_quantity = self._kitchen_quantity(line)
            old = prior_by_line.pop(line.uuid, False)
            # Do not let a silent replacement borrow another line's kitchen
            # history merely because it happens to use the same product.
            if kitchen_quantity == 0 and not old:
                continue
            if not old:
                # See _same_logical_line: only recover an unambiguous replacement
                # so a sync/reload cannot issue a false NEW followed by CANCEL.
                candidates = [state for state in prior_by_line.values()
                              if self._same_logical_line(state, details)]
                # A sole product line can legitimately receive a changed note
                # or presentation name in the same synchronization.  Keep it
                # as an update, but never apply this looser match to duplicates.
                if not candidates:
                    candidates = [state for state in prior_by_line.values()
                                  if state.product_id.id == details['product_id']]
                if len(candidates) == 1:
                    old = candidates[0]
                    prior_by_line.pop(old.line_uuid)
            # POS represents a deleted line as quantity zero until the next
            # synchronization. Treat that state as a kitchen cancellation,
            # never as an UPDATE with a visible quantity of zero.
            if kitchen_quantity <= 0:
                if old:
                    event, job = self._record_quantity_event(
                        order, line, old, old.printer_id, old.route_id, old.copies,
                        action_uuid, old.quantity, 0, reason_code, reason_note,
                    )
                    events |= event
                    jobs |= job
                    old.unlink()
                continue
            # Destination freezes at first send. Later mapping changes never redirect updates or cancellations.
            if old:
                printer, binding, copies = old.printer_id, old.route_id, old.copies
            else:
                categories = line.product_id.product_tmpl_id.pos_categ_ids
                binding = self.env['baseer.print.route']._select_binding(order.config_id, categories)
                if not binding:
                    continue
                printer, copies = binding.printer_id, binding.copies
            vals = {'company_id': order.company_id.id, 'order_id': order.id, 'order_line_id': line.id,
                    'line_uuid': line.uuid, 'product_id': line.product_id.id, 'printer_id': printer.id,
                    'route_id': binding.id if binding else False, 'copies': copies, 'quantity': kitchen_quantity,
                    'details': details}
            changed = not old or old.quantity != kitchen_quantity or self._details_changed(old, details)
            # Persist the new UUID/line ID even where the kitchen details did not
            # change; it becomes the baseline for the next synchronization.
            if old and not changed:
                old.write(vals)
                continue
            if not changed:
                continue
            previous = old.quantity if old else 0
            if abs(kitchen_quantity - previous) > 0.000001:
                event, job = self._record_quantity_event(
                    order, line, old, printer, binding, copies, action_uuid, previous, kitchen_quantity,
                )
                events |= event
                jobs |= job
            else:
                # Presentation/name/note changes remain compatible with the
                # legacy kitchen UPDATE. Quantity lineage is recorded only by
                # immutable semantic events.
                change = {
                    **details, 'action': 'update', 'delta_quantity': 0,
                    'previous_quantity': previous, 'new_quantity': kitchen_quantity,
                }
                jobs |= Job._enqueue_preparation(order, printer, binding, change, copies)
            if old:
                old.write(vals)
            else:
                try:
                    with self.env.cr.savepoint():
                        State.create(vals)
                except IntegrityError:
                    State.search([('order_id', '=', order.id), ('line_uuid', '=', line.uuid),
                                  ('printer_id', '=', printer.id)], limit=1).write(vals)
        # Missing lines cancel on their original snapshot destination.
        for old in prior_by_line.values():
            event, job = self._record_quantity_event(
                order, False, old, old.printer_id, old.route_id, old.copies,
                action_uuid, old.quantity, 0, reason_code, reason_note,
            )
            events |= event
            jobs |= job
            old.unlink()
        zero_lines = order.lines.filtered(lambda candidate: candidate.qty == 0)
        if zero_lines:
            zero_lines.unlink()
        self._finish_empty_preparation_order(order)
        return {
            'accepted': True,
            'correlation': client_event_uuid or False,
            'event_ids': events.ids,
            'job_ids': jobs.ids,
        }
