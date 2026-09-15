from odoo import api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        # A company remains on Odoo's normal optional workflow until its
        # approved analytic map is provisioned.  The mapping wave enables the
        # mandatory rule explicitly; creating an empty company must not make
        # vendor bills fail before the company has a chart and map.
        return companies

    def _baseer_ensure_spend_applicability(self):
        """Fill absent native setup only; preserve reviewed applicability rules."""
        plan = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not plan or not self:
            return
        plan = plan.sudo()
        plan.flush_recordset(['default_applicability'])
        # A no-op write serialises provisioning under REPEATABLE READ as well:
        # a waiter with an older snapshot must retry instead of inserting a
        # second applicability after a lock-only predecessor commits.
        self.env.cr.execute(
            'UPDATE account_analytic_plan SET id = id WHERE id = %s RETURNING default_applicability',
            [plan.id],
        )
        stored_defaults = self.env.cr.fetchone()[0] or {}
        plan.invalidate_recordset(['default_applicability'])
        applicability = self.env['account.analytic.applicability'].sudo()
        for company in self.sudo():
            if str(company.id) not in stored_defaults:
                plan.with_company(company).default_applicability = 'unavailable'
            existing = applicability.search([
                ('analytic_plan_id', '=', plan.id),
                ('company_id', '=', company.id),
                ('business_domain', '=', 'bill'),
            ], limit=1)
            if not existing:
                applicability.create({
                    'analytic_plan_id': plan.id,
                    'company_id': company.id,
                    'business_domain': 'bill',
                    'applicability': 'mandatory',
                })
