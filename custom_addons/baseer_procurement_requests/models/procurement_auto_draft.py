"""Server-owned purchase-batch drafts created from completed receipts.

The receipt remains the authority for its actual total and route.  A draft is
only an accountant inbox item: it must never create a vendor bill, payment, or
custody settlement until the normal batch approval workflow runs.
"""

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


AUTO_DRAFT_INTERNAL = 'baseer_procurement_auto_draft_internal'


class ProcurementRequest(models.Model):
    _inherit = 'baseer.procurement.request'

    def action_confirm_actual_purchase(self):
        result = super().action_confirm_actual_purchase()
        for request in self:
            request._ensure_purchase_batch_auto_draft()
        return result

    def _ensure_purchase_batch_auto_draft(self):
        """Create exactly one non-accounting draft after a completed receipt.

        ``action_confirm_actual_purchase`` already locks the request row.  The
        unique batch header link remains the durable last line of protection
        for retried or concurrent receipt confirmations.
        """
        self.ensure_one()
        if self.state != 'purchased':
            return self.env['baseer.purchase.batch']
        company = self.company_id
        Batch = self.env['baseer.purchase.batch'].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id],
            **{AUTO_DRAFT_INTERNAL: True},
        )
        existing = Batch.search([('procurement_request_id', '=', self.id)], limit=1)
        if existing:
            if existing.procurement_auto_draft:
                return existing
            raise ValidationError(_(
                'This completed purchase request is already reserved by a manual supplier-bill batch.'
            ))

        values = {
            'company_id': company.id,
            'procurement_request_id': self.id,
            'procurement_auto_draft': True,
        }
        return Batch.create(values)


class BaseerPurchaseBatch(models.Model):
    _inherit = 'baseer.purchase.batch'

    procurement_auto_draft = fields.Boolean(
        string='Receipt invoice draft', readonly=True, copy=False, index=True,
        help='Created automatically after a completed purchase receipt; no accounting entry exists until approval.',
    )
    procurement_representative_funded_amount = fields.Monetary(
        compute='_compute_procurement_representative_funded_amount',
        string='Representative amount transferred', currency_field='currency_id', readonly=True,
    )
    procurement_request_representative_id = fields.Many2one(
        related='procurement_request_id.representative_partner_id',
        string='Purchase representative', readonly=True,
    )

    @api.depends('procurement_request_id', 'procurement_request_id.representative_partner_id')
    def _compute_procurement_representative_funded_amount(self):
        batches = self.filtered(lambda batch: batch.procurement_request_id and batch.procurement_purchase_route == 'representative')
        grouped = self.env['baseer.procurement.representative.advance'].sudo().read_group(
            [
                ('procurement_request_id', 'in', batches.mapped('procurement_request_id').ids),
                ('movement_type', '=', 'funding'),
                ('state', '=', 'posted'),
            ],
            ['procurement_request_id', 'amount:sum'], ['procurement_request_id'],
        ) if batches else []
        amounts = {row['procurement_request_id'][0]: row['amount'] for row in grouped if row['procurement_request_id']}
        for batch in self:
            batch.procurement_representative_funded_amount = amounts.get(batch.procurement_request_id.id, 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        Request = self.env['baseer.procurement.request']
        for values in vals_list:
            request_id = values.get('procurement_request_id')
            if request_id and not values.get('procurement_auto_draft'):
                request = Request.browse(request_id).exists()
                if not request or request.state != 'purchased':
                    raise ValidationError(_(
                        'A supplier-bill batch can be linked only to a completed purchase receipt.'
                    ))
        if any(values.get('procurement_auto_draft') for values in vals_list):
            if not (self.env.su and self.env.context.get(AUTO_DRAFT_INTERNAL)):
                raise AccessError(_('Receipt invoice drafts are created only by the completed-receipt workflow.'))
        return super().create(vals_list)

    def write(self, values):
        protected_auto_draft_fields = {
            'procurement_request_id', 'company_id', 'representative_petty_cash_id',
        }
        if protected_auto_draft_fields & set(values) and self.filtered('procurement_auto_draft'):
            raise AccessError(_(
                'The completed-receipt link and payment route of an automatic invoice draft are controlled by the server.'
            ))
        if 'procurement_auto_draft' in values:
            raise AccessError(_('Receipt invoice draft status is controlled by the server.'))
        return super().write(values)

    def unlink(self):
        if self.filtered('procurement_auto_draft'):
            raise AccessError(_('Automatic receipt invoice drafts cannot be deleted.'))
        return super().unlink()
