from decimal import Decimal, InvalidOperation

from odoo import api, models


_PARENT_PLAN_ALIASES = {
    # These two source taxonomy labels deliberately have business-friendly
    # plan names.  Keep the mapping here instead of relying on an installed
    # UI language during a background company-creation transaction.
    'الموظفون والقوى العاملة': 'تكاليف الموظفين والتزامات نظامية',
    'الجهات الحكومية والامتثال': 'جهات حكومية',
}

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

        A shared analytic account or an arbitrary distribution model is not
        enough.  Every leaf tag under a configured spend parent must have one
        approved shared map and one valid 100% native Odoo model pointing to
        the same active shared leaf.  This keeps a partial seed from silently
        turning a new company's bill workflow mandatory.
        """
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not root:
            return False
        Plan = self.env['account.analytic.plan'].sudo()
        Category = self.env['res.partner.category'].sudo()
        plans = Plan.search([('parent_id', '=', root.id)])
        if not plans:
            return False
        plans_by_name = {plan.name: plan for plan in plans}
        parent_plans = {}
        for category in Category.search([('parent_id', '=', False)]):
            plan = plans_by_name.get(category.name) or plans_by_name.get(
                _PARENT_PLAN_ALIASES.get(category.name)
            )
            if plan:
                parent_plans[category.id] = plan
        leaves = Category.search([('parent_id', 'in', list(parent_plans))])
        if not leaves:
            return False

        rules = self.env['baseer.spend.map.rule'].sudo().search([
            ('company_id', '=', False), ('selector_kind', '=', 'partner_tag'),
            ('state', '=', 'approved'),
        ])
        models = self.env['account.analytic.distribution.model'].sudo().search([
            ('company_id', '=', False),
        ])
        for leaf in leaves:
            plan = parent_plans[leaf.parent_id.id]
            matching_rules = rules.filtered(lambda rule: rule.partner_tag_id == leaf)
            if len(matching_rules) != 1:
                return False
            account = matching_rules.analytic_account_id
            if (not account.active or account.company_id or account.plan_id != plan
                    or account.root_plan_id != root):
                return False
            matching_models = models.filtered(lambda model: model.partner_category_id == leaf)
            if len(matching_models) != 1:
                return False
            model = matching_models
            spend_accounts = model.distribution_analytic_account_ids.filtered(
                lambda candidate: candidate.root_plan_id == root
            )
            if spend_accounts.ids != account.ids:
                return False
            total = Decimal('0')
            try:
                for key, percentage in (model.analytic_distribution or {}).items():
                    ids = {int(part) for part in str(key).split(',')}
                    if account.id in ids:
                        total += Decimal(str(percentage))
            except (InvalidOperation, TypeError, ValueError):
                return False
            if total != Decimal('100'):
                return False
        return True

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
