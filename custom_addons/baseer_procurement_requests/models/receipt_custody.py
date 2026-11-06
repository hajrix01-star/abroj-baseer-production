"""Atomic native receipt / Representative Petty Cash boundary."""
import hashlib
import json
from decimal import Decimal, DecimalException

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .procurement import _catalog_identifier, _decimal_input, _decimal_text, _is_bwork_receipt_internal

_MARKER_CONTEXT = '_baseer_receipt_custody_proof'
_MARKER_PROOF = object()


class ProcurementReceiptCustody(models.Model):
    _inherit = 'baseer.procurement.request'

    receipt_custody_confirmed = fields.Boolean(readonly=True, copy=False, default=False)

    @api.model_create_multi
    def create(self, vals_list):
        if any('receipt_custody_confirmed' in vals for vals in vals_list):
            raise AccessError(_('Receipt funding confirmation is managed by the receipt workflow.'))
        if self.env.context.get('default_receipt_custody_confirmed'):
            raise AccessError(_('Receipt funding confirmation is managed by the receipt workflow.'))
        return super().create([{**vals, 'receipt_custody_confirmed': False} for vals in vals_list])

    def write(self, vals):
        if 'receipt_custody_confirmed' in vals and not (
                self.env.su and self.env.context.get(_MARKER_CONTEXT) is _MARKER_PROOF
                and set(vals) == {'receipt_custody_confirmed'} and vals['receipt_custody_confirmed'] is True):
            raise AccessError(_('Receipt funding confirmation is managed by the receipt workflow.'))
        return super().write(vals)

    def _receipt_custody_required(self):
        self.ensure_one()
        bwork = ('source_channel' in self._fields
                 and getattr(self, '_bwork_source_channel', None) is not None
                 and self.source_channel == self._bwork_source_channel)
        return self.purchase_route == 'representative' and not bwork and not _is_bwork_receipt_internal(self.env)

    @api.model
    def _receipt_custody_request(self, request_id):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            raise AccessError(_('Only a procurement cashier can confirm the quantity receipt.'))
        request = self.browse(_catalog_identifier(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        request.check_access('read')
        return request

    def _receipt_custody_fundings(self):
        self.ensure_one()
        records = self.env['baseer.procurement.representative.advance'].sudo().search([
            ('company_id', '=', self.company_id.id), ('procurement_request_id', '=', self.id),
            ('movement_type', '=', 'funding'),
        ], order='id')
        for record in records:
            if (record.state != 'posted' or not record.move_id or record.move_id.state != 'posted'
                    or record.move_id.company_id != self.company_id
                    or record.representative_partner_id != self.representative_partner_id):
                raise UserError(_('The existing request funding has an inconsistent accounting link. Contact an accountant.'))
        return records

    def _receipt_custody_context(self):
        self.ensure_one()
        if not self._receipt_custody_required():
            return {'required': False}
        if self.state not in ('sent', 'received', 'purchased'):
            raise UserError(_('Representative funding is entered only at final receipt confirmation.'))
        representative = self.representative_partner_id.with_company(self.company_id)
        if (not representative or not representative.active or representative.is_company
                or representative.parent_id or not representative.is_purchase_representative
                or (representative.company_id and representative.company_id != self.company_id)):
            raise UserError(_('Select an active purchase representative contact on the request before confirming receipt.'))
        company = self.company_id.sudo()
        funding = self._receipt_custody_fundings()
        points = company._baseer_representative_petty_cash_payment_points().filtered(
            lambda point: (not point.currency_id or point.currency_id == company.currency_id)
            and (not point.default_account_id.currency_id
                 or point.default_account_id.currency_id == company.currency_id))
        if not funding:
            account, journal = company._baseer_representative_petty_cash_ready()
            if ((account.currency_id and account.currency_id != company.currency_id)
                    or (journal.currency_id and journal.currency_id != company.currency_id)):
                raise UserError(_('Representative receipt funding requires company-currency accounts and journals.'))
            if not points:
                raise UserError(_('Configure an approved company-currency bank or cash payment point before confirming receipt.'))
        fingerprint = {
            'request': [self.id, company.id, self.state, self.purchase_route, representative.id,
                        str(self.write_date), self.receipt_custody_confirmed],
            'setup': [company.baseer_procurement_representative_petty_cash_account_id.id,
                      company.baseer_procurement_representative_petty_cash_journal_id.id],
            'points': [(p.id, str(p.write_date), p.default_account_id.id,
                        p.currency_id.id, p.default_account_id.currency_id.id) for p in points.sorted('id')],
            'funding': [(f.id, str(f.amount), f.payment_journal_id.id, str(f.movement_date),
                         f.move_id.id, f.move_id.state) for f in funding],
        }
        amount = sum((Decimal(str(f.amount)) for f in funding), Decimal('0.00'))
        return {
            'required': True, 'request_id': self.id, 'request_name': self.name,
            'representative_id': representative.id, 'representative_name': representative.display_name,
            'existing_funded': bool(funding), 'funded_amount': format(amount, '.2f'),
            'funded_amount_text': _decimal_text(amount), 'currency_symbol': company.currency_id.symbol,
            'currency_position': company.currency_id.position,
            'payment_points': [{'id': p.id, 'name': p.display_name, 'type': p.type} for p in points],
            'default_payment_journal_id': points.id if len(points) == 1 else False,
            'movement_date': fields.Date.to_string(fields.Date.context_today(self)),
            'snapshot': hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest(),
            'funding_records': [{'id': f.id, 'name': f.name, 'amount_text': _decimal_text(Decimal(str(f.amount))),
                                 'payment_point_name': f.payment_journal_id.display_name,
                                 'move_name': f.move_id.name, 'movement_date': fields.Date.to_string(f.movement_date)}
                                for f in funding],
        }

    @api.model
    def prepare_receipt_custody(self, request_id):
        return self._receipt_custody_request(request_id)._receipt_custody_context()

    def _lock_receipt_custody(self):
        self.ensure_one()
        representative = self.representative_partner_id
        if not representative:
            self._receipt_custody_context()  # actionable legacy-contact error, no fallback partner
        advances = self.env['baseer.procurement.representative.advance']
        advances._baseer_lock_representative_balance(self.company_id, representative)
        advances._lock_request(self.id)
        self.invalidate_recordset()
        if representative != self.representative_partner_id:
            raise UserError(_('The request changed. Reload the receipt before confirming.'))

    @api.model
    def confirm_actual_from_catalog(self, request_id, lines, receipt_custody=False):
        request = self._receipt_custody_request(request_id) if not _is_bwork_receipt_internal(self.env) else self.browse(request_id)
        if not request._receipt_custody_required():
            return super().confirm_actual_from_catalog(request_id, lines)
        with self.env.cr.savepoint():
            request._lock_receipt_custody()
            context = request._receipt_custody_context()
            if request.state not in ('sent', 'received'):
                raise UserError(_('Only an unconfirmed receipt can record representative funding.'))
            payload = receipt_custody or {}
            if not isinstance(payload, dict) or set(payload) - {'snapshot', 'amount', 'payment_journal_id', 'movement_date'}:
                raise ValidationError(_('Invalid representative funding details.'))
            if payload and payload.get('snapshot') != context['snapshot']:
                raise UserError(_('The request funding changed. Reload the receipt before confirming.'))
            if context['existing_funded']:
                if set(payload) - {'snapshot'}:
                    raise ValidationError(_('Existing request funding is read-only. Reload the receipt.'))
            else:
                if not payload or payload.get('snapshot') != context['snapshot']:
                    raise ValidationError(_('Enter the actual representative advance and payment point before confirming receipt.'))
                try:
                    amount = _decimal_input(payload.get('amount'), _('Actual representative advance'), positive=True)
                except DecimalException as error:
                    raise ValidationError(_('Enter a valid actual representative advance.')) from error
                point_id = payload.get('payment_journal_id') or context['default_payment_journal_id']
                point_id = _catalog_identifier(point_id)
                if point_id not in [p['id'] for p in context['payment_points']]:
                    raise ValidationError(_('Choose an approved company-currency payment point.'))
                try:
                    movement_date = fields.Date.to_date(payload.get('movement_date'))
                except (TypeError, ValueError):
                    movement_date = False
                if not movement_date:
                    raise ValidationError(_('Enter the transfer date before saving.'))
                self.env['baseer.procurement.representative.advance']._create_and_post({
                    'company_id': request.company_id.id, 'movement_type': 'funding',
                    'representative_partner_id': request.representative_partner_id.id,
                    'procurement_request_id': request.id, 'payment_journal_id': point_id,
                    'movement_date': movement_date, 'amount': float(amount),
                    'client_token': 'receipt-custody:%s' % request.id, 'created_by_id': self.env.uid,
                })
            result = super().confirm_actual_from_catalog(request_id, lines)
            request.sudo().with_context(**{_MARKER_CONTEXT: _MARKER_PROOF}).write({'receipt_custody_confirmed': True})
            request.message_post(body=_('Representative advance reused or recorded with final receipt by %s.') % self.env.user.display_name)
            return result

    def action_confirm_actual_purchase(self):
        self.ensure_one()
        if self._receipt_custody_required() and self.state != 'purchased':
            self._receipt_custody_request(self.id)
            self._lock_receipt_custody()
            self._receipt_custody_context()
            if not self._receipt_custody_fundings():
                raise UserError(_('Enter the actual representative advance and payment point in the receipt screen before confirming.'))
        eligible_transition = self.state in ('sent', 'received')
        result = super().action_confirm_actual_purchase()
        if eligible_transition and self.state == 'purchased' and self._receipt_custody_required() and not self.receipt_custody_confirmed:
            self.sudo().with_context(**{_MARKER_CONTEXT: _MARKER_PROOF}).write({'receipt_custody_confirmed': True})
        return result

    def action_open_receipt_custody(self):
        self.ensure_one()
        self.env['baseer.procurement.representative.advance']._require_reader()
        if self.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        self.check_access('read')
        funding = self._receipt_custody_fundings()
        return {'type': 'ir.actions.client', 'tag': 'baseer_procurement_requests.representative_petty_cash',
                'params': {'representative_id': self.representative_partner_id.id,
                           'month_start': fields.Date.to_string(funding[-1].movement_date.replace(day=1)) if funding else False}}


class RepresentativeAdvanceReceiptCustody(models.Model):
    _inherit = 'baseer.procurement.representative.advance'

    def _require_reader(self):
        if self.env.user.has_group('baseer_procurement_requests.group_procurement_cashier'):
            return
        return super()._require_reader()

    def _dashboard_data(self, representative_id=False, month_start=False):
        result = super()._dashboard_data(representative_id, month_start)
        movements = self.sudo().search([('id', 'in', [m['id'] for m in result.get('movements', [])]),
                                        ('company_id', '=', self.env.company.id)])
        requests = {m.id: m.procurement_request_id.id for m in movements}
        for movement in result.get('movements', []):
            movement['request_id'] = requests.get(movement['id'], False)
        return result

    @api.model
    def submit_funding(self, request_id, payment_journal_id, representative_partner_id, amount, client_token,
                       movement_date=False, external_reference=False, transfer_proof=False, transfer_proof_filename=False):
        self._require_accountant()
        request = self.env['baseer.procurement.request'].browse(_catalog_identifier(request_id)).exists()
        if not request or request.company_id != self.env.company:
            raise AccessError(_('The procurement request is unavailable in the active company.'))
        token = (client_token or '').strip()
        existing = self.search([('company_id', '=', self.env.company.id), ('created_by_id', '=', self.env.uid),
                                ('client_token', '=', token)], limit=1) if token else self.browse()
        if existing:
            return existing.id
        representative = self.env['res.partner'].browse(_catalog_identifier(representative_partner_id)).exists()
        if representative != request.representative_partner_id or not representative:
            raise ValidationError(_('The transfer destination must match the purchase representative on the selected request.'))
        self._baseer_lock_representative_balance(self.env.company, representative)
        self._lock_request(request.id)
        request.invalidate_recordset()
        if request.receipt_custody_confirmed:
            raise UserError(_('This receipt already confirmed its representative advance. Contact an accountant for corrections.'))
        return super().submit_funding(request_id, payment_journal_id, representative_partner_id, amount, client_token,
                                      movement_date, external_reference, transfer_proof, transfer_proof_filename)
