from collections import defaultdict
from decimal import Decimal, InvalidOperation

from odoo import _, api, models
from odoo.exceptions import ValidationError


class AccountAnalyticDistributionModel(models.Model):
    _inherit = 'account.analytic.distribution.model'

    @api.model
    def _baseer_validate_spend_values(self, distribution, company):
        """Check JSON identity/percentages before the native 100% validator.

        Native joint keys represent DIFFERENT dimensions, never two accounts
        within the same spend root. Metadata reads do not grant config access.
        """
        if not distribution:
            return
        invalid = _('Choose a valid analytic distribution: distinct accounts, valid percentages, and one Spend Classification account per allocation.')
        if not isinstance(distribution, dict):
            raise ValidationError(invalid)
        selections = []
        ids = set()
        for key, value in distribution.items():
            parts = key.split(',') if isinstance(key, str) else []
            if not parts or any(not part.isascii() or not part.isdigit() or int(part) <= 0 for part in parts):
                raise ValidationError(invalid)
            selected = [int(part) for part in parts]
            if len(selected) != len(set(selected)) or isinstance(value, bool):
                raise ValidationError(invalid)
            try:
                percentage = Decimal(str(value))
            except (InvalidOperation, ValueError, TypeError):
                raise ValidationError(invalid) from None
            if not percentage.is_finite() or percentage < 0 or percentage > 100:
                raise ValidationError(invalid)
            selections.append(selected)
            ids.update(selected)
        accounts = self.env['account.analytic.account'].sudo().browse(ids).exists()
        if set(accounts.ids) != ids:
            raise ValidationError(invalid)
        root = self.env.ref('baseer_native_spend.spend_plan')
        spend = accounts.filtered(lambda account: account.root_plan_id == root)
        if any(not account.active or (account.company_id and account.company_id != company) for account in spend):
            raise ValidationError(_('Choose active Spend Classification accounts belonging to this company or shared accounts.'))
        spend_ids = set(spend.ids)
        if any(len(spend_ids.intersection(selected)) > 1 for selected in selections):
            raise ValidationError(invalid)

    @api.model
    def _get_distribution(self, vals):
        arguments = dict(vals)
        protected = arguments.pop('_baseer_vendor_spend', False)
        result = super()._get_distribution(arguments)
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not protected or not root or root in arguments.get('related_root_plan_ids', self.env['account.analytic.plan']):
            return result
        applicable = self._get_applicable_models({
            key: value for key, value in arguments.items() if key != 'related_root_plan_ids'
        })
        candidates = applicable.filtered(lambda model: root in model.distribution_analytic_account_ids.root_plan_id)
        if not candidates:
            return result
        explicit = candidates.filtered(lambda model: model.product_id or model.product_categ_id or model.partner_id)
        selected = self.browse()
        if explicit:
            selected = explicit.sorted(key=lambda model: (
                0 if model.product_id else 1 if model.product_categ_id else 2,
                not bool(model.company_id), model.sequence, -model.id,
            ))[:1]
        else:
            tag_candidates = candidates.filtered('partner_category_id')
            # A company-specific model may override the shared model for the same
            # tag. Resolve that override first, then compare distinct tag results.
            tag_winners = self.browse()
            seen_tags = set()
            for model in tag_candidates.sorted(key=lambda model: (
                not bool(model.company_id), model.sequence, -model.id,
            )):
                if model.partner_category_id.id not in seen_tags:
                    seen_tags.add(model.partner_category_id.id)
                    tag_winners |= model
            destinations = tag_winners.distribution_analytic_account_ids.filtered(lambda account: account.root_plan_id == root)
            if len(destinations) <= 1:
                eligible = tag_winners or candidates.filtered(lambda model: not model.partner_category_id)
                selected = eligible.sorted(key=lambda model: (
                    not bool(model.partner_category_id), not bool(model.company_id), model.sequence, -model.id,
                ))[:1]
        spend_distribution = defaultdict(float)
        if selected:
            spend_ids = set(selected.distribution_analytic_account_ids.filtered(lambda account: account.root_plan_id == root).ids)
            for key, percentage in selected.analytic_distribution.items():
                kept = sorted(int(account_id) for account_id in key.split(',') if int(account_id) in spend_ids)
                if kept:
                    spend_distribution[','.join(map(str, kept))] += percentage
        # Replace this dimension only; native merge retains projects/other dimensions.
        return self._merge_distribution(result, dict(spend_distribution) | {'__update__': [root._column_name()]})
