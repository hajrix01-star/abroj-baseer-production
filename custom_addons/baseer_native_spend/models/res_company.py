from odoo import api, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        # The catalog is shared: a company created after the reviewed native
        # template exists must get the same posting guard as every existing
        # company.  Before that point we deliberately keep Odoo optional, so
        # installing the technical module cannot strand a newly-created
        # company without an approved classification route.
        if companies._baseer_has_shared_spend_template():
            companies._baseer_ensure_spend_applicability()
        return companies

    def _baseer_has_shared_spend_template(self):
        """Whether a reusable native Odoo spend mapping is available.

        A shared analytic account by itself is not enough: the template must
        contain a shared native distribution model that routes a vendor bill
        into the Spend Classification root.  This makes creating a later
        company deterministic without copying per-company configuration.
        """
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not root:
            return False
        models = self.env['account.analytic.distribution.model'].sudo().search([
            ('company_id', '=', False),
        ])
        return any(
            root in model.distribution_analytic_account_ids.root_plan_id
            for model in models
        )

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
