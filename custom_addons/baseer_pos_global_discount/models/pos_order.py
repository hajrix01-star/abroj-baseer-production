"""Owned discount commands. Native account.tax is the only tax calculator."""
import hashlib
import hmac
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID, uuid4

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_TOKEN = object()
_OFFLINE_TOKEN = object()
_DRAFT_TOKEN = object()
_PREFIX = 'baseer_global_discount_'
_ORDER_METADATA = {'baseer_global_discount_kind', 'baseer_global_discount_value',
                   'baseer_global_discount_gross', 'baseer_global_discount_locked',
                   'baseer_global_discount_reason', 'baseer_global_discount_snapshot',
                   'baseer_offline_draft_kind', 'baseer_offline_draft_value',
                   'baseer_offline_draft_revision', 'baseer_offline_draft_command_uuid',
                   'baseer_offline_draft_digest'}
_LINE_METADATA = {'baseer_global_discount_line', 'baseer_global_discount_source_id'}
_FINANCIAL = {'product_id', 'qty', 'price_unit', 'discount', 'tax_ids', 'extra_tax_data',
              'uuid', 'order_id', 'refunded_orderline_id', 'combo_parent_id', 'combo_line_ids', 'combo_item_id'}
_HEADER = {'session_id', 'company_id', 'config_id', 'pricelist_id', 'fiscal_position_id', 'partner_id', 'uuid', 'is_refund'}


def _internal(env):
    return env.context.get('_baseer_global_discount_token') is _TOKEN


def _draft_sync(env):
    value = env.context.get('_baseer_draft_apply')
    return isinstance(value, tuple) and len(value) == 2 and value[0] is _DRAFT_TOKEN


def _number(value):
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', value):
        raise ValidationError(_('Enter a positive number using 0-9 and at most two decimal places.'))
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValidationError(_('Enter a valid discount.')) from None
    if not result.is_finite() or result > Decimal('1000000000'):
        raise ValidationError(_('The discount amount is too large.'))
    return result


def _same(record, key, value):
    current = record[key]
    field = record._fields[key]
    if field.type == 'many2one':
        return (current.id or False) == (value or False)
    if field.type in ('many2many', 'one2many'):
        if isinstance(value, (list, tuple)) and all(type(item) is int for item in value):
            return set(value) == set(current.ids)
        ids = set(current.ids)
        for command in value:
            if command[0] == 6:
                ids = set(command[2])
            elif command[0] == 5:
                ids = set()
            elif command[0] == 4:
                ids.add(command[1])
            elif command[0] == 3:
                ids.discard(command[1])
            else:
                return False
        return ids == set(current.ids)
    if field.type == 'json':
        return (current or {}) == (value or {})
    return (current or False) == (value or False)


