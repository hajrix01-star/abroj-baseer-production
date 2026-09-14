from odoo import fields, models


class PurchaseBatchCashierApprovalAudit(models.Model):
    _name = 'baseer.purchase.batch.cashier.approval.audit'
    _description = 'Cashier Purchase Batch Approval Audit'
    _order = 'approved_at desc, id desc'
    _check_company_auto = True

    _batch_unique = models.Constraint(
        'unique(batch_id)',
        'A cashier purchase batch can have only one self-approval audit record.',
    )

    batch_id = fields.Many2one(
        'baseer.purchase.batch', required=True, readonly=True, ondelete='restrict', index=True,
    )
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, ondelete='restrict', index=True,
    )
    actor_user_id = fields.Many2one(
        'res.users', required=True, readonly=True, ondelete='restrict', index=True,
    )
    execution_user_id = fields.Many2one(
        'res.users', required=True, readonly=True, ondelete='restrict', index=True,
    )
    approved_at = fields.Datetime(required=True, readonly=True, index=True)
