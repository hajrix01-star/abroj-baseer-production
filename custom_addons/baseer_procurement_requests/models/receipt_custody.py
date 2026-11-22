"""Compatibility and authorization boundaries for historical receipt funding."""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .procurement import _catalog_identifier

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
        return False

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
        return {'required': False}

    @api.model
    def prepare_receipt_custody(self, request_id):
        return self._receipt_custody_request(request_id)._receipt_custody_context()

    @api.model
    def confirm_actual_from_catalog(self, request_id, lines, receipt_custody=False):
        if receipt_custody:
            raise ValidationError(_('Receipt no longer records Representative Petty Cash. Reload the page and record the transfer separately.'))
        return super().confirm_actual_from_catalog(request_id, lines)

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
        if not request_id:
            return super().submit_funding(request_id, payment_journal_id, representative_partner_id, amount, client_token,
                                          movement_date, external_reference, transfer_proof, transfer_proof_filename)
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