class DiscountEvent(models.Model):
    _name = 'baseer.pos.global.discount.event'
    _description = 'Immutable invoice discount command'
    _order = 'id desc'

    order_id = fields.Many2one('pos.order', ondelete='set null', index=True)
    order_uuid = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    action_uuid = fields.Char(required=True, index=True)
    fingerprint = fields.Char(required=True)
    payload = fields.Json(required=True)
    _unique_action = models.Constraint('unique(action_uuid)', 'This discount command already exists.')

    @api.model_create_multi
    def create(self, values):
        if not _internal(self.env):
            raise AccessError(_('Discount audit records are created by the invoice discount command only.'))
        return super().create(values)

    def write(self, values):
        raise AccessError(_('Discount audit records cannot be changed.'))

    def unlink(self):
        raise AccessError(_('Discount audit records cannot be removed.'))

    def check_access_rule(self, operation):
        super().check_access_rule(operation)
        if any(event.company_id not in self.env.companies for event in self):
            raise AccessError(_('This discount belongs to another company.'))


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_global_discount_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount'), ('refund', 'Refund allocation')], readonly=True, copy=False)
    baseer_global_discount_value = fields.Char(readonly=True, copy=False)
    baseer_global_discount_gross = fields.Monetary(readonly=True, copy=False)
    baseer_global_discount_reason = fields.Char(readonly=True, copy=False)
    baseer_global_discount_locked = fields.Boolean(readonly=True, copy=False)
    baseer_global_discount_snapshot = fields.Json(readonly=True, copy=False)
    baseer_offline_draft_kind = fields.Selection([('percent', 'Percentage'), ('fixed', 'Fixed amount')], readonly=True, copy=False)
    baseer_offline_draft_value = fields.Char(readonly=True, copy=False)
    baseer_offline_draft_revision = fields.Integer(readonly=True, copy=False, default=0)
    baseer_offline_draft_command_uuid = fields.Char(readonly=True, copy=False)
    baseer_offline_draft_digest = fields.Char(readonly=True, copy=False)

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        private = {'baseer_global_discount_snapshot', 'baseer_offline_draft_command_uuid', 'baseer_offline_draft_digest'}
        return list(dict.fromkeys(inherited + sorted(_ORDER_METADATA - private))) if inherited else inherited

    def _gd_internal(self):
        return self.with_context(_baseer_global_discount_token=_TOKEN)

    @api.model
    def _gd_offline_intent(self, raw, order):
        """Validate untrusted local intent before passing it through native sync."""
        keys = {'version', 'order_uuid', 'action_uuid', 'kind', 'value', 'expected_total', 'expected_tax',
                'preview_line_uuids', 'account_proof'}
        if not isinstance(raw, dict) or set(raw) != keys or type(raw['version']) is not int or raw['version'] != 1:
            raise ValidationError(_('The offline discount needs review before synchronization.'))
        for key in ('order_uuid', 'action_uuid'):
            try:
                if str(UUID(raw[key])) != raw[key]:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValidationError(_('The offline discount identifier is invalid.')) from None
        if raw['order_uuid'] != order.get('uuid') or raw['kind'] not in ('fixed', 'percent'):
            raise ValidationError(_('The offline discount does not match this order.'))
        if not isinstance(raw['account_proof'], str) or not re.fullmatch(r'[0-9a-f]{64}', raw['account_proof']):
            raise ValidationError(_('The offline discount account proof is missing or invalid. Keep the paid order for manager review.'))
        if _number(raw['value']) <= 0:
            raise ValidationError(_('Enter a positive discount.'))
        for key in ('expected_total', 'expected_tax'):
            _number(raw[key])
        previews = raw['preview_line_uuids']
        if (not isinstance(previews, list) or not previews or len(previews) > 200
                or not all(isinstance(value, str) for value in previews) or len(set(previews)) != len(previews)):
            raise ValidationError(_('The offline discount preview is invalid.'))
        for value in previews:
            try:
                if str(UUID(value)) != value:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise ValidationError(_('The offline discount preview is invalid.')) from None
        return dict(raw)

    @api.model
    def _gd_offline_preview(self, order, intent, config):
        """Discard only explicitly named preview lines and retain tax proof."""
        preview_ids, found, kept, proof = set(intent['preview_line_uuids']), set(), [], []
        product_id = config.baseer_global_discount_product_id.id
        for command in order.get('lines', []):
            values = command[2] if len(command) > 2 and isinstance(command[2], dict) else {}
            line_uuid = values.get('uuid')
            if line_uuid not in preview_ids:
                if values.get('product_id') == product_id:
                    raise AccessError(_('Use the invoice discount command instead of adding its product manually.'))
                kept.append(command)
                continue
            if command[0] != 0 or values.get('product_id') != product_id or line_uuid in found:
                raise ValidationError(_('The offline discount preview is invalid.'))
            found.add(line_uuid)
            tax_ids = set()
            commands = values.get('tax_ids')
            if not isinstance(commands, (list, tuple)):
                raise ValidationError(_('The offline discount tax evidence is missing.'))
            # Native POS serializer sends IDs directly for non-dynamic
            # many-to-many models; other native callers may send ORM commands.
            if all(type(tax_id) is int for tax_id in commands):
                commands = [(6, 0, commands)]
            for tax_command in commands:
                if not isinstance(tax_command, (list, tuple)) or not tax_command:
                    raise ValidationError(_('The offline discount tax evidence is invalid.'))
                if tax_command[0] == 6 and len(tax_command) == 3 and isinstance(tax_command[2], (list, tuple)):
                    tax_ids = set(tax_command[2])
                elif tax_command[0] == 4 and len(tax_command) >= 2:
                    tax_ids.add(tax_command[1])
                elif tax_command[0] == 5:
                    tax_ids.clear()
                else:
                    raise ValidationError(_('The offline discount tax evidence is invalid.'))
            if not all(type(tax_id) is int and tax_id > 0 for tax_id in tax_ids):
                raise ValidationError(_('The offline discount tax evidence is invalid.'))
            amounts = []
            for name in ('price_subtotal', 'price_subtotal_incl'):
                try:
                    value = Decimal(str(values[name]))
                except (KeyError, InvalidOperation, TypeError, ValueError):
                    raise ValidationError(_('The offline discount amount evidence is missing.')) from None
                if not value.is_finite() or value > 0 or value < -Decimal('1000000000'):
                    raise ValidationError(_('The offline discount amount evidence is invalid.'))
                amounts.append(str(value))
            proof.append({'uuid': line_uuid, 'tax_ids': sorted(tax_ids), 'base': amounts[0], 'gross': amounts[1]})
        if found != preview_ids:
            raise ValidationError(_('The offline discount preview is incomplete.'))
        return kept, sorted(proof, key=lambda item: item['uuid'])

    @api.model
    def _gd_offline_fingerprint(self, intent, proof, order_digest):
        return hashlib.sha256(json.dumps({
            'intent': intent, 'proof': proof, 'order_digest': order_digest,
        }, sort_keys=True).encode()).hexdigest()

    @api.model
    def _gd_offline_order_digest(self, order):
        # Capture the client payload before native sync adjusts session, lines,
        # totals or the client-selected order date. On lost acknowledgements an
        # exact retry is safe; an altered sale must not be silently accepted.
        # Hash all sent fields (including sale, payment and relation commands),
        # rather than a fragile allowlist that can miss a new POS extension.
        return hashlib.sha256(json.dumps(order, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()

    @api.model
    def baseer_cancel_offline_draft(self, order_uuid, revision, command_uuid):
        try:
            if str(UUID(order_uuid)) != order_uuid or str(UUID(command_uuid)) != command_uuid:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ValidationError(_('The shared order cancellation identifier is invalid.')) from None
        if type(revision) is not int or revision < 1:
            raise ValidationError(_('The shared order cancellation revision is invalid.'))
        self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [order_uuid])
        order = self.search([('uuid', '=', order_uuid)], limit=1)
        if not order:
            raise ValidationError(_('The shared order is no longer available.'))
        order._gd_lock()
        order.invalidate_recordset()
        digest = self._gd_offline_order_digest({'uuid': order_uuid, 'revision': revision,
                                                'command_uuid': command_uuid, 'operation': 'cancel'})
        if order.baseer_offline_draft_command_uuid == command_uuid:
            if order.baseer_offline_draft_digest != digest or order.state != 'cancel':
                raise ValidationError(_('The shared order retry differs from the saved command.'))
            return {'uuid': order.uuid, 'state': order.state, 'revision': order.baseer_offline_draft_revision}
        if order.state != 'draft' or order.baseer_offline_draft_revision != revision:
            raise ValidationError(_('This shared order changed on another device. Keep your local changes for review.'))
        if (order.payment_ids or not order.currency_id.is_zero(order.amount_paid)
                or self.env['baseer.print.preparation.state'].sudo().search_count([('order_id', '=', order.id)])
                or self.env['baseer.print.job'].sudo().search_count([
                    ('source_order_id', '=', order.id), ('ticket_type', '=', 'preparation')])):
            raise ValidationError(_('This order has a payment or kitchen activity. Use the protected cancellation workflow or ask a manager.'))
        order._gd_internal().write({'baseer_offline_draft_revision': revision + 1,
                                    'baseer_offline_draft_command_uuid': command_uuid,
                                    'baseer_offline_draft_digest': digest})
        order._gd_internal().action_pos_order_cancel()
        return {'uuid': order.uuid, 'state': order.state, 'revision': order.baseer_offline_draft_revision}

    @api.model
    def sync_from_ui(self, orders):
        # Native sync normally returns an existing paid order without checking
        # the payload. Only an exact acknowledged offline command may be retried.
        order_digests = {}
        draft_commands = {}
        # Take these locks before looking up whether a shared draft exists: an
        # older client without a revision can race its very first creation.
        # Sorting also avoids inverse UUID lock ordering in batch syncs.
        uuids = [order.get('uuid') for order in orders]
        if any(not isinstance(value, str) or not value for value in uuids):
            raise ValidationError(_('A point of sale order identifier is required.'))
        for order_uuid in sorted(set(uuids)):
            self.env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [order_uuid])
        for order in orders:
            command = order.get('baseer_offline_draft_command')
            if order.get('state') == 'draft' and order.get('baseer_offline_discount_intent') and not command:
                raise ValidationError(_('This discount draft needs a shared order revision. Refresh the point of sale.'))
            existing_draft = self._get_open_order(order)
            if command or (existing_draft and existing_draft.baseer_offline_draft_revision):
                if not isinstance(command, dict) or set(command) != {'revision', 'command_uuid', 'operation'}:
                    raise ValidationError(_('This shared order needs its current discount revision. Refresh before changing it.'))
                if type(command['revision']) is not int or command['revision'] < 0 or command['operation'] not in ('set', 'remove', 'keep'):
                    raise ValidationError(_('The shared order discount command is invalid.'))
                try:
                    if str(UUID(command['command_uuid'])) != command['command_uuid']:
                        raise ValueError()
                except (ValueError, TypeError, AttributeError):
                    raise ValidationError(_('The shared order command identifier is invalid.')) from None
                order_uuid = order.get('uuid')
                if order_uuid in draft_commands:
                    raise ValidationError(_('The same shared order cannot be synchronized twice in one request.'))
                # The same lock is used by ticket reservation, before the order
                # row lock, so concurrent first saves cannot both create it.
                existing_draft = self._get_open_order(order)
                digest = self._gd_offline_order_digest(order)
                retry = False
                if existing_draft:
                    existing_draft._gd_lock()
                    existing_draft.invalidate_recordset()
                    if existing_draft.baseer_offline_draft_command_uuid == command['command_uuid']:
                        if existing_draft.baseer_offline_draft_digest != digest:
                            raise ValidationError(_('The shared order retry differs from the saved command.'))
                        retry = True
                    elif existing_draft.baseer_offline_draft_revision != command['revision']:
                        raise ValidationError(_('This shared order changed on another device. Keep your local changes for review.'))
                    elif existing_draft.state != 'draft':
                        raise ValidationError(_('This shared order was already paid. Keep your local changes for review.'))
                elif command['revision'] != 0:
                    raise ValidationError(_('This shared order revision is no longer available.'))
                has_intent = bool(order.get('baseer_offline_discount_intent'))
                if has_intent and not isinstance(order['baseer_offline_discount_intent'], dict):
                    raise ValidationError(_('The shared order discount command is invalid.'))
                if (command['operation'] == 'remove' and has_intent or
                    command['operation'] == 'set' and not has_intent or
                    command['operation'] == 'keep' and bool(existing_draft and existing_draft.baseer_offline_draft_kind) != has_intent):
                    raise ValidationError(_('The shared order discount command is incomplete.'))
                if (command['operation'] == 'keep' and has_intent and existing_draft and
                        (order['baseer_offline_discount_intent'].get('kind') != existing_draft.baseer_offline_draft_kind or
                         order['baseer_offline_discount_intent'].get('value') != existing_draft.baseer_offline_draft_value)):
                    raise ValidationError(_('Changing a shared order discount requires a new discount command.'))
                draft_commands[order_uuid] = (command, digest, retry)
            if not order.get('baseer_offline_discount_intent'):
                continue
            order_digest = self._gd_offline_order_digest(order)
            order_uuid = order.get('uuid')
            if order_uuid in order_digests:
                raise ValidationError(_('The same offline order cannot be synchronized twice in one request.'))
            order_digests[order_uuid] = order_digest
            existing = self._get_open_order(order)
            if not existing or existing.state == 'draft':
                continue
            existing.check_access('read')
            if existing.company_id not in self.env.companies:
                raise AccessError(_('The offline discount belongs to another company.'))
            intent = self._gd_offline_intent(order['baseer_offline_discount_intent'], order)
            _kept, proof = self._gd_offline_preview(order, intent, existing.config_id)
            event = self.env['baseer.pos.global.discount.event'].sudo().search([
                ('order_id', '=', existing.id), ('action_uuid', '=', intent['action_uuid']),
            ], limit=1)
            if not event or event.fingerprint != self._gd_offline_fingerprint(intent, proof, order_digest):
                raise ValidationError(_('The offline discount retry differs from the paid order. Keep it for manager review.'))
        scoped = self.with_context(_baseer_offline_digests=(_OFFLINE_TOKEN, order_digests),
                                   _baseer_draft_commands=(_DRAFT_TOKEN, draft_commands))
        return super(PosOrder, scoped).sync_from_ui(orders)

    @api.model
    def _process_order(self, order, existing_order):
        command = order.pop('baseer_offline_draft_command', False)
        draft_scope = self.env.context.get('_baseer_draft_commands')
        draft_data = draft_scope[1].get(order.get('uuid')) if isinstance(draft_scope, tuple) and len(draft_scope) == 2 and draft_scope[0] is _DRAFT_TOKEN else None
        if command and not draft_data:
            raise AccessError(_('Shared order commands must use point of sale synchronization.'))
        if draft_data and draft_data[2]:
            return existing_order.id
        if draft_data and existing_order:
            owned = existing_order.lines.filtered('baseer_global_discount_line')
            owned_ids = set(owned.ids)
            if any(len(item) > 1 and item[0] in (1, 2, 3, 4) and item[1] in owned_ids for item in order.get('lines', [])):
                raise AccessError(_('Shared discount lines are managed by the server.'))
            internal = existing_order._gd_internal()
            internal.lines.filtered('baseer_global_discount_line').unlink()
            internal.write({'baseer_global_discount_locked': False, 'baseer_global_discount_snapshot': False,
                            'baseer_global_discount_kind': False, 'baseer_global_discount_value': False,
                            'baseer_global_discount_reason': False, 'baseer_global_discount_gross': 0})
        if draft_data:
            self = self.with_context(_baseer_draft_apply=(_DRAFT_TOKEN, draft_data))
            if existing_order:
                existing_order = existing_order.with_env(self.env)
        raw = order.pop('baseer_offline_discount_intent', False)
        if not raw:
            return super()._process_order(order, existing_order)
        intent = self._gd_offline_intent(raw, order)
        session = self.env['pos.session'].browse(order.get('session_id')).exists()
        if len(session) != 1 or session.config_id.company_id not in self.env.companies:
            raise AccessError(_('The offline discount session is not available in this company.'))
        if existing_order and existing_order.baseer_global_discount_locked:
            raise ValidationError(_('Remove the existing invoice discount while connected before using offline discount.'))
        kept, proof = self._gd_offline_preview(order, intent, session.config_id)
        order['lines'] = kept
        digests = self.env.context.get('_baseer_offline_digests')
        if not isinstance(digests, tuple) or len(digests) != 2 or digests[0] is not _OFFLINE_TOKEN:
            raise AccessError(_('The offline discount must be synchronized through the point of sale.'))
        order_digest = digests[1].get(intent['order_uuid'])
        if not order_digest:
            raise ValidationError(_('The offline order fingerprint is missing.'))
        scoped = self.with_context(_baseer_offline_discount=(_OFFLINE_TOKEN, intent, proof, order_digest))
        # Native _process_order reuses the existing recordset directly. Its
        # environment otherwise keeps the caller context and silently drops
        # our private reconciliation intent for previously synced drafts.
        existing_scoped = existing_order.with_env(scoped.env) if existing_order else existing_order
        return super(PosOrder, scoped)._process_order(order, existing_scoped)

    def _gd_reconcile_offline_discount(self, intent, proof, order_digest):
        """Rebuild at the transaction boundary before native posting/invoicing."""
        self.ensure_one()
        self._gd_lock()
        if (not self.config_id.baseer_global_discount_enabled or self.baseer_global_discount_locked
                or self.account_move or self.session_move_id or self.session_id.state != 'opened'
                or self.state not in ('draft', 'paid') or self.is_refund
                or self.currency_id != self.company_id.currency_id or self.currency_id.rounding != 0.01
                or self.config_id.cash_rounding):
            raise ValidationError(_('The offline discount cannot be synchronized in this order state.'))
        if (getattr(self.config_id, 'baseer_zatca_phase2_enabled', False) and not self.to_invoice):
            raise ValidationError(_('A ZATCA invoice is required before synchronizing this discounted sale.'))
        account_proof = self.config_id._gd_offline_account_proof(self.fiscal_position_id)
        if not account_proof or not hmac.compare_digest(account_proof, intent['account_proof']):
            raise ValidationError(_('The invoice discount account changed while offline. Keep the paid order for manager review.'))
        event = self.env['baseer.pos.global.discount.event'].sudo().search([('action_uuid', '=', intent['action_uuid'])], limit=1)
        if event:
            raise ValidationError(_('This offline discount command was already processed. Refresh the order.'))
        expected_total, expected_tax = _number(intent['expected_total']), _number(intent['expected_tax'])
        self._gd_apply_values(intent['kind'], _number(intent['value']), '')
        local_tax_groups, server_tax_groups = {}, {}
        for row in proof:
            key = tuple(row['tax_ids'])
            previous = local_tax_groups.get(key, (Decimal('0'), Decimal('0')))
            local_tax_groups[key] = (previous[0] + Decimal(row['base']), previous[1] + Decimal(row['gross']))
        for line in self.lines.filtered('baseer_global_discount_line'):
            key = tuple(sorted(line.tax_ids.ids))
            previous = server_tax_groups.get(key, (Decimal('0'), Decimal('0')))
            server_tax_groups[key] = (previous[0] + Decimal(str(line.price_subtotal)),
                                      previous[1] + Decimal(str(line.price_subtotal_incl)))
        if set(local_tax_groups) != set(server_tax_groups) or any(
                any(self.currency_id.compare_amounts(float(actual), float(expected))
                    for actual, expected in zip(local_tax_groups[key], server_tax_groups[key]))
                for key in local_tax_groups):
            raise ValidationError(_('The offline discount tax categories differ from the server calculation. Keep the paid order for manager review.'))
        if (self.currency_id.compare_amounts(self.amount_total, float(expected_total))
                or self.currency_id.compare_amounts(self.amount_tax, float(expected_tax))
                or self.currency_id.compare_amounts(sum(self.payment_ids.mapped('amount')), float(expected_total))):
            raise ValidationError(_('The paid amount or tax differs from the server calculation. Keep the paid order for manager review.'))
        fingerprint = self._gd_offline_fingerprint(intent, proof, order_digest)
        self.env['baseer.pos.global.discount.event'].with_context(_baseer_global_discount_token=_TOKEN).create({
            'order_id': self.id, 'order_uuid': self.uuid, 'company_id': self.company_id.id,
            'action_uuid': intent['action_uuid'], 'fingerprint': fingerprint, 'payload': {'intent': intent, 'proof': proof},
        })

    def _gd_lock(self):
        self.ensure_one()
        origins = self.lines.refunded_orderline_id.order_id
        (self | origins).check_access('write')
        if any(order.company_id not in self.env.companies for order in self | origins):
            raise AccessError(_('This order does not belong to an allowed company.'))
        self.env['baseer.print.preparation.state']._lock_orders_states(self | origins)
        self._baseer_command_access_and_lock()
        if self.config_id.company_id != self.company_id:
            raise AccessError(_('The point of sale company does not match the order.'))
        allowed_users = self.config_id.employee_ids.user_id if 'employee_ids' in self.config_id._fields else self.env['res.users']
        if (allowed_users and self.env.user not in allowed_users
                and not self.env.user.has_group('point_of_sale.group_pos_manager')
                and self.user_id != self.env.user):
            raise AccessError(_('You are not a cashier for this point of sale.'))

    def _gd_unpaid(self, allow_disabled=False):
        if (self.state != 'draft' or self.session_id.state != 'opened' or self.account_move or self.session_move_id
                or self.payment_ids or not self.currency_id.is_zero(self.amount_paid)
                or (not allow_disabled and not self.config_id.baseer_global_discount_enabled)):
            raise AccessError(_('An invoice discount requires an unpaid draft in an open, enabled point of sale.'))
        if self.currency_id.rounding != 0.01 or self.currency_id != self.company_id.currency_id:
            raise ValidationError(_('Invoice discounts currently require the company currency with two decimal places.'))
        if self.config_id.cash_rounding:
            raise ValidationError(_('Invoice discounts do not support cash rounding in this candidate.'))

    def _gd_snapshot(self):
        self.ensure_one()
        return {
            'header': {key: (self[key].id if self._fields[key].type == 'many2one' else self[key]) for key in sorted(_HEADER)},
            'tax_configuration': [{key: (tax[key].ids if tax._fields[key].type in ('many2one', 'one2many', 'many2many') else tax[key])
                                   for key in ('id', 'amount', 'amount_type', 'price_include', 'include_base_amount',
                                               'is_base_affected', 'sequence', 'tax_group_id', 'invoice_repartition_line_ids',
                                               'refund_repartition_line_ids', 'l10n_sa_exemption_reason_code', 'l10n_sa_is_retention')
                                   if key in tax._fields}
                                  for tax in self.lines.tax_ids_after_fiscal_position.sorted('id')],
            'rounding': [self.company_id.tax_calculation_rounding_method, self.currency_id.rounding],
            'lines': [{key: (line[key].ids if line._fields[key].type in ('many2many', 'one2many')
                             else line[key].id if line._fields[key].type == 'many2one' else line[key])
                       for key in sorted(_FINANCIAL | _LINE_METADATA)} for line in self.lines.sorted('id')],
        }

    def _gd_lock_mutations(self):
        """Private lock shared by ordinary CRUD and command finalization."""
        orders = self | self.lines.refunded_orderline_id.order_id
        self.env['baseer.print.preparation.state']._lock_orders_states(orders)
        orders.invalidate_recordset()
        orders.lines.invalidate_recordset()

    def _gd_assert_snapshot(self, ignore_tax=False):
        for order in self.filtered('baseer_global_discount_locked'):
            current, saved = order._gd_snapshot(), dict(order.baseer_global_discount_snapshot or {})
            if ignore_tax:
                for key in ('tax_configuration', 'rounding'):
                    current.pop(key, None)
                    saved.pop(key, None)
            if current != saved:
                raise ValidationError(_('Remove the invoice discount before changing products, quantities, prices, customer or taxes.'))

    def baseer_read_global_discount_state(self):
        self._gd_lock()
        return self._baseer_command_result(accepted=False)

    def _gd_begin(self, action_uuid, expected_revision, payload):
        self._gd_lock()
        try:
            canonical_uuid = str(UUID(action_uuid))
        except (ValueError, TypeError, AttributeError):
            raise ValidationError(_('The discount command identifier is invalid.')) from None
        if canonical_uuid != action_uuid:
            raise ValidationError(_('The discount command identifier is invalid.'))
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        event = self.env['baseer.pos.global.discount.event'].search([('action_uuid', '=', action_uuid)], limit=1)
        if event:
            if event.order_id != self or event.fingerprint != fingerprint:
                raise AccessError(_('This discount command belongs to a different operation.'))
            return True, fingerprint
        self._gd_unpaid(allow_disabled=payload.get('kind') == 'remove')
        if not expected_revision or expected_revision != self._baseer_revision():
            raise ValidationError(_('The order changed on another device. Refresh it before trying again.'))
        return False, fingerprint

    def _gd_finish(self, action_uuid, fingerprint, payload):
        self.env['baseer.pos.global.discount.event'].with_context(_baseer_global_discount_token=_TOKEN).create({
            'order_id': self.id, 'order_uuid': self.uuid, 'company_id': self.company_id.id,
            'action_uuid': action_uuid, 'fingerprint': fingerprint, 'payload': payload,
        })
        return self._baseer_command_result(action_uuid=action_uuid)

    def _gd_source_lines(self):
        lines = self.lines.filtered(lambda line: not line.baseer_global_discount_line)
        if not lines or len(lines) > 200:
            raise ValidationError(_('Add between 1 and 200 products before applying an invoice discount.'))
        headers = self._gd_combo_headers(lines)
        locked = self._baseer_substitution_locked_snapshots(self)
        for line in lines:
            taxes = line.tax_ids_after_fiscal_position._flatten_taxes_and_sort_them()[0]
            if not taxes and line not in headers:
                raise ValidationError(_('Every product needs an explicit tax category, including zero-rated or exempt products, before an invoice discount.'))
            if (line.qty <= 0 or line.refunded_orderline_id or line.price_unit < 0
                    or line.product_id == self.config_id.tip_product_id
                    or line.uuid in locked or line.product_id.baseer_substitution_enabled
                    or any(tax.amount_type != 'percent' for tax in taxes)):
                raise ValidationError(_('This basket contains protected items, tips or unsupported taxes. Invoice discount cannot be applied.'))
            if line.extra_tax_data:
                raise ValidationError(_('This basket already contains special price or tax allocations.'))
        for base_line in self._gd_tax_base_lines(headers):
            details = base_line['tax_details']
            if any(details[key] for key in ('total_excluded_currency', 'total_included_currency',
                                            'delta_total_excluded_currency')):
                raise ValidationError(_('A combo header must have zero price, discount and tax value.'))
        return lines - headers

    def _gd_combo_headers(self, lines):
        """Validate native sale topology; only priced children enter allocation."""
        headers = lines.filtered(lambda line: line.product_id.type == 'combo')
        for parent in headers:
            children = parent.combo_line_ids
            if (not Decimal(str(parent.qty)).is_finite() or parent.qty <= 0
                    or parent.combo_parent_id or parent.combo_item_id or not children
                    or parent.price_unit != 0 or parent.discount != 0
                    or parent.price_subtotal != 0 or parent.price_subtotal_incl != 0
                    or any(child.order_id != self or child not in lines for child in children)):
                raise ValidationError(_('A combo header must be zero-valued and contain its own order components.'))
        for line in lines - headers:
            if line.combo_parent_id:
                parent, item = line.combo_parent_id, line.combo_item_id
                if (parent not in headers or parent.order_id != self or line.combo_line_ids
                        or not item or item.product_id != line.product_id
                        or item.combo_id not in parent.product_id.combo_ids
                        or (item.company_id and item.company_id != self.company_id)):
                    raise ValidationError(_('The combo components do not match their parent and original product choices.'))
            elif line.combo_item_id or line.combo_line_ids:
                raise ValidationError(_('A combo component must belong to one valid header in this order.'))
        for parent in headers:
            for choice in parent.product_id.combo_ids:
                quantities = [Decimal(str(child.qty)) for child in parent.combo_line_ids
                              if child.combo_item_id.combo_id == choice]
                if any(not quantity.is_finite() for quantity in quantities):
                    raise ValidationError(_('Combo quantities must be finite and respect the original choice limits.'))
                selected = sum(quantities, Decimal('0')) / Decimal(str(parent.qty))
                tolerance = Decimal('0.000000001')
                if selected < Decimal(choice.qty_free) - tolerance or selected > Decimal(choice.qty_max) + tolerance:
                    raise ValidationError(_('The combo must include every required choice within its minimum and maximum quantities.'))
        return headers

    def _gd_combo_refund_headers(self, originals):
        """Refund a recorded group, never reinterpret today's combo definition."""
        by_source = {line.refunded_orderline_id.id: line for line in self.lines}
        headers = self.env['pos.order.line']
        for refund_line in self.lines:
            source = refund_line.refunded_orderline_id
            if source.combo_line_ids or source.product_id.type == 'combo':
                original_children = source.combo_line_ids
                children = self.env['pos.order.line'].browse([
                    by_source[child.id].id for child in original_children if child.id in by_source
                ])
                if (source.combo_parent_id or not original_children or refund_line.combo_parent_id
                        or refund_line.combo_item_id or refund_line.price_unit != 0 or refund_line.discount != 0
                        or len(children) != len(original_children)
                        or set(refund_line.combo_line_ids.ids) != set(children.ids)
                        or any(child.order_id != originals for child in original_children)):
                    raise ValidationError(_('Refund the combo header and all of its original components together.'))
                headers |= refund_line
            elif source.combo_parent_id:
                parent = by_source.get(source.combo_parent_id.id)
                if (not parent or parent.order_id != self or refund_line.combo_parent_id != parent
                        or refund_line.combo_line_ids or not source.combo_item_id
                        or (refund_line.combo_item_id and refund_line.combo_item_id != source.combo_item_id)):
                    raise ValidationError(_('Refund the combo header and all of its original components together.'))
                expected = Decimal(str(parent.qty)) * Decimal(str(source.qty))
                actual = Decimal(str(refund_line.qty)) * Decimal(str(source.combo_parent_id.qty))
                if abs(expected - actual) > Decimal('0.000000001'):
                    raise ValidationError(_('Combo refund quantities must preserve the original component ratios.'))
                # Native TicketScreen omits combo_item_id on refunds. Its
                # immutable sale source, not the current product choices, owns it.
                if not refund_line.combo_item_id:
                    refund_line.with_context(_baseer_global_discount_token=_TOKEN).write({
                        'combo_item_id': source.combo_item_id.id,
                    })
            elif refund_line.combo_parent_id or refund_line.combo_line_ids or refund_line.combo_item_id:
                raise ValidationError(_('The refund combo structure does not match the original sale.'))
        return headers

    def _gd_tax_base_lines(self, lines):
        values = lines._prepare_tax_base_line_values()
        self.env['account.tax']._add_tax_details_in_base_lines(values, self.company_id)
        self.env['account.tax']._round_base_lines_tax_details(values, self.company_id)
        return values

    def _gd_recompute(self):
        order = self._gd_internal()
        base_lines = order._gd_tax_base_lines(order.lines)
        for base_line in base_lines:
            details = base_line['tax_details']
            # Native base-line preparation already normalizes refund quantity.
            # Store that native orientation; order/ledger consumers restore its
            # sign themselves. A second reversal breaks margins and proofs.
            base_line['record'].with_context(_baseer_global_discount_token=_TOKEN).write({
                'price_subtotal': details['total_excluded_currency'] + details['delta_total_excluded_currency'],
                'price_subtotal_incl': (details['total_excluded_currency'] + details['delta_total_excluded_currency']
                                              + sum(tax['tax_amount_currency'] for tax in details['taxes_data'])),
            })
        order._compute_prices()

    def _gd_add_allowance(self, base_line, source, product, refunded=False):
        AccountTax = self.env['account.tax']
        extra = AccountTax._export_base_line_extra_tax_data(base_line)
        details = base_line['tax_details']
        return self.env['pos.order.line'].with_context(_baseer_global_discount_token=_TOKEN).create({
            'order_id': self.id, 'product_id': product.id, 'full_product_name': _('Invoice discount'),
            'qty': -base_line['quantity'] if refunded else base_line['quantity'], 'price_unit': base_line['price_unit'], 'discount': 0,
            'tax_ids': [(6, 0, base_line['tax_ids'].ids)], 'price_type': 'manual',
            'extra_tax_data': extra, 'price_subtotal': details['total_excluded_currency'],
            'price_subtotal_incl': details['total_included_currency'],
            'baseer_global_discount_line': True, 'baseer_global_discount_source_id': source.id,
            'refunded_orderline_id': refunded.id if refunded else False,
        })

    def baseer_apply_global_discount(self, kind, value, reason, action_uuid, expected_revision):
        self.ensure_one()
        if kind not in ('percent', 'fixed', 'remove') or not isinstance(reason, str) or len(reason.strip()) > 250:
            raise ValidationError(_('Choose a discount type and enter a short reason.'))
        parsed = _number(value)
        if kind != 'remove' and parsed <= 0:
            raise ValidationError(_('Enter a positive discount.'))
        payload = {'kind': kind, 'value': str(parsed), 'reason': reason.strip()}
        retry, fingerprint = self._gd_begin(action_uuid, expected_revision, payload)
        if retry:
            return self._baseer_command_result(action_uuid=action_uuid)
        self._gd_apply_values(kind, parsed, reason)
        return self._gd_finish(action_uuid, fingerprint, payload)

    def _gd_apply_values(self, kind, parsed, reason):
        """Apply validated values; caller owns authorization, locks and transaction."""
        self.ensure_one()
        if self.is_refund or self.lines.refunded_orderline_id:
            raise ValidationError(_('A new discount cannot be applied to a refund.'))
        if (kind != 'remove' and 'baseer_zatca_phase2_enabled' in self.config_id._fields
                and self.config_id.baseer_zatca_phase2_enabled and not self.partner_id):
            raise ValidationError(_('Choose the customer before applying an invoice discount for ZATCA invoicing.'))
        self._gd_assert_snapshot(ignore_tax=kind == 'remove')
        internal = self._gd_internal()
        internal.lines.filtered('baseer_global_discount_line').unlink()
        internal.write({'baseer_global_discount_locked': False, 'baseer_global_discount_snapshot': False})
        if kind == 'remove':
            internal.write({'baseer_global_discount_kind': False, 'baseer_global_discount_value': False,
                            'baseer_global_discount_gross': 0, 'baseer_global_discount_reason': False})
            internal._gd_recompute()
            return
        sources = internal._gd_source_lines()
        product = self.config_id.baseer_global_discount_product_id
        if (not product or product.company_id != self.company_id or product.type != 'service'
                or not product.available_in_pos or not product.sale_ok):
            raise ValidationError(_('Ask a POS manager to set up the invoice discount product.'))
        base_lines = internal._gd_tax_base_lines(sources)
        for base_line in base_lines:
            base_line['_gd_source'] = base_line['record']
        gross = sum(Decimal(str(line['tax_details']['total_included_currency'])) for line in base_lines)
        if gross <= 0:
            raise ValidationError(_('The eligible total must be positive.'))
        amount = gross * parsed / 100 if kind == 'percent' else parsed
        cap_percent = Decimal(str(self.config_id.baseer_global_discount_max_percent))
        cap_amount = Decimal(str(self.config_id.baseer_global_discount_max_amount))
        if amount > gross or (kind == 'percent' and parsed > 100) or amount * 100 > gross * cap_percent:
            raise ValidationError(_('The discount exceeds the permitted percentage or invoice total.'))
        if cap_amount > 0 and amount > cap_amount:
            raise ValidationError(_('The discount exceeds the permitted amount.'))
        discounts = self.env['account.tax']._prepare_global_discount_lines(
            base_lines, self.company_id, 'percent' if kind == 'percent' else 'fixed', float(parsed),
            computation_key='baseer_global_discount', grouping_function=lambda line: {'_gd_source': line['_gd_source']},
        )
        for base_line in discounts:
            internal._gd_add_allowance(base_line, base_line['_gd_source'], product)
        expected = self.currency_id.round(float(amount))
        internal.write({'baseer_global_discount_kind': kind, 'baseer_global_discount_value': str(parsed),
                        'baseer_global_discount_reason': reason.strip(), 'baseer_global_discount_gross': expected})
        internal._gd_recompute()
        actual = -sum(line.price_subtotal_incl for line in self.lines.filtered('baseer_global_discount_line'))
        if self.currency_id.compare_amounts(actual, expected):
            raise ValidationError(_('The tax engine could not preserve the requested discount amount.'))
        internal.write({'baseer_global_discount_locked': True, 'baseer_global_discount_snapshot': internal._gd_snapshot()})

    def _gd_allocate_history(self, original, quantity, source_quantity, previous, order_base_cache):
        """Allocate already rounded historical base/tax cents; never calculate a tax rate."""
        tax = self.env['account.tax']
        def full_order_base(line):
            if line.order_id.id not in order_base_cache:
                order_base_cache[line.order_id.id] = {
                    item['record'].id: item for item in line.order_id._gd_tax_base_lines(line.order_id.lines)
                }
            return order_base_cache[line.order_id.id][line.id]
        original_base = full_order_base(original)
        previous_bases = [full_order_base(line) for line in previous]
        completed_qty = sum(-Decimal(str(line.qty)) for line in previous if not line.baseer_global_discount_line)
        # Allowance quantities are always one, so its sale-source quantity drives allocation.
        if original.baseer_global_discount_line:
            completed_qty = sum(-Decimal(str(line.baseer_global_discount_source_id.qty)) for line in previous)
        cumulative = completed_qty + quantity
        if cumulative > source_quantity:
            raise ValidationError(_('The refund exceeds the remaining sold quantity.'))
        currency_quantum = Decimal(str(self.currency_id.rounding))
        company_quantum = Decimal(str(self.company_id.currency_id.rounding))
        def allocate(field, previous_details, quantum):
            delta_field = field.replace('total_', 'delta_total_')
            total = Decimal(str(original_base['tax_details'][field])) + Decimal(str(original_base['tax_details'].get(delta_field, 0)))
            target = total if cumulative == source_quantity else (total * cumulative / source_quantity).quantize(quantum, rounding=ROUND_HALF_UP)
            return float(target - sum(Decimal(str(item[field])) + Decimal(str(item.get(delta_field, 0))) for item in previous_details))
        previous_details = [line['tax_details'] for line in previous_bases]
        base = original_base.copy()
        base.update({'quantity': float(quantity / source_quantity) if original.baseer_global_discount_line else float(quantity),
                     'computation_key': 'baseer_global_discount_refund',
                     'manual_total_excluded_currency': allocate('total_excluded_currency', previous_details, currency_quantum),
                     'manual_total_excluded': allocate('total_excluded', previous_details, company_quantum)})
        manual = {}
        for original_tax in original_base['tax_details']['taxes_data']:
            previous_tax_details = []
            for previous_base in previous_bases:
                match = next(item for item in previous_base['tax_details']['taxes_data'] if item['tax'] == original_tax['tax'])
                previous_tax_details.append(match)
            values = {}
            for name, quantum in (('tax_amount_currency', currency_quantum), ('base_amount_currency', currency_quantum),
                                  ('tax_amount', company_quantum), ('base_amount', company_quantum)):
                total = Decimal(str(original_tax[name]))
                target = total if cumulative == source_quantity else (total * cumulative / source_quantity).quantize(quantum, rounding=ROUND_HALF_UP)
                values[name] = float(target - sum(Decimal(str(item[name])) for item in previous_tax_details))
            manual[str(original_tax['tax'].id)] = values
        base['manual_tax_amounts'] = manual
        # Preserve original prices; quantity and historical manual amounts reverse
        # only this source slice, including the last base/tax cent.
        base.pop('tax_details', None)
        tax._add_tax_details_in_base_lines([base], self.company_id)
        tax._round_base_lines_tax_details([base], self.company_id)
        return base

    def baseer_prepare_global_discount_refund(self, action_uuid, expected_revision):
        self.ensure_one()
        payload = {'kind': 'refund'}
        retry, fingerprint = self._gd_begin(action_uuid, expected_revision, payload)
        if retry:
            return self._baseer_command_result(action_uuid=action_uuid)
        if self.baseer_global_discount_locked:
            self._gd_assert_snapshot()
            return self._gd_finish(action_uuid, fingerprint, payload)
        originals = self.lines.refunded_orderline_id.order_id
        if (len(originals) != 1 or originals.company_id != self.company_id
                or not originals.baseer_global_discount_locked or self.partner_id != originals.partner_id):
            raise ValidationError(_('Select products from one discounted sale in this company.'))
        if originals.state not in ('paid', 'done', 'invoiced'):
            raise ValidationError(_('The original sale has not been paid.'))
        originals._gd_assert_snapshot()
        if not self.lines or any(line.qty >= 0 or not line.refunded_orderline_id or line.refunded_orderline_id.baseer_global_discount_line for line in self.lines):
            raise ValidationError(_('Refund products only; discount lines cannot be refunded separately.'))
        if len(self.lines.refunded_orderline_id) != len(self.lines):
            raise ValidationError(_('Refund each original product on one line only.'))
        headers = self._gd_combo_refund_headers(originals)
        internal = self._gd_internal()
        internal.write({'is_refund': True})
        allocation_gross = Decimal('0')
        order_base_cache = {}
        for refund_line in internal.lines:
            source = refund_line.refunded_orderline_id
            if (refund_line.product_id != source.product_id or refund_line.price_unit != source.price_unit
                    or refund_line.discount != source.discount or refund_line.tax_ids != source.tax_ids
                    or self.fiscal_position_id != originals.fiscal_position_id):
                raise ValidationError(_('The refund must preserve the original product, price and tax identity.'))
            others = source.refund_orderline_ids.filtered(lambda line: line.order_id != self and line.order_id.state != 'cancel')
            if any(line.order_id.state == 'draft' for line in others):
                raise ValidationError(_('Finish or cancel the other draft refund of this product first.'))
            quantity, source_quantity = -Decimal(str(refund_line.qty)), Decimal(str(source.qty))
            if refund_line in headers:
                if quantity + sum(-Decimal(str(line.qty)) for line in others) > source_quantity:
                    raise ValidationError(_('The refund exceeds the remaining sold quantity.'))
                continue
            sale_allocation = internal._gd_allocate_history(source, quantity, source_quantity, others, order_base_cache)
            refund_line.with_context(_baseer_global_discount_token=_TOKEN).write({
                'extra_tax_data': self.env['account.tax']._export_base_line_extra_tax_data(sale_allocation),
            })
            for allowance in originals.lines.filtered(lambda line: line.baseer_global_discount_source_id == source):
                previous = allowance.refund_orderline_ids.filtered(lambda line: line.order_id.state not in ('cancel', 'draft'))
                portion = internal._gd_allocate_history(allowance, quantity, source_quantity, previous, order_base_cache)
                internal._gd_add_allowance(portion, refund_line, allowance.product_id, refunded=allowance)
                allocation_gross -= Decimal(str(portion['tax_details']['total_included_currency']))
        internal.write({'baseer_global_discount_kind': 'refund', 'baseer_global_discount_value': str(allocation_gross),
                        'baseer_global_discount_gross': float(allocation_gross), 'baseer_global_discount_reason': _('Original sale discount allocation')})
        internal._gd_recompute()
        internal.write({'baseer_global_discount_locked': True, 'baseer_global_discount_snapshot': internal._gd_snapshot()})
        return self._gd_finish(action_uuid, fingerprint, payload)

    def _gd_refund_ready(self):
        for order in self:
            origins = order.lines.refunded_orderline_id.order_id.filtered('baseer_global_discount_locked')
            if origins:
                if not order.baseer_global_discount_locked or order.baseer_global_discount_kind != 'refund':
                    raise ValidationError(_('Prepare the original invoice discount allocation before paying this refund.'))
                order._gd_assert_snapshot()

    def _prepare_invoice_vals(self):
        values = super()._prepare_invoice_vals()
        # A managed POS return is a return of goods/services. Preserve any
        # explicit native reason and all native original-invoice references.
        if (values.get('move_type') == 'out_refund'
                and 'l10n_sa_reason' in self.env['account.move']._fields
                and not values.get('l10n_sa_reason')
                and self.company_id.country_id.code == 'SA'
                and all(order.baseer_global_discount_locked
                        and order.baseer_global_discount_kind == 'refund' for order in self)):
            values['l10n_sa_reason'] = 'BR-KSA-17-reason-4'
        return values

    def _process_saved_order(self, draft):
        offline = self.env.context.get('_baseer_offline_discount')
        draft_scope = self.env.context.get('_baseer_draft_apply')
        command_data = draft_scope[1] if isinstance(draft_scope, tuple) and len(draft_scope) == 2 and draft_scope[0] is _DRAFT_TOKEN else None
        if isinstance(offline, tuple) and len(offline) == 4 and offline[0] is _OFFLINE_TOKEN:
            if draft:
                if command_data:
                    intent = offline[1]
                    account_proof = self.config_id._gd_offline_account_proof(self.fiscal_position_id)
                    if not account_proof or not hmac.compare_digest(account_proof, intent['account_proof']):
                        raise ValidationError(_('The invoice discount account changed. Refresh the order before applying the discount.'))
                    self._gd_apply_values(intent['kind'], _number(intent['value']), '')
                    if (self.currency_id.compare_amounts(self.amount_total, float(_number(intent['expected_total']))) or
                            self.currency_id.compare_amounts(self.amount_tax, float(_number(intent['expected_tax'])))):
                        raise ValidationError(_('The discount total differs from the server calculation. Keep the local order for review.'))
                    self._gd_internal().write({'baseer_global_discount_locked': False,
                                               'baseer_global_discount_snapshot': False})
                else:
                    # Legacy draft path must never retain client preview totals.
                    self._gd_recompute()
            else:
                self._gd_reconcile_offline_discount(offline[1], offline[2], offline[3])
        elif draft and command_data:
            self._gd_recompute()
        if command_data:
            command, digest, _retry = command_data
            raw_intent = offline[1] if isinstance(offline, tuple) and len(offline) == 4 and offline[0] is _OFFLINE_TOKEN else False
            self._gd_internal().write({
                'baseer_offline_draft_kind': raw_intent['kind'] if raw_intent else False,
                'baseer_offline_draft_value': raw_intent['value'] if raw_intent else False,
                'baseer_offline_draft_revision': command['revision'] + 1,
                'baseer_offline_draft_command_uuid': command['command_uuid'],
                'baseer_offline_draft_digest': digest,
            })
        if not draft and (self.baseer_global_discount_locked or self.lines.refunded_orderline_id.order_id.filtered('baseer_global_discount_locked')):
            self._gd_lock()
            self._gd_refund_ready()
            self._gd_assert_snapshot()
            if self.baseer_global_discount_locked:
                proposed = self.amount_total
                self._gd_recompute()
                if self.currency_id.compare_amounts(proposed, self.amount_total):
                    raise ValidationError(_('The payment total does not match the server tax calculation. Refresh the order.'))
        return super()._process_saved_order(draft)

    @api.model_create_multi
    def create(self, values_list):
        if not _internal(self.env):
            for values in values_list:
                if any(values.get(key) for key in _ORDER_METADATA):
                    raise AccessError(_('Invoice discount data is created by the discount command only.'))
        result = super().create(values_list)
        if not _internal(self.env):
            result.filtered(lambda order: order.state in ('paid', 'done', 'invoiced'))._gd_refund_ready()
        return result

    def write(self, values):
        if not _internal(self.env):
            if _HEADER.intersection(values) or values.get('lines') or values.get('state'):
                self._gd_lock_mutations()
            for order in self:
                if (order.state == 'draft' and order.baseer_offline_draft_revision and not _draft_sync(self.env)
                        and (_HEADER | {'lines', 'payment_ids', 'state', 'amount_total', 'amount_tax', 'amount_paid'}).intersection(values)):
                    raise ValidationError(_('Change this shared discount order through the point of sale revision command.'))
                for key in _ORDER_METADATA & values.keys():
                    if not _same(order, key, values[key]):
                        raise AccessError(_('Invoice discount data is managed by the discount command only.'))
                if order.baseer_global_discount_locked:
                    for key in (_HEADER | {'amount_total', 'amount_tax'}) & values.keys():
                        unchanged = (not order.currency_id.compare_amounts(order[key], values[key])
                                     if key in ('amount_total', 'amount_tax') else _same(order, key, values[key]))
                        if not unchanged:
                            raise ValidationError(_('Remove the invoice discount before changing this order.'))
                if values.get('state') in ('paid', 'done', 'invoiced'):
                    order._gd_refund_ready()
                    order._gd_assert_snapshot()
                if (order.baseer_global_discount_kind == 'refund' and order.baseer_global_discount_locked
                        and order.state == 'cancel' and values.get('state') not in (None, 'cancel')):
                    raise ValidationError(_('A cancelled prepared refund cannot be reopened. Create a new refund from the original sale.'))
        result = super().write(values)
        if not _internal(self.env):
            self._gd_assert_snapshot()
        return result

    def unlink(self):
        self._gd_lock_mutations()
        if self.filtered(lambda order: order.state == 'draft' and order.baseer_offline_draft_revision):
            raise AccessError(_('A shared discount order cannot be deleted without resolving its revision.'))
        if any(order.baseer_global_discount_locked for order in self):
            raise AccessError(_('Cancel the discounted order instead of deleting its audit history.'))
        return super().unlink()


