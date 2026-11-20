"""Keep native bill splitting atomic with Baseer's frozen kitchen state."""

from copy import deepcopy
import hashlib
import json
import math
from uuid import UUID

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_split_receipt = fields.Json(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, values_list):
        if any('baseer_split_receipt' in values for values in values_list):
            raise AccessError(_('Bill split receipts can only be recorded by the native split workflow.'))
        return super().create(values_list)

    def write(self, values):
        if 'baseer_split_receipt' in values:
            raise AccessError(_('Bill split receipts can only be recorded by the native split workflow.'))
        return super().write(values)

    @api.model
    def _process_order(self, order, existing_order):
        if 'baseer_split_receipt' in order:
            expected = existing_order.baseer_split_receipt if existing_order else False
            value = order.pop('baseer_split_receipt')
            if type(value) is not type(expected) or value != expected:
                raise AccessError(_('Bill split receipts can only be recorded by the native split workflow.'))
        return super()._process_order(order, existing_order)

    def _baseer_check_split_access(self):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can split an order.'))
        self.check_access('write')
        if any(order.company_id not in self.env.companies for order in self):
            raise AccessError(_('The split order does not belong to an allowed company.'))

    def _baseer_check_split_source(self):
        self.ensure_one()
        self._baseer_check_split_access()
        self._baseer_assert_cancellation_batch(self.session_id.id)
        if (self.session_id.state != 'opened' or self.config_id.current_session_id != self.session_id
                or not self.config_id.iface_splitbill):
            raise ValidationError(_('Bill splitting requires the current open session with splitting enabled.'))
        if any(line.qty < 0 for line in self.lines):
            raise ValidationError(_('Refund items cannot be split by this workflow.'))
        if any((line.baseer_substitution_minimum_quantity or line.baseer_substitution_silent_quantity)
               for line in self.lines if 'baseer_substitution_silent_quantity' in line._fields):
            raise ValidationError(_('Complete protected item changes before splitting this order.'))
        State = self.env['baseer.print.preparation.state']
        lines = {line.uuid: line for line in self.lines}
        if any(state.line_uuid not in lines
               or state.quantity - State._kitchen_quantity(lines[state.line_uuid]) > 0.000001
               for state in self._baseer_preparation_states()):
            raise ValidationError(_('The saved kitchen state does not match this order. Reload it before splitting.'))

    def baseer_prepare_bill_split(self):
        self.ensure_one()
        self._baseer_check_split_source()
        self.env['baseer.print.preparation.state']._lock_orders_states(self)
        self.invalidate_recordset()
        self._baseer_check_split_source()
        return self._baseer_restaurant_merge_baseline()

    @api.model
    def _baseer_normalize_native_split(self, request, orders):
        if (type(request) is not dict or len(orders) != 2
                or set(request) != {'source_uuid', 'target_uuid', 'baseline', 'lines'}
                or self.env.context.get('baseer_restaurant_merge')):
            raise ValidationError(_('The native bill split request is invalid.'))
        for name in ('source_uuid', 'target_uuid'):
            try:
                if type(request[name]) is not str or str(UUID(request[name])) != request[name]:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValidationError(_('The native bill split request is invalid.')) from None
        if (request['source_uuid'] == request['target_uuid']
                or type(request['baseline']) is not str or len(request['baseline']) != 64
                or any(char not in '0123456789abcdef' for char in request['baseline'])
                or type(request['lines']) is not list or not 0 < len(request['lines']) <= 500
                or any(type(order) is not dict for order in orders)
                or any(type(order.get('uuid')) is not str for order in orders)
                or {order.get('uuid') for order in orders} != {request['source_uuid'], request['target_uuid']}):
            raise ValidationError(_('The native bill split request is invalid.'))
        sources, targets = set(), set()
        for line in request['lines']:
            if (type(line) is not dict or set(line) != {'source_uuid', 'target_uuid', 'quantity'}
                    or any(type(line[name]) is not str or not 0 < len(line[name]) <= 128
                           for name in ('source_uuid', 'target_uuid'))
                    or type(line['quantity']) not in (int, float) or not math.isfinite(line['quantity'])
                    or line['quantity'] <= 0 or line['source_uuid'] in sources or line['target_uuid'] in targets):
                raise ValidationError(_('The native bill split line map is invalid.'))
            sources.add(line['source_uuid'])
            targets.add(line['target_uuid'])

    def _baseer_split_discount_product(self):
        config = self.config_id
        return (config.discount_product_id if 'discount_product_id' in config._fields
                and config.module_pos_discount else self.env['product.product'])

    def _baseer_split_line_snapshot(self):
        discount_product = self._baseer_split_discount_product()
        return {line.uuid: (line.qty, self._baseer_merge_line_key(line))
                for line in self.lines if line.product_id != discount_product}

    @api.model
    def sync_from_ui(self, orders):
        request = self.env.context.get('baseer_native_split')
        if not request:
            return super().sync_from_ui(orders)
        self._baseer_normalize_native_split(request, orders)
        # Native sync mutates its dictionaries. Bind retries to the frozen request.
        digest = hashlib.sha256(json.dumps([request, orders], sort_keys=True).encode()).hexdigest()
        source = self.sudo().search([('uuid', '=', request['source_uuid'])], limit=1).with_env(self.env)
        if not source:
            raise ValidationError(_('The original bill split order was not found.'))
        source._baseer_check_split_access()
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                            ['baseer-native-split:' + request['target_uuid']])
        target = self.sudo().search([('uuid', '=', request['target_uuid'])], limit=1).with_env(self.env)
        pair = source | target
        pair._baseer_check_split_access()
        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(pair)
        pair.invalidate_recordset()
        if target:
            if (target.company_id != source.company_id or target.config_id != source.config_id
                    or target.session_id != source.session_id
                    or target.baseer_split_receipt != {'source_uuid': source.uuid, 'digest': digest}):
                raise ValidationError(_('This bill split has already been processed with different order data.'))
            # An acknowledged child can since have been paid or split again.
            return pair.read_pos_data([], source.config_id)
        source._baseer_check_split_source()
        if request['baseline'] != source._baseer_restaurant_merge_baseline():
            raise ValidationError(_('The order changed. Reload it before splitting again.'))
        for payload in orders:
            if (payload.get('state') != 'draft' or type(payload.get('session_id')) is not int
                    or type(payload.get('company_id')) is not int
                    or payload.get('session_id') != source.session_id.id
                    or payload.get('company_id') != source.company_id.id
                    or payload.get('config_id', source.config_id.id) != source.config_id.id
                    or payload.get('payment_ids') or payload.get('baseer_preparation_action')
                    or payload.get('to_invoice') or payload.get('account_move')
                    or payload.get('is_refund') or payload.get('amount_paid', 0) or payload.get('amount_return', 0)):
                raise ValidationError(_('Both split orders must be unpaid drafts in the same Point of Sale session.'))
        before = source._baseer_split_line_snapshot()
        moved = {line['source_uuid']: line for line in request['lines']}
        if any(uuid not in before or line['quantity'] > before[uuid][0] + 0.000001
               or line['target_uuid'] in before
               for uuid, line in moved.items()):
            raise ValidationError(_('The native bill split line map is invalid.'))
        if not any(qty - moved.get(uuid, {}).get('quantity', 0) > 0.000001 for uuid, (qty, _key) in before.items()):
            raise ValidationError(_('Pay the whole order instead of splitting every item into a new order.'))
        states = State.sudo()._states_for_orders(source)
        # Preserve a plain snapshot: native sync can remove original line rows.
        frozen_states = [dict(state.read(['company_id', 'line_uuid', 'product_id', 'printer_id',
                                          'route_id', 'copies', 'quantity', 'details'])[0]) for state in states]
        with self.env.cr.savepoint():
            super().sync_from_ui(deepcopy(orders))
            target = self.search([('uuid', '=', request['target_uuid'])], limit=1)
            if not target:
                raise ValidationError(_('The native bill split did not create its destination order.'))
            (source | target).invalidate_recordset()
            if (source.state != 'draft' or target.state != 'draft' or target.payment_ids
                    or target.company_id != source.company_id or target.config_id != source.config_id
                    or target.session_id != source.session_id):
                raise ValidationError(_('Both split orders must be unpaid drafts in the same Point of Sale session.'))
            remaining = source._baseer_split_line_snapshot()
            selected = target._baseer_split_line_snapshot()
            if set(remaining) - set(before) or set(selected) != {line['target_uuid'] for line in moved.values()}:
                raise ValidationError(_('The split orders do not preserve the original items.'))
            for uuid, (quantity, key) in before.items():
                transfer = moved.get(uuid)
                moved_qty = transfer['quantity'] if transfer else 0
                rest = remaining.get(uuid)
                if (rest and (rest[1] != key or abs(rest[0] - (quantity - moved_qty)) > 0.000001)
                        or not rest and abs(quantity - moved_qty) > 0.000001):
                    raise ValidationError(_('The split orders do not preserve the original items.'))
                if transfer:
                    new_qty, new_key = selected[transfer['target_uuid']]
                    if new_key != key or abs(new_qty - moved_qty) > 0.000001:
                        raise ValidationError(_('The split orders do not preserve the original items.'))
            self._baseer_transfer_split_states(source, target, frozen_states, moved)
            super(PosOrder, target).write({'baseer_split_receipt': {'source_uuid': source.uuid, 'digest': digest}})
            return (source | target).read_pos_data([], source.config_id)

    @api.model
    def _baseer_transfer_split_states(self, source, target, frozen_states, moved):
        State = self.env['baseer.print.preparation.state'].sudo()
        source_lines = {line.uuid: line for line in source.lines}
        target_lines = {line.uuid: line for line in target.lines}
        for snapshot in frozen_states:
            transfer = moved.get(snapshot['line_uuid'])
            if not transfer:
                continue
            quantity = min(snapshot['quantity'], transfer['quantity'])
            remainder = snapshot['quantity'] - quantity
            target_line = target_lines[transfer['target_uuid']]
            state = State.browse(snapshot['id']).exists()
            if not state or not State._same_logical_line(state, State._line_details(target_line)):
                raise ValidationError(_('The split kitchen item does not match the original kitchen item.'))
            if quantity > 0:
                values = {name: (snapshot[name][0] if snapshot[name] else False)
                          for name in ('company_id', 'product_id', 'printer_id', 'route_id')}
                details = dict(snapshot['details'], line_uuid=target_line.uuid, quantity=quantity)
                State.create({**values, 'order_id': target.id, 'order_line_id': target_line.id,
                              'line_uuid': target_line.uuid, 'copies': snapshot['copies'],
                              'quantity': quantity, 'details': details})
            if remainder > 0:
                source_line = source_lines.get(snapshot['line_uuid'])
                if not source_line or remainder - State._kitchen_quantity(source_line) > 0.000001:
                    raise ValidationError(_('The split kitchen item quantity is invalid.'))
                state.write({'quantity': remainder, 'order_line_id': source_line.id,
                             'details': dict(snapshot['details'], quantity=remainder)})
            else:
                state.unlink()
