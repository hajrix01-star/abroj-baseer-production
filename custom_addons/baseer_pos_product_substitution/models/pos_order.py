import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare


# An RPC context cannot impersonate this transaction-local internal capability.
_PROTECTED_COMMAND_TOKEN = object()


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_protected_revision = fields.Char(compute='_compute_baseer_protected_revision')

    @api.depends('write_date', 'state', 'lines.write_date', 'payment_ids.write_date')
    def _compute_baseer_protected_revision(self):
        for order in self:
            order.baseer_protected_revision = order._baseer_revision()

    def _baseer_revision(self):
        self.ensure_one()
        values = {
            'id': self.id, 'state': self.state, 'session': self.session_id.id,
            'company': self.company_id.id, 'pricelist': self.pricelist_id.id,
            'partner': self.partner_id.id, 'fiscal_position': self.fiscal_position_id.id,
            'write_date': str(self.write_date),
            'lines': [(line.id, line.uuid, line.product_id.id, line.qty, line.price_unit,
                       line.discount, sorted(line.tax_ids.ids), str(line.write_date))
                      for line in self.lines.sorted('id')],
            'payments': [(payment.id, payment.amount, str(payment.write_date))
                         for payment in self.payment_ids.sorted('id')],
        }
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + ['baseer_protected_revision'])) if inherited else inherited

    @api.model
    def _load_pos_data_read(self, records, config):
        result = super()._load_pos_data_read(records, config)
        by_id = {record.id: record for record in records}
        for value in result:
            value['baseer_protected_revision'] = by_id[value['id']]._baseer_revision()
        return result

    def _baseer_command_access_and_lock(self):
        self.ensure_one()
        if not self.exists() or not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can change a protected item.'))
        self.check_access('write')
        if self.company_id not in self.env.companies:
            raise AccessError(_('This order does not belong to an allowed company.'))
        self.env['baseer.print.preparation.state']._lock_order_state(self)
        self.invalidate_recordset()
        self.lines.invalidate_recordset()
        self.payment_ids.invalidate_recordset()
        self.check_access('write')
        if self.company_id not in self.env.companies:
            raise AccessError(_('This order does not belong to an allowed company.'))

    @api.model
    def _baseer_action_model(self, kind):
        if kind not in ('edit', 'cancel'):
            raise ValidationError(_('Choose edit or cancel.'))
        return self.env['baseer.pos.substitution' if kind == 'edit' else 'baseer.pos.protected_item_cancellation']

    @api.model
    def _baseer_action_fingerprint(self, kind, action):
        return hashlib.sha256(json.dumps({'kind': kind, 'action': action}, sort_keys=True,
                                        separators=(',', ':')).encode()).hexdigest()

    def _baseer_command_result(self, action_uuid=False, accepted=True):
        self.ensure_one()
        return {'action_uuid': action_uuid, 'accepted': accepted,
                'data': self.read_pos_data([], self.config_id),
                'revision': self._baseer_revision(), 'state': self.state}

    def baseer_read_protected_state(self):
        """Authoritative reconciliation; never writes or erases a local command."""
        self._baseer_command_access_and_lock()
        return self._baseer_command_result(accepted=False)

    def _baseer_validate_new_command(self, action, expected_revision):
        if (self.state != 'draft' or self.payment_ids or self.is_refund
                or self.amount_paid or self.amount_return
                or self.session_id.state != 'opened'
                or not self.config_id.baseer_substitution_enabled):
            raise AccessError(_('Only an unpaid draft in an open session can be edited or cancelled.'))
        if not expected_revision or expected_revision != self._baseer_revision():
            raise ValidationError(_('The order changed on another device. Refresh it before trying again.'))
        source = self.lines.filtered(lambda line: line.uuid == action['source_line_uuid'])
        if len(source) != 1 or source.qty <= 0 or not source.product_id.baseer_substitution_enabled:
            raise ValidationError(_('The protected item is no longer available.'))
        if source.uuid in self._baseer_substitution_locked_snapshots(self):
            raise AccessError(_('An accepted replacement cannot be edited or cancelled again.'))
        return source

    def _baseer_quote_replacements(self, source, action):
        requested = action['replacements']
        if len({item['line_uuid'] for item in requested}) != len(requested):
            raise ValidationError(_('Replacement line identifiers must be unique.'))
        if any(item['line_uuid'] in self.lines.mapped('uuid') for item in requested):
            raise ValidationError(_('Replacement lines must be new lines.'))
        products = self.env['product.product'].browse([item['product_id'] for item in requested]).exists()
        allowed = source.product_id.baseer_substitution_product_ids
        if len(products) != len(requested) or any(
                product not in allowed or not product.active or not product.available_in_pos
                or product.company_id and product.company_id != self.company_id for product in products):
            raise AccessError(_('One or more replacement products are not allowed for this item.'))
        totals = []
        for item in requested:
            product = products.filtered(lambda candidate: candidate.id == item['product_id'])
            price, taxes, amount = self._baseer_substitution_server_amount(self, product, item['quantity'])
            totals.append((item, product, price, taxes, amount))
        return totals

    def baseer_quote_protected_action(self, kind, raw_action, expected_revision):
        self._baseer_command_access_and_lock()
        action = self._baseer_action_model(kind)._normalize_action(raw_action)
        source = self._baseer_validate_new_command(action, expected_revision)
        quote = self._baseer_quote_replacements(source, action) if kind == 'edit' else []
        replacement = sum(item[4]['total_included'] for item in quote)
        return {'source_gross': source.price_subtotal_incl, 'replacement_gross': replacement,
                'valid': kind == 'cancel' or self.currency_id.is_zero(replacement - source.price_subtotal_incl),
                'revision': self._baseer_revision()}

    def _baseer_update_silent_baseline(self, source_uuid, replacements):
        try:
            baseline = json.loads(self.last_order_preparation_change or '{}')
        except (ValueError, TypeError):
            baseline = {}
        if not isinstance(baseline, dict):
            baseline = {}
        lines = baseline.get('lines')
        if not isinstance(lines, dict):
            lines = baseline['lines'] = {}
        for key, entry in list(lines.items()):
            if key == source_uuid or isinstance(entry, dict) and entry.get('uuid') == source_uuid:
                del lines[key]
        for line in replacements:
            lines[line.uuid] = {
                'uuid': line.uuid, 'product_id': line.product_id.id,
                'name': line.full_product_name, 'basic_name': line.product_id.name,
                'display_name': line.product_id.display_name, 'quantity': line.qty,
                'note': line.note or '', 'customer_note': line.customer_note or '',
                'attribute_value_names': [], 'isCombo': False,
            }
        baseline['metadata'] = {'serverDate': fields.Datetime.to_string(fields.Datetime.now())}
        self.write({'last_order_preparation_change': json.dumps(baseline)})

    def baseer_apply_protected_action(self, kind, raw_action, expected_revision):
        """Apply intent only, atomically. No client-supplied order/payments/totals."""
        with self.env.cr.savepoint():
            self._baseer_command_access_and_lock()
            Event = self._baseer_action_model(kind)
            action = Event._normalize_action(raw_action)
            fingerprint = self._baseer_action_fingerprint(kind, action)
            retry = Event.sudo().search([('order_id', '=', self.id),
                                         ('action_uuid', '=', action['action_uuid'])], limit=1)
            other_kind = self._baseer_action_model('cancel' if kind == 'edit' else 'edit')
            if other_kind.sudo().search_count([('order_id', '=', self.id), ('action_uuid', '=', action['action_uuid'])]):
                raise ValidationError(_('This action identifier was already used for another operation.'))
            if retry:
                if retry.request_fingerprint != fingerprint:
                    raise ValidationError(_('This action identifier was already used with different details.'))
                return self._baseer_command_result(action['action_uuid'])
            source = self._baseer_validate_new_command(action, expected_revision)
            snapshot = self._baseer_substitution_source_snapshot(source)
            quote = self._baseer_quote_replacements(source, action) if kind == 'edit' else []
            if kind == 'edit' and not self.currency_id.is_zero(
                    sum(row[4]['total_included'] for row in quote) - snapshot['gross']):
                raise ValidationError(_('Replacement products must equal the protected item total exactly.'))
            protected = self.with_context(baseer_protected_command=_PROTECTED_COMMAND_TOKEN)
            prepared = self.env['baseer.print.preparation.state'].sudo().search([
                ('order_id', '=', self.id), ('line_uuid', '=', source.uuid)])
            replacements = self.env['pos.order.line']
            for item, product, price, taxes, amounts in quote:
                replacements |= self.env['pos.order.line'].create({
                    'order_id': self.id, 'uuid': item['line_uuid'], 'product_id': product.id,
                    'qty': item['quantity'], 'price_unit': price, 'discount': 0,
                    'price_type': 'original', 'tax_ids': [(6, 0, taxes.ids)],
                    'full_product_name': product.display_name,
                    'price_subtotal': amounts['total_excluded'],
                    'price_subtotal_incl': amounts['total_included'],
                })
            source.with_context(baseer_protected_command=_PROTECTED_COMMAND_TOKEN).unlink()
            protected._compute_prices()
            if kind == 'cancel' and prepared:
                quantities = set(prepared.mapped('quantity'))
                if len(quantities) != 1:
                    raise ValidationError(_('The kitchen baseline changed. Refresh the order.'))
                self.env['baseer.print.preparation.state']._apply_action(protected, {
                    'action_uuid': action['action_uuid'], 'action_type': 'line_change',
                    'lines': [{'line_uuid': snapshot['line_uuid'], 'expected_quantity': quantities.pop(),
                               'new_quantity': 0, 'reason_code': action['reason_code'],
                               'reason_note': action['reason_note']}],
                })
            elif kind == 'edit':
                prepared.unlink()
            protected._baseer_update_silent_baseline(snapshot['line_uuid'], replacements)
            values = {
                'company_id': self.company_id.id, 'order_id': self.id,
                'pos_config_id': self.config_id.id, 'session_id': self.session_id.id,
                'cashier_id': self.env.user.id, 'action_uuid': action['action_uuid'],
                'request_fingerprint': fingerprint, 'request_payload': action,
                'event_at': fields.Datetime.now(),
                'order_reference': self.pos_reference or self.name or str(self.id),
                'source_product_id': snapshot['product_id'], 'source_line_uuid': snapshot['line_uuid'],
                'source_quantity': snapshot['quantity'], 'source_gross': snapshot['gross'],
                'currency_id': self.currency_id.id, 'reason_note': action['reason_note'] or False,
                'source_snapshot': snapshot,
            }
            if kind == 'edit':
                values.update(replacement_gross=sum(row[4]['total_included'] for row in quote),
                              replacement_product_ids=[(6, 0, replacements.product_id.ids)],
                              replacement_snapshot=[dict(self._baseer_substitution_source_snapshot(line),
                                                         tax_ids=line.tax_ids.ids)
                                                    for line in replacements])
            else:
                values['reason_code'] = action['reason_code']
            Event.with_context(baseer_substitution_internal=True,
                               baseer_protected_item_cancellation_internal=True).sudo().create(values)
            self.lines.invalidate_recordset(['baseer_substitution_minimum_quantity',
                                            'baseer_substitution_silent_quantity'])
            if not self.lines:
                released = protected._baseer_release_empty_table()
                # The protected cancellation also applies to counter orders,
                # where the restaurant-only release helper intentionally does
                # nothing. Never leave an acknowledged empty command as draft.
                if (not released and self.state == 'draft' and not self.payment_ids
                        and not self.account_move and not self.is_refund
                        and not self._baseer_has_native_preparation_obligation()
                        and all(self.currency_id.is_zero(value) for value in (
                            self.amount_total, self.amount_paid, self.amount_return))
                        and not self.env['baseer.print.preparation.state'].sudo().search_count([
                            ('order_id', '=', self.id), ('quantity', '!=', 0)])):
                    protected.action_pos_order_cancel()
            return self._baseer_command_result(action['action_uuid'])

    @api.model
    def _baseer_substitution_source_snapshot(self, line):
        return {
            'line_uuid': line.uuid,
            'product_id': line.product_id.id,
            'product_name': line.full_product_name or line.product_id.display_name,
            'quantity': line.qty,
            'unit_price': line.price_unit,
            'discount': line.discount,
            'gross': line.price_subtotal_incl,
            'tax_ids': line.tax_ids_after_fiscal_position.ids,
        }

    @api.model
    def _baseer_substitution_server_amount(self, order, product, quantity):
        """Return the Odoo-owned price/taxes/gross for one replacement line."""
        taxes = product.taxes_id.filtered_domain(
            self.env['account.tax']._check_company_domain(order.company_id)
        )
        mapped_taxes = order.fiscal_position_id.map_tax(taxes)
        price = order.pricelist_id._get_product_price(
            product.with_company(order.company_id), quantity, currency=order.currency_id,
        )
        price = self.env['account.tax']._fix_tax_included_price_company(
            price, taxes, mapped_taxes, order.company_id,
        )
        totals = mapped_taxes.compute_all(
            price, order.currency_id, quantity, product=product, partner=order.partner_id,
        )
        return price, taxes, totals

    @api.model
    def _baseer_substitution_validate_before_sync(self, existing_order, action):
        if not existing_order:
            raise AccessError(_('A substitution can only be made on an existing draft order.'))
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can substitute a protected item.'))
        existing_order.check_access_rights('read')
        existing_order.check_access_rule('read')
        if (existing_order.company_id not in self.env.companies
                or existing_order.state != 'draft'
                or existing_order.is_refund
                or existing_order.session_id.state not in ('opened', 'closing_control')):
            raise AccessError(_('This order cannot be changed by a substitution.'))
        if not existing_order.config_id.baseer_substitution_enabled:
            raise AccessError(_('Controlled substitutions are disabled for this Point of Sale.'))
        self.env['baseer.print.preparation.state']._lock_order_state(existing_order)
        source = existing_order.lines.filtered(lambda line: line.uuid == action['source_line_uuid'])
        if len(source) != 1 or source.qty <= 0 or not source.product_id.baseer_substitution_enabled:
            raise ValidationError(_('The protected item is no longer available for substitution.'))
        allowed = source.product_id.baseer_substitution_product_ids
        requested_ids = {item['product_id'] for item in action['replacements']}
        products = self.env['product.product'].browse(list(requested_ids)).exists()
        if len(products) != len(requested_ids) or any(product not in allowed for product in products):
            raise AccessError(_('One or more replacement products are not allowed for this item.'))
        return source.ensure_one(), self._baseer_substitution_source_snapshot(source)

    @api.model
    def _baseer_substitution_validate_after_sync(self, order, source, source_snapshot, action):
        """Make native draft lines authoritative before recording the audit event."""
        if source.exists():
            raise ValidationError(_('The protected item must be fully substituted in one action.'))
        replacement_lines = self.env['pos.order.line']
        expected_by_uuid = {item['line_uuid']: item for item in action['replacements']}
        actual_by_uuid = {line.uuid: line for line in order.lines if line.uuid in expected_by_uuid}
        if set(actual_by_uuid) != set(expected_by_uuid):
            raise ValidationError(_('The replacement order lines do not match the substitution request.'))
        snapshots = []
        total_gross = 0.0
        for line_uuid, expected in expected_by_uuid.items():
            line = actual_by_uuid[line_uuid]
            if line.product_id.id != expected['product_id'] or abs(line.qty - expected['quantity']) > 0.000001:
                raise ValidationError(_('The replacement quantity changed before it was saved.'))
            price, taxes, totals = self._baseer_substitution_server_amount(order, line.product_id, line.qty)
            # Browsers may only propose product and quantity.  Price/tax values are always reset here.
            line.write({
                'price_unit': price,
                'discount': 0.0,
                'price_type': 'original',
                'tax_ids': [(6, 0, taxes.ids)],
                'price_subtotal': totals['total_excluded'],
                'price_subtotal_incl': totals['total_included'],
            })
            replacement_lines |= line
            total_gross += totals['total_included']
            snapshots.append({
                'line_uuid': line.uuid,
                'product_id': line.product_id.id,
                'product_name': line.full_product_name or line.product_id.display_name,
                'quantity': line.qty,
                'unit_price': price,
                'discount': 0.0,
                'gross': totals['total_included'],
                'tax_ids': taxes.ids,
            })
        source_gross = source_snapshot['gross']
        if not order.currency_id.is_zero(total_gross - source_gross):
            raise ValidationError(_(
                'Replacement products must equal the protected item total exactly. Source: %(source)s; replacements: %(replacement)s.',
                source=order.currency_id.format(source_gross),
                replacement=order.currency_id.format(total_gross),
            ))
        return replacement_lines, total_gross, snapshots

    @api.model
    def _baseer_protected_cancellation_validate_before_sync(self, existing_order, action, raw_preparation):
        # Cancellation shares the same draft/session/company/source safeguards as substitution,
        # but deliberately has no replacement-products requirement.
        if not existing_order:
            raise AccessError(_('A protected item can only be cancelled on an existing draft order.'))
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can cancel a protected item.'))
        if (existing_order.company_id not in self.env.companies or existing_order.state != 'draft'
                or existing_order.is_refund or existing_order.session_id.state not in ('opened', 'closing_control')
                or not existing_order.config_id.baseer_substitution_enabled):
            raise AccessError(_('This order cannot be changed by a protected item cancellation.'))
        self.env['baseer.print.preparation.state']._lock_order_state(existing_order)
        source = existing_order.lines.filtered(lambda line: line.uuid == action['source_line_uuid'])
        if len(source) != 1 or source.qty <= 0 or not source.product_id.baseer_substitution_enabled:
            raise ValidationError(_('The protected item is no longer available for cancellation.'))
        prepared = self.env['baseer.print.preparation.state'].sudo().search([
            ('order_id', '=', existing_order.id), ('line_uuid', '=', source.uuid),
        ])
        if prepared:
            if not raw_preparation:
                raise AccessError(_('This item was sent to the kitchen and must include its kitchen cancellation.'))
            preparation = self.env['baseer.print.preparation.state']._normalize_action(raw_preparation)
            matching = [item for item in preparation['lines'] if item['line_uuid'] == source.uuid]
            if (len(matching) != 1 or matching[0]['new_quantity'] != 0
                    or matching[0]['reason_code'] != action['reason_code']
                    or (matching[0]['reason_note'] or '').strip() != action['reason_note']):
                raise ValidationError(_('The kitchen cancellation must match the protected item cancellation reason.'))
        return source.ensure_one(), self._baseer_substitution_source_snapshot(source)

    @api.model
    def _baseer_substitution_remove_kitchen_baseline(self, order, source_line_uuid):
        """A substitution is silent: discard only the operational baseline, never the audit record."""
        states = self.env['baseer.print.preparation.state'].sudo().search([
            ('order_id', '=', order.id), ('line_uuid', '=', source_line_uuid),
        ])
        states.unlink()

    @api.model
    def _baseer_assert_protected_lines_unchanged(self, previous, updated):
        """Server-side guard for stale clients or RPC payload tampering.

        A protected source line may be removed only in the validated action
        below. It may not be silently removed or reduced by a native sync.
        """
        current = {line.uuid: line for line in updated.lines}
        for line_uuid, quantity in previous.items():
            line = current.get(line_uuid)
            if not line or line.qty < quantity - 0.000001:
                raise AccessError(_('A protected item must be substituted; it cannot be deleted or reduced directly.'))

    @api.model
    def _baseer_substitution_locked_snapshots(self, order):
        events = self.env['baseer.pos.substitution'].sudo().search([('order_id', '=', order.id)])
        return {
            item['line_uuid']: item
            for event in events
            for item in (event.replacement_snapshot or [])
            if item.get('line_uuid')
        }

    @api.model
    def _baseer_assert_substitution_lines_unchanged(self, snapshots, updated):
        """Keep lines created by a substitution from being silently removed or edited.

        The immutable substitution event is authoritative; this does not depend on
        the replacement product's own substitution setting.
        """
        if not snapshots:
            return
        lines_by_uuid = {}
        for line in updated.lines:
            if line.uuid:
                lines_by_uuid.setdefault(line.uuid, []).append(line)
        currency = updated.currency_id
        for line_uuid, snapshot in snapshots.items():
            matches = lines_by_uuid.get(line_uuid, [])
            if len(matches) != 1:
                raise AccessError(_('A substituted item cannot be removed or duplicated.'))
            line = matches[0]
            rounding = line.product_id.uom_id.rounding
            if (line.product_id.id != snapshot['product_id']
                    or float_compare(line.qty, snapshot['quantity'], precision_rounding=rounding) < 0
                    or currency.compare_amounts(line.price_unit, snapshot['unit_price']) != 0
                    or float_compare(line.discount, snapshot.get('discount', 0.0), precision_digits=4) != 0
                    or set(line.tax_ids.ids) != set(snapshot.get('tax_ids', []))):
                raise AccessError(_('A substituted item cannot be changed or reduced below its original quantity.'))

    @api.model
    def _process_order(self, order, existing_order):
        order.pop('baseer_protected_revision', None)
        # Protected actions are commands, not metadata on ordinary save/payment.
        # Legacy clients may resend an acknowledged action, but must still run
        # native payment processing and must not reintroduce obsolete lines.
        raw_cancellation = order.pop('baseer_protected_item_cancellation_action', False)
        raw_action = order.pop('baseer_substitution_action', False)
        if raw_cancellation and raw_action:
            raise AccessError(_('A protected item cannot be edited and cancelled in the same action.'))
        locked_before = {}
        protected_before = {}
        if existing_order:
            existing_order._baseer_command_access_and_lock()
            if existing_order.state != 'draft' and order.get('state') == 'draft':
                raise ValidationError(_('This order is already completed. Refresh its saved state.'))
            locked_before = self._baseer_substitution_locked_snapshots(existing_order)
            if existing_order.config_id.baseer_substitution_enabled:
                protected_before = {line.uuid: line.qty for line in existing_order.lines
                                    if line.product_id.baseer_substitution_enabled and line.qty > 0
                                    and line.uuid not in locked_before}
        if raw_action or raw_cancellation:
            kind = 'edit' if raw_action else 'cancel'
            Event = self._baseer_action_model(kind)
            action = Event._normalize_action(raw_action or raw_cancellation)
            retry = Event.sudo().search([('order_id', '=', existing_order.id if existing_order else 0),
                                         ('action_uuid', '=', action['action_uuid'])], limit=1)
            if not retry or retry.request_fingerprint != self._baseer_action_fingerprint(kind, action):
                raise ValidationError(_('This client uses an obsolete edit workflow. Refresh the Point of Sale before continuing.'))
            # Exact saved actions are harmless metadata, not an instruction to
            # skip native synchronization/payment. Existing locks/tombstones
            # below reject stale or collateral line mutations.
        order_id = super()._process_order(order, existing_order)
        updated = self.browse(order_id)
        self._baseer_assert_protected_lines_unchanged(protected_before, updated)
        self._baseer_assert_substitution_lines_unchanged(locked_before, updated)
        updated._baseer_assert_no_obsolete_lines()
        return order_id

    def _baseer_assert_no_obsolete_lines(self):
        for order in self:
            obsolete = set()
            for model in ('baseer.pos.substitution', 'baseer.pos.protected_item_cancellation'):
                obsolete.update(self.env[model].sudo().search([('order_id', '=', order.id)]).mapped('source_line_uuid'))
            if obsolete.intersection(order.lines.mapped('uuid')):
                raise AccessError(_('A removed protected item cannot be restored from an outdated device. Refresh the order.'))

    def unlink(self):
        events = self.env['baseer.pos.substitution'].sudo().search([('order_id', 'in', self.ids)])
        cancellations = self.env['baseer.pos.protected_item_cancellation'].sudo().search([('order_id', 'in', self.ids)])
        if events or cancellations:
            raise AccessError(_('An order with substitution audit records cannot be deleted.'))
        return super().unlink()


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_substitution_minimum_quantity = fields.Float(compute='_compute_baseer_substitution_policy')
    baseer_substitution_silent_quantity = fields.Float(compute='_compute_baseer_substitution_policy')

    @api.depends('order_id', 'uuid')
    def _compute_baseer_substitution_policy(self):
        policies = {order.id: self.env['pos.order']._baseer_substitution_locked_snapshots(order)
                    for order in self.order_id}
        for line in self:
            snapshot = policies.get(line.order_id.id, {}).get(line.uuid, {})
            line.baseer_substitution_minimum_quantity = snapshot.get('quantity', 0)
            line.baseer_substitution_silent_quantity = snapshot.get('quantity', 0)

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + [
            'baseer_substitution_minimum_quantity', 'baseer_substitution_silent_quantity',
        ])) if inherited else inherited

    @api.model_create_multi
    def create(self, values_list):
        order_ids = sorted({values.get('order_id') for values in values_list if values.get('order_id')})
        for order in self.env['pos.order'].browse(order_ids):
            self.env['baseer.print.preparation.state']._lock_order_state(order)
        sanitized = []
        for values in values_list:
            values = dict(values)
            values.pop('baseer_substitution_minimum_quantity', None)
            values.pop('baseer_substitution_silent_quantity', None)
            sanitized.append(values)
        lines = super().create(sanitized)
        lines.order_id._baseer_assert_no_obsolete_lines()
        return lines

    def write(self, values):
        values = dict(values)
        values.pop('baseer_substitution_minimum_quantity', None)
        values.pop('baseer_substitution_silent_quantity', None)
        previous_orders = self.mapped('order_id')
        for order in previous_orders.sorted('id'):
            self.env['baseer.print.preparation.state']._lock_order_state(order)
        self.invalidate_recordset()
        internal = self.env.context.get('baseer_protected_command') is _PROTECTED_COMMAND_TOKEN
        if not internal:
            for line in self.filtered(lambda row: row.order_id.state == 'draft'
                                      and row.order_id.config_id.baseer_substitution_enabled
                                      and row.product_id.baseer_substitution_enabled and row.qty > 0):
                if line.uuid in self.env['pos.order']._baseer_substitution_locked_snapshots(line.order_id):
                    continue
                if ('qty' in values and values['qty'] < line.qty - 0.000001
                        or 'order_id' in values and values['order_id'] != line.order_id.id
                        or 'uuid' in values and values['uuid'] != line.uuid
                        or 'product_id' in values and values['product_id'] != line.product_id.id):
                    raise AccessError(_('Use the documented edit or cancellation action for this protected item.'))
        result = super().write(values)
        orders = previous_orders | self.mapped('order_id')
        for order in orders:
            snapshots = self.env['pos.order']._baseer_substitution_locked_snapshots(order)
            if snapshots:
                self.env['pos.order']._baseer_assert_substitution_lines_unchanged(snapshots, order)
        (previous_orders | self.order_id)._baseer_assert_no_obsolete_lines()
        return result

    def unlink(self):
        for order in self.order_id.sorted('id'):
            self.env['baseer.print.preparation.state']._lock_order_state(order)
        self.invalidate_recordset()
        internal = self.env.context.get('baseer_protected_command') is _PROTECTED_COMMAND_TOKEN
        if not internal and any(line.qty > 0 and line.order_id.state == 'draft'
                                and line.order_id.config_id.baseer_substitution_enabled
                                and line.product_id.baseer_substitution_enabled for line in self):
            raise AccessError(_('Use the documented edit or cancellation action for this protected item.'))
        DraftOrder = self.env['pos.order'].sudo()
        for order in self.mapped('order_id').filtered(lambda item: item.state in ('draft', 'cancel')):
            snapshots = DraftOrder._baseer_substitution_locked_snapshots(order)
            if any(line.uuid in snapshots for line in self.filtered(lambda item: item.order_id == order)):
                self.env['baseer.print.preparation.state']._lock_order_state(order)
                raise AccessError(_('A substituted item cannot be removed from the order.'))
        return super().unlink()
