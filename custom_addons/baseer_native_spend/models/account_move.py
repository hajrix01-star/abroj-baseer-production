from odoo import _, api, models
from odoo.exceptions import ValidationError
from odoo.tools import frozendict


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        protected = self.filtered(lambda move: move.move_type in ('in_invoice', 'in_refund'))
        protected._baseer_validate_spend_foundation()
        return super()._post(soft=soft)

    def _baseer_validate_spend_foundation(self):
        """Reuse native percentage validation, including plain/background posting."""
        if not self:
            return
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        # This is the migration bridge.  If an installation is incomplete or
        # its old XML id is invalid, Odoo retains its ordinary optional vendor
        # bill workflow until the administrator explicitly activates a
        # company-specific mandatory rule after mapping.
        if not root or root.sudo().parent_id:
            return
        Account = self.env['account.analytic.account'].sudo()
        Applicability = self.env['account.analytic.applicability'].sudo()
        for company in self.company_id:
            plan = root.sudo().with_company(company)
            complete_rule = Applicability.search_count([
                ('analytic_plan_id', '=', plan.id), ('company_id', '=', company.id),
                ('business_domain', '=', 'bill'), ('applicability', '=', 'mandatory'),
                ('account_prefix', '=', False), ('product_categ_id', '=', False),
            ], limit=1)
            has_accounts = Account.search_count([
                ('plan_id', 'child_of', plan.id), ('active', '=', True),
                ('company_id', 'in', [False, company.id]),
            ], limit=1)
            # During the controlled mapping wave, companies without the
            # explicit mandatory rule remain on native optional behaviour.
            # Once that rule is enabled, the entire protected path fails
            # closed as before.
            if not complete_rule:
                continue
            if not has_accounts or plan.default_applicability != 'unavailable':
                raise ValidationError(_(
                    'Complete Spend Classification setup for %(company)s: an active analytic account, '
                    'a company-specific mandatory Vendor Bill applicability, and Unavailable default are required.',
                    company=company.display_name,
                ))
            lines = self.filtered(lambda move: move.company_id == company).invoice_line_ids.filtered(
                lambda line: line.display_type == 'product'
            )
            for line in lines:
                self.env['account.analytic.distribution.model']._baseer_validate_spend_values(
                    line.analytic_distribution, company,
                )
                arguments = {
                    'company_id': company.id, 'product': line.product_id.id,
                    'account': line.account_id.id, 'business_domain': 'bill',
                }
                if plan._get_applicability(**arguments) != 'mandatory':
                    raise ValidationError(_('Spend Classification must remain mandatory for every vendor bill item. Review its applicability rules.'))
                selected_ids = {
                    int(account_id)
                    for key in (line.analytic_distribution or {})
                    for account_id in key.split(',')
                }
                spend_accounts = Account.browse(selected_ids).exists().filtered(lambda account: account.root_plan_id == plan)
                if any(not account.active or (account.company_id and account.company_id != company) for account in spend_accounts):
                    raise ValidationError(_('Choose active Spend Classification accounts belonging to this company or shared accounts.'))
                line.with_context(validate_analytic=True)._validate_distribution(**arguments)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.depends('account_id', 'partner_id', 'product_id')
    def _compute_analytic_distribution(self):
        super()._compute_analytic_distribution()
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not root:
            return
        Account = self.env['account.analytic.account']
        Distribution = self.env['account.analytic.distribution.model']
        cache = {}
        for line in self:
            if line.move_id.move_type not in ('in_invoice', 'in_refund') or line.display_type != 'product':
                continue
            current = line.analytic_distribution or {}
            selected_ids = {int(account_id) for key in current for account_id in key.split(',')}
            if root not in Account.browse(selected_ids).exists().root_plan_id:
                continue
            related = line._related_analytic_distribution()
            related_ids = {int(account_id) for key in related for account_id in key.split(',')}
            related_roots = Account.browse(related_ids).exists().root_plan_id
            if root in related_roots:
                continue
            arguments = frozendict(line._get_analytic_distribution_arguments(related_roots))
            if arguments not in cache:
                proposed = Distribution._get_distribution(arguments)
                proposed_ids = {int(account_id) for key in proposed for account_id in key.split(',')}
                cache[arguments] = root in Account.browse(proposed_ids).exists().root_plan_id
            if not cache[arguments]:
                # Native fallback retains the previous distribution when no model
                # matches. A changed source must not silently retain its old spend
                # category. Explicit distributions assigned without a dependency
                # change do not invoke this compute and retain native editability.
                line.analytic_distribution = Distribution._merge_distribution(
                    dict(current), {'__update__': [root._column_name()]},
                )

    def _get_analytic_distribution_arguments(self, root_plans):
        arguments = super()._get_analytic_distribution_arguments(root_plans)
        if self.move_id.move_type in ('in_invoice', 'in_refund') and self.display_type == 'product':
            arguments['_baseer_vendor_spend'] = True
        return arguments
