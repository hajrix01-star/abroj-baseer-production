from odoo import _, api, fields, models
from odoo.exceptions import AccessError


class PurchaseBatch(models.Model):
    _inherit = 'baseer.purchase.batch'

    is_cashier = fields.Boolean(compute='_compute_cashier_approval_access')
    cashier_batch_approval_allowed = fields.Boolean(
        compute='_compute_cashier_approval_access',
    )

    @api.depends('company_id', 'create_uid', 'state')
    @api.depends_context('uid', 'company')
    def _compute_cashier_approval_access(self):
        is_cashier = self.env.user.has_group('baseer_access_roles.group_cashier')
        active_company = self.env.company
        for batch in self:
            batch.is_cashier = is_cashier
            batch.cashier_batch_approval_allowed = bool(
                is_cashier
                and batch.state == 'draft'
                and batch.create_uid == self.env.user
                and batch.company_id == active_company
                and batch.company_id.sudo().cashier_purchase_batch_approval_enabled
            )

    def action_approve(self):
        if self.env.user.has_group('baseer_access_roles.group_cashier'):
            return self.action_cashier_approve()
        return super().action_approve()

    def _check_cashier_approval_policy_at_lock(self, actor):
        """Recheck the policy after the parent flow locks batch and company."""
        self.ensure_one()
        if not actor.has_group('baseer_access_roles.group_cashier'):
            raise AccessError(_('Only a cashier can use cashier purchase-batch approval.'))
        if self.company_id != self.env.company or self.company_id not in actor.company_ids:
            raise AccessError(_('Switch to the batch company before approving this purchase batch.'))
        if self.create_uid != actor:
            raise AccessError(_('Cashiers can approve only purchase batches they created.'))
        if self.state != 'draft':
            raise AccessError(_('Only a draft purchase batch can be approved.'))
        if not self.company_id.cashier_purchase_batch_approval_enabled:
            raise AccessError(_('Cashier purchase-batch approval is disabled for this company.'))

    def action_cashier_approve(self):
        """Server-only authorization wrapper for a cashier's own batch.

        The actor is derived from the session. It is never accepted through a
        browser context or an RPC argument, and the private core helper repeats
        this policy after its company mutex has been acquired.
        """
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('baseer_access_roles.group_cashier'):
            raise AccessError(_('Only a cashier can use cashier purchase-batch approval.'))
        if self.state != 'draft':
            raise AccessError(_('Only a draft purchase batch can be approved.'))
        actor = self.env['res.users'].sudo().browse(self.env.uid).exists()
        with self.env.cr.savepoint():
            self.sudo()._approve_as_actor(
                actor,
                authorization_check=lambda batch: batch._check_cashier_approval_policy_at_lock(actor),
            )
            self.env['baseer.purchase.batch.cashier.approval.audit'].sudo().create({
                'batch_id': self.id,
                'company_id': self.company_id.id,
                'actor_user_id': actor.id,
                'execution_user_id': self.sudo().env.user.id,
                'approved_at': fields.Datetime.now(),
            })
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_view_bills(self):
        if self.env.user.has_group('baseer_access_roles.group_cashier'):
            raise AccessError(_('Cashiers can view their batch details, not the accounting documents.'))
        return super().action_view_bills()

    def _get_print_data(self):
        if self.env.user.has_group('baseer_access_roles.group_cashier'):
            self.ensure_one()
            self.check_access('read')
            if self.company_id not in self.env.user.company_ids:
                raise AccessError(_('The company is outside your authorized companies.'))
            # Fixed-shape existing summary of the verified own batch only. Elevation
            # reads its bill reference, not native invoice/payment records for RPC.
            return super(PurchaseBatch, self.sudo())._get_print_data()
        return super()._get_print_data()


class PurchaseBatchLine(models.Model):
    _inherit = 'baseer.purchase.batch.line'

    baseer_bill_reference = fields.Char(
        string='Approved Bill Reference', compute='_compute_baseer_bill_reference',
        compute_sudo=False,
    )

    @api.depends('move_id')
    def _compute_baseer_bill_reference(self):
        for line in self:
            if line.move_id:
                line.check_access('read')
                line.baseer_bill_reference = line.move_id.sudo().name or ''
            else:
                line.baseer_bill_reference = ''

    def action_view_bill(self):
        if self.env.user.has_group('baseer_access_roles.group_cashier'):
            raise AccessError(_('Cashiers can view their batch details, not the accounting documents.'))
        return super().action_view_bill()
