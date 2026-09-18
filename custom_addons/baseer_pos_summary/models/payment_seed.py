"""Company-scoped, fill-once POS defaults; native ledger remains authoritative."""
from odoo import api, Command, models, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import clean_context


APPLICATIONS = (
    ('hungerstation', 'هنقرستيشن | HungerStation', '102110'),
    ('keeta', 'كيتا | Keeta', '102111'),
    ('jahez', 'جاهز | Jahez', '102112'),
)
class Company(models.Model):
    _inherit = 'res.company'

    @api.model
    def _baseer_initialize_pos_payments(self):
        """Legacy XML entry point: upgrades must never provision all companies."""
        return self.env['res.company']

    def _baseer_pos_identity(self, key, model, record=None):
        self.ensure_one()
        name = f'payment_seed_{key}_company_{self.id}'
        data = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_pos_summary'), ('name', '=', name)], limit=1)
        if data:
            # Read durable onboarding metadata in the target company's context.
            # The wizard is intentionally available while its manager is active
            # in another company, where regular POS record rules hide this
            # company-owned configuration.
            existing = self.env[model].sudo().browse(data.res_id).exists() if data.model == model else self.env[model]
            owned = existing and (self in existing.company_ids if model == 'account.account' else existing.company_id == self)
            if not owned:
                raise ValidationError(_('Invalid POS payment seed reference: %s', name))
            return existing
        if record:
            self.env['ir.model.data'].create({'module': 'baseer_pos_summary', 'name': name,
                'model': model, 'res_id': record.id, 'noupdate': True})
            return record
        return self.env[model]

    def _baseer_pos_account(self, key, code, name, kind, reconcile=True):
        account = self._baseer_pos_identity(key, 'account.account')
        if not account:
            accounts = self.env['account.account']
            account = accounts.create({'name': name,
                'code': accounts._search_new_account_code(code, cache=set()),
                'account_type': kind, 'reconcile': reconcile, 'company_ids': [Command.set(self.ids)]})
            self._baseer_pos_identity(key, account._name, account)
        return account

    def _baseer_pos_journal(self, key, code, name, kind, account=None):
        journal = self._baseer_pos_identity(key, 'account.journal')
        if not journal:
            codes = set(self.env['account.journal'].search([('company_id', '=', self.id)]).mapped('code'))
            if code in codes:
                code = next((f'PS{i:03}' for i in range(1, 1000) if f'PS{i:03}' not in codes), None)
                if not code:
                    raise ValidationError(_('No available POS seed journal code.'))
            values = {'name': name, 'code': code, 'type': kind, 'company_id': self.id}
            if account:
                values['default_account_id'] = account.id
            journal = self.env['account.journal'].create(values)
            self._baseer_pos_identity(key, journal._name, journal)
        return journal

    def _baseer_pos_category(self, kind, name, sequence):
        category = self._baseer_pos_identity('category_' + kind, 'baseer.pos.payment.category')
        if not category:
            category = self.env['baseer.pos.payment.category'].create({
                'name': name, 'kind': kind, 'sequence': sequence, 'company_id': self.id})
            self._baseer_pos_identity('category_' + kind, category._name, category)
        return category

    def _baseer_pos_method(self, key, name, category, journal, receivable, outstanding=None):
        method = self._baseer_pos_identity('method_' + key, 'pos.payment.method')
        if not method:
            method = self.env['pos.payment.method'].create({
                'name': name, 'company_id': self.id, 'baseer_category_id': category.id,
                'journal_id': journal.id, 'receivable_account_id': receivable.id,
                'outstanding_account_id': outstanding.id if outstanding else False,
                'split_transactions': False, 'payment_method_type': 'none',
                'sequence': category.sequence})
            self._baseer_pos_identity('method_' + key, method._name, method)
        return method

    def _baseer_seed_pos_payments(self):
        """Deprecated bulk path kept harmless for old callers."""
        return self.env['pos.config']

    def _baseer_create_pos_defaults(self):
        """Compatibility wrapper; new code must pass the user's explicit choices."""
        return self._baseer_apply_summary_payment_choices(
            {'cash', 'bank', *(key for key, _label, _code in APPLICATIONS)}
        )

    def _baseer_apply_summary_payment_choices(self, selected_keys):
        """Add only selected summary methods for one company; never replace history."""
        self.ensure_one()
        selected = set(selected_keys or ())
        supported = {'cash', 'bank', *(key for key, _label, _code in APPLICATIONS)}
        if not selected or not selected <= supported:
            raise ValidationError(_('Choose one or more supported sales-summary payment methods.'))
        if self.parent_id or self.chart_template != 'sa' or self.currency_id.name != 'SAR':
            raise ValidationError(_('Saudi accounting and SAR are required before configuring sales summaries.'))
        company = self.sudo().with_context(dict(clean_context(self.env.context),
            allowed_company_ids=[self.id], active_test=False, lang='en_US')).with_company(self)
        company.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
        company.invalidate_recordset()
        config = company.env['pos.config'].search([
            ('company_id', '=', company.id), ('baseer_summary_only', '=', True)], limit=1)
        owned_config = company._baseer_pos_identity('config', 'pos.config')
        if config and config != owned_config:
            raise ValidationError(_('Review the existing sales-summary POS before adding payment methods.'))
        if owned_config and not owned_config.active:
            raise ValidationError(_('Review the archived sales-summary POS before adding payment methods.'))
        config = owned_config or config
        has_history = config and (company.env['pos.session'].search_count([('config_id', '=', config.id)], limit=1)
            or company.env['baseer.pos.summary'].search_count([('config_id', '=', config.id)], limit=1))
        if has_history:
            config._validate_baseer_setup()
        category_definitions = {
            'cash': ('نقدي | Cash', 10),
            'bank': ('بنك | Bank', 20),
            'platform': ('تطبيقات | Applications', 30),
        }
        categories = {}
        for kind in ({'cash'} if 'cash' in selected else set()) | ({'bank'} if 'bank' in selected else set()) | ({'platform'} if selected & {key for key, _label, _code in APPLICATIONS} else set()):
            name, sequence = category_definitions[kind]
            categories[kind] = company._baseer_pos_category(kind, name, sequence)
        receivable = company.account_default_pos_receivable_account_id
        if not (receivable and receivable.active and receivable.reconcile
                and receivable.account_type == 'asset_receivable' and company in receivable.company_ids):
            receivable = company._baseer_pos_account('receivable', '102095',
                'وسيط ملخص المبيعات | Sales summary intermediary', 'asset_receivable')
        methods = company.env['pos.payment.method']
        if 'cash' in selected:
            cash_account = company._baseer_pos_account('cash_account', '105090',
                'صندوق ملخص المبيعات | Sales summary cash', 'asset_cash', False)
            cash = company._baseer_pos_journal('cash_journal', 'PSCSH',
                'صندوق ملخص المبيعات | Sales summary cash', 'cash', cash_account)
            methods |= company._baseer_pos_method('cash', 'نقدي | Cash', categories['cash'], cash, receivable)
        bank_account = company.env['account.account']
        bank = company.env['account.journal']
        if selected - {'cash'}:
            bank_account = company._baseer_pos_account('bank_account', '101090',
                'البنك - ملخص المبيعات | Bank - sales summaries', 'asset_cash')
            bank = company._baseer_pos_journal('bank_journal', 'PSBNK',
                'تحصيلات ملخص المبيعات | Sales summary receipts', 'bank', bank_account)
        if 'bank' in selected:
            methods |= company._baseer_pos_method('bank', 'بنك | Bank', categories['bank'], bank, receivable, bank_account)
        for key, label, code in APPLICATIONS:
            if key not in selected:
                continue
            arabic, english = label.split(' | ')
            account = company._baseer_pos_account(key + '_clearing', code,
                f'مستحقات {arabic} | {english} receivable', 'asset_current')
            methods |= company._baseer_pos_method(key, label, categories['platform'], bank, receivable, account)
        if not config:
            config = company.env['pos.config'].create({'name': 'ملخص المبيعات | Sales summaries',
                'company_id': company.id, 'baseer_summary_only': True,
                'payment_method_ids': [Command.set(methods.ids)]})
        else:
            additions = methods - config.payment_method_ids
            if has_history and len(config.payment_method_ids | additions) > 25:
                raise ValidationError(_('There is no capacity to add the selected summary payment methods.'))
            if additions:
                config.write({'payment_method_ids': [Command.link(method.id) for method in additions]})
        updates = {}
        if not config.baseer_summary_product_id:
            income = company.income_account_id
            if not income or income.account_type not in ('income', 'income_other'):
                income = company._baseer_pos_account('income', '500090',
                    'إيرادات ملخص المبيعات | Sales summary revenue', 'income', False)
            product = company.env['product.product'].create({'name': 'ملخص المبيعات | Sales summary',
                'type': 'service', 'company_id': company.id, 'sale_ok': True, 'purchase_ok': False,
                'property_account_income_id': income.id})
            updates['baseer_summary_product_id'] = product.id
        if not config.baseer_summary_tax_id:
            tax = company.account_sale_tax_id
            if not tax or tax.type_tax_use != 'sale':
                raise ValidationError(_('Configure the company sales tax before creating POS payment defaults.'))
            updates['baseer_summary_tax_id'] = tax.id
        if updates:
            config.write(updates)
        config._validate_baseer_setup()
        company._baseer_pos_identity('config', config._name, config)
        return config


class PosConfig(models.Model):
    _inherit = 'pos.config'

    def _get_group_pos_manager(self):
        # pos_hr.write otherwise creates a cashier employee for a company manager.
        # A summary-only POS never opens the cashier UI or needs cashier staff.
        # This must also cover deferred native recomputations after seed context
        # expires. Empty-record default resolution retains the real group field.
        if self and all(self.mapped('baseer_summary_only')):
            return self.env['res.groups']
        return super()._get_group_pos_manager()