class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    baseer_global_discount_line = fields.Boolean(readonly=True, copy=False)
    baseer_global_discount_source_id = fields.Many2one('pos.order.line', readonly=True, copy=False, ondelete='restrict', index=True)

    @api.model
    def _load_pos_data_fields(self, config):
        inherited = super()._load_pos_data_fields(config)
        return list(dict.fromkeys(inherited + sorted(_LINE_METADATA))) if inherited else inherited

    @api.model_create_multi
    def create(self, values_list):
        if not _internal(self.env):
            orders = self.env['pos.order'].browse([values['order_id'] for values in values_list if values.get('order_id')]).exists()
            orders._gd_lock_mutations()
            if not _draft_sync(self.env) and orders.filtered(lambda order: order.state == 'draft' and order.baseer_offline_draft_revision):
                raise ValidationError(_('Change this shared discount order through the point of sale revision command.'))
            for values in values_list:
                if any(values.get(key) for key in _LINE_METADATA):
                    raise AccessError(_('Invoice discount lines are created by the discount command only.'))
                order = self.env['pos.order'].browse(values.get('order_id')).exists()
                if order.baseer_global_discount_locked:
                    raise ValidationError(_('Remove the invoice discount before adding products.'))
                if (order.config_id.baseer_global_discount_product_id
                        and values.get('product_id') == order.config_id.baseer_global_discount_product_id.id):
                    raise AccessError(_('Use the invoice discount command instead of adding its product manually.'))
        return super().create(values_list)

    def write(self, values):
        affected_orders = self.order_id | self.env['pos.order'].browse(values.get('order_id')).exists()
        if not _internal(self.env):
            affected_orders._gd_lock_mutations()
            if not _draft_sync(self.env) and affected_orders.filtered(lambda order: order.state == 'draft' and order.baseer_offline_draft_revision) and (_FINANCIAL | {'price_subtotal', 'price_subtotal_incl'}).intersection(values):
                raise ValidationError(_('Change this shared discount order through the point of sale revision command.'))
            target_order = self.env['pos.order'].browse(values.get('order_id')).exists()
            if target_order.baseer_global_discount_locked and any(line.order_id != target_order for line in self):
                raise ValidationError(_('Remove the invoice discount before adding products.'))
            for line in self:
                if ('product_id' in values and values['product_id'] != line.product_id.id
                        and values['product_id'] == line.order_id.config_id.baseer_global_discount_product_id.id):
                    raise AccessError(_('Use the invoice discount command instead of adding its product manually.'))
                keys = _LINE_METADATA & values.keys()
                if line.order_id.baseer_global_discount_locked:
                    keys |= (_FINANCIAL | {'price_subtotal', 'price_subtotal_incl'}) & values.keys()
                if any(not _same(line, key, values[key]) for key in keys):
                    raise ValidationError(_('Remove the invoice discount before changing products, prices or taxes.'))
        result = super().write(values)
        if not _internal(self.env):
            affected_orders._gd_assert_snapshot()
        return result

    def unlink(self):
        self.order_id._gd_lock_mutations()
        if not _internal(self.env) and (self.filtered('baseer_global_discount_line') or
                (not _draft_sync(self.env) and self.order_id.filtered(lambda order: order.state == 'draft' and order.baseer_offline_draft_revision))):
            raise ValidationError(_('Change this shared discount order through the point of sale revision command.'))
        if not _internal(self.env) and self.order_id.filtered('baseer_global_discount_locked'):
            raise ValidationError(_('Remove the invoice discount before deleting products.'))
        return super().unlink()


class PosPayment(models.Model):
    _inherit = 'pos.payment'

    def _gd_check_shared_draft_payment(self, orders):
        if not _internal(self.env) and not _draft_sync(self.env):
            if orders.filtered(lambda order: order.state == 'draft' and order.baseer_offline_draft_revision):
                raise ValidationError(_('Change this shared discount order through the point of sale revision command.'))

    @api.model_create_multi
    def create(self, values_list):
        self._gd_check_shared_draft_payment(self.env['pos.order'].browse([
            values['pos_order_id'] for values in values_list if values.get('pos_order_id')
        ]).exists())
        return super().create(values_list)

    def write(self, values):
        if {'amount', 'payment_method_id', 'pos_order_id', 'is_change', 'payment_date', 'uuid'}.intersection(values):
            orders = self.pos_order_id | self.env['pos.order'].browse(values.get('pos_order_id')).exists()
            self._gd_check_shared_draft_payment(orders)
        return super().write(values)

    def unlink(self):
        self._gd_check_shared_draft_payment(self.pos_order_id)
        return super().unlink()
