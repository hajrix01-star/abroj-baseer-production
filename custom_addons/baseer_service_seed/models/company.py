"""Fill-only company service masters; all financial posting remains native."""
from decimal import Decimal, InvalidOperation

from odoo import api, Command, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.misc import clean_context

from .catalog import ACCOUNT_PURPOSES, PROVIDERS, SERVICES


HR_SERVICE_ANALYTIC_LEAVES = (
    ('permits', 'إقامات وجوازات', 'Employee permits and passports'),
    ('health', 'فحوص وشهادات صحية للموظفين', 'Employee health checks and certificates'),
    ('tickets', 'تذاكر سفر الموظفين', 'Employee travel tickets'),
    ('insurance', 'تأمين طبي', 'Employee medical insurance'),
    ('processing', 'خدمات تعقيب الموظفين', 'Employee processing services'),
    ('other', 'خدمات موظفين أخرى', 'Other employee services'),
)

HR_SERVICE_ANALYTIC_MAP = {
    'iqama_issue': 'permits', 'iqama_renewal': 'permits',
    'work_permit_issue': 'permits', 'work_permit_renewal': 'permits',
    'employee_transfer': 'permits', 'profession_change': 'permits', 'visa': 'permits',
    'health_certificate_issue': 'health', 'health_certificate_renewal': 'health',
    'medical_exam': 'health', 'ticket': 'tickets',
    'insurance_issue': 'insurance', 'insurance_renewal': 'insurance',
    'processing': 'processing', 'other_employee': 'other',
}


class Company(models.Model):
    _inherit = 'res.company'

    @api.model
    def _baseer_initialize_services(self):
        """Legacy private entry point; deliberately does not scan companies.

        Module upgrades must never provision or alter historic companies merely
        because the service catalog changed.  New companies use the accounting
        callback; an existing company uses the explicit readiness action.
        """
        return self.env['res.company']

    def _baseer_service_identity(self, kind, key, model, record=None):
        self.ensure_one()
        name = f'{kind}_{key}_company_{self.id}'
        data = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', name)], limit=1)
        if data:
            if data.model != model:
                raise ValidationError(_('The service seed reference has the wrong model: %s', name))
            # This durable identity is internal readiness metadata.  A company
            # manager may run the onboarding wizard while their active company
            # is different from the company being prepared, so normal product
            # record rules can hide an otherwise valid company-owned product
            # during the read-only refresh.  Do not expose the record through
            # this helper; use sudo only to resolve and validate the identity.
            existing = self.env[model].sudo().browse(data.res_id).exists()
            if not existing:
                raise ValidationError(_('A referenced service seed record was deleted: %s', name))
            owned = (self in existing.company_ids if model == 'account.account' else
                     existing.company_id in (self, self.env['res.company']) if kind == 'provider' and model == 'res.partner' else
                     existing.company_id in (self, self.env['res.company']) if model == 'product.product' else
                     existing.company_id == self)
            if not owned:
                raise ValidationError(_('The service seed reference belongs to another company: %s', name))
            return existing
        if record:
            self.env['ir.model.data'].create({
                'module': 'baseer_service_seed', 'name': name, 'model': model,
                'res_id': record.id, 'noupdate': True,
            })
            return record
        return self.env[model]

    def _baseer_service_account(self, purpose):
        account = self._baseer_service_identity('account', purpose, 'account.account')
        if account:
            return account
        native_code, fallback_code, label = ACCOUNT_PURPOSES[purpose]
        if self.chart_template == 'sa' and native_code:
            candidate = self.env.ref(f'account.{self.id}_sa_account_{native_code}', raise_if_not_found=False)
            if (candidate and self in candidate.company_ids and candidate.active
                    and candidate.account_type == 'expense'):
                account = candidate
        if not account:
            account_model = self.env['account.account']
            code = account_model._search_new_account_code(fallback_code, cache=set())
            account = account_model.create({
                'name': label, 'code': code, 'account_type': 'expense',
                'company_ids': [Command.set(self.ids)], 'reconcile': False,
            })
        return self._baseer_service_identity('account', purpose, 'account.account', account)

    def _baseer_replace_service_identity(self, kind, key, record):
        """Point an existing company seed reference at its safe replacement."""
        self.ensure_one()
        name = f'{kind}_{key}_company_{self.id}'
        data = self.env['ir.model.data'].search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', name)], limit=1)
        if not data:
            return self._baseer_service_identity(kind, key, record._name, record)
        if data.model != record._name:
            raise ValidationError(_('The service seed reference has the wrong model: %s', name))
        data.res_id = record.id
        return record

    def _baseer_service_product(self, service, accounts):
        key, english, arabic, purpose = service
        category = self.env.ref(f'baseer_service_seed.category_{key}')
        product = self._baseer_service_identity('product', key, 'product.product')
        if product and not product.company_id:
            # A legacy shared product cannot receive a company-specific expense
            # account or analytic rule. Preserve it for historical documents
            # and create the explicitly-owned replacement below.
            if product.type != 'service' or not product.purchase_ok:
                raise ValidationError(_('Review the shared native service product: %s', product.display_name))
            product = self.env['product.product']
        if not product:
            account = accounts.get(purpose)
            if account is None:
                account = accounts[purpose] = self._baseer_service_account(purpose)
            if not account.active or account.account_type != 'expense':
                raise ValidationError(_('Review the archived or changed service expense account: %s', account.display_name))
            product = self.env['product.product'].with_context(lang='en_US').create({
                'name': english, 'default_code': f'BASEER-SVC-{key.upper()}',
                'type': 'service', 'company_id': self.id, 'categ_id': category.id,
                'sale_ok': False, 'purchase_ok': True,
                'property_account_expense_id': account.id,
                'supplier_taxes_id': [Command.clear()], 'taxes_id': [Command.clear()],
            })
            # Only newly created products receive translated names.
            for language in self.env['res.lang'].search([('code', 'in', ['ar_001', 'ar']), ('active', '=', True)]):
                product.with_context(lang=language.code).name = arabic
            self._baseer_replace_service_identity('product', key, product)
        else:
            # Earlier seeds may have created the exact service product inactive
            # and without its expense account.  The readiness action may repair
            # only that known, otherwise valid product; it never revives or
            # rewrites an unrelated product.
            if not product.active:
                if product.company_id != self or product.type != 'service' or not product.purchase_ok:
                    raise ValidationError(_('Review the inactive native service product: %s', product.display_name))
                product.active = True
            if not product.with_company(self).property_account_expense_id:
                # Fill only the empty field from the declared Saudi purpose;
                # never replace an existing account.
                account = accounts.get(purpose)
                if account is None:
                    account = accounts[purpose] = self._baseer_service_account(purpose)
                if not account.active or account.account_type != 'expense':
                    raise ValidationError(_('Review the archived or changed service expense account: %s', account.display_name))
                product.with_company(self).property_account_expense_id = account
        return product

    def _baseer_service_provider(self, provider):
        return self._baseer_shared_service_provider(provider)

    def _baseer_hr_analytic_identity(self, kind, key, model, record=None):
        """Return a durable service-analytics identity without name adoption."""
        self.ensure_one()
        name = f'hr_analytic_{kind}_{key}'
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', name)], limit=1)
        if data:
            if data.model != model:
                raise ValidationError(_('The employee-service analytic reference has the wrong model: %s', name))
            existing = self.env[model].sudo().with_context(active_test=False).browse(data.res_id).exists()
            if not existing:
                raise ValidationError(_('A referenced employee-service analytic record was deleted: %s', name))
            if record and existing != record:
                raise ValidationError(_('The employee-service analytic reference already belongs to another record: %s', name))
            return existing
        if record:
            self.env['ir.model.data'].sudo().create({
                'module': 'baseer_service_seed', 'name': name, 'model': model,
                'res_id': record.id, 'noupdate': True,
            })
            return record
        return self.env[model]

    def _baseer_hr_analytic_root(self):
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        if not root or root.parent_id:
            raise ValidationError(_('Install and configure the native Spend Classification root before employee-service analytics.'))
        return root.sudo()

    def _baseer_hr_analytic_plan(self, create=False):
        self.ensure_one()
        root = self._baseer_hr_analytic_root()
        plan = self._baseer_hr_analytic_identity('plan', 'employees', 'account.analytic.plan')
        if not plan and create:
            plan = self.env['account.analytic.plan'].sudo().create({
                'name': 'تكاليف الموظفين',
                'description': 'Shared employee-service expense classification.',
                'parent_id': root.id,
                'sequence': 25,
            })
            plan = self._baseer_hr_analytic_identity('plan', 'employees', plan._name, plan)
        if plan and plan.parent_id != root:
            raise ValidationError(_('Review the modified employee-service analytic plan.'))
        return plan

    def _baseer_hr_analytic_leaf(self, key, create=False):
        self.ensure_one()
        definition = dict((item[0], item) for item in HR_SERVICE_ANALYTIC_LEAVES).get(key)
        if not definition:
            raise ValidationError(_('Unknown employee-service analytic leaf: %s', key))
        plan = self._baseer_hr_analytic_plan(create=create)
        leaf = self._baseer_hr_analytic_identity('leaf', key, 'account.analytic.account')
        if not leaf and create:
            leaf = self.env['account.analytic.account'].sudo().create({
                'name': definition[1], 'plan_id': plan.id, 'company_id': False,
            })
            leaf = self._baseer_hr_analytic_identity('leaf', key, leaf._name, leaf)
        if leaf and (not leaf.active or leaf.company_id or leaf.plan_id != plan):
            raise ValidationError(_('Review the modified employee-service analytic leaf: %s', leaf.display_name))
        return leaf

    def _baseer_hr_service_analytic_model(self, service_type):
        self.ensure_one()
        return self._baseer_hr_analytic_identity('model', f'{service_type}_company_{self.id}',
                                                  'account.analytic.distribution.model')

    def _baseer_replace_hr_service_analytic_model(self, service_type, model):
        """Retain a legacy rule while making its replacement the company rule."""
        self.ensure_one()
        key = f'model_{service_type}_company_{self.id}'
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'baseer_service_seed'), ('name', '=', f'hr_analytic_{key}')], limit=1)
        if not data:
            return self._baseer_hr_analytic_identity('model', f'{service_type}_company_{self.id}', model._name, model)
        if data.model != model._name:
            raise ValidationError(_('The employee-service analytic reference has the wrong model: %s', data.name))
        data.res_id = model.id
        return model

    def _baseer_hr_service_analytic_distribution_is_valid(self, model, product, leaf):
        self.ensure_one()
        if not model or model.company_id != self or model.product_id != product:
            return False
        distribution = model.analytic_distribution or {}
        if set(distribution) != {str(leaf.id)}:
            return False
        try:
            return Decimal(str(distribution[str(leaf.id)])) == Decimal('100')
        except (InvalidOperation, TypeError, ValueError):
            return False

    def _baseer_hr_service_analytic_status(self, service_types=None):
        """Read-only readiness evidence for one company; no name-based adoption."""
        self.ensure_one()
        services = [service for service in SERVICES[:15]
                    if service_types is None or service[0] in set(service_types)]
        results = []
        if self.parent_id or not self.chart_template or self.currency_id.name != 'SAR':
            return [{'service_type': service[0], 'state': 'blocked',
                     'message': _('Saudi accounting and SAR are required before employee-service preparation.')}
                    for service in services]
        try:
            self._baseer_hr_analytic_root()
        except ValidationError as error:
            return [{'service_type': service[0], 'state': 'blocked', 'message': str(error)} for service in services]

        Native = self.env['account.analytic.distribution.model'].sudo().with_context(active_test=False)
        Product = self.env['product.product'].sudo().with_context(active_test=False)
        for service_type, _english, _arabic, _purpose in services:
            product = self._baseer_service_identity('product', service_type, 'product.product')
            leaf_key = HR_SERVICE_ANALYTIC_MAP[service_type]
            try:
                leaf = self._baseer_hr_analytic_leaf(leaf_key)
                model = self._baseer_hr_service_analytic_model(service_type)
            except ValidationError as error:
                results.append({'service_type': service_type, 'state': 'blocked', 'message': str(error)})
                continue
            if not product:
                legacy = Product.search([
                    ('company_id', '=', self.id),
                    ('default_code', '=', f'BASEER-SVC-{service_type.upper()}'),
                ], limit=1)
                results.append({'service_type': service_type,
                                'state': 'blocked' if legacy else 'missing',
                                'message': _('A legacy service product needs accountant review.') if legacy else
                                           _('The native service product is missing.')})
                continue
            if not product.company_id:
                if product.type != 'service' or not product.purchase_ok:
                    results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                    'state': 'blocked', 'message': _('Review the shared native service product.')})
                else:
                    results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                    'state': 'missing', 'message': _('A company-specific replacement for the shared service product is missing.')})
                continue
            expense = product.with_company(self).property_account_expense_id
            if product.company_id != self or product.type != 'service' or not product.purchase_ok:
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'blocked', 'message': _('Review the active native service product and its expense account.')})
                continue
            if not product.active:
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'missing', 'message': _('The native service product is inactive.')})
                continue
            if not expense:
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'missing', 'message': _('The native service product expense account is missing.')})
                continue
            if not expense.active or expense.account_type not in ('expense', 'expense_direct_cost', 'expense_depreciation'):
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'blocked', 'message': _('Review the active native service product and its expense account.')})
                continue
            candidates = Native.search([
                ('company_id', 'in', [False, self.id]), ('product_id', '=', product.id),
            ])
            unexpected = candidates - model
            if unexpected:
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'blocked', 'message': _('A product-specific analytic distribution already exists and requires accountant review.')})
                continue
            if not leaf or not model:
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'missing', 'message': _('The 100% employee-service analytic rule is missing.')})
                continue
            if not self._baseer_hr_service_analytic_distribution_is_valid(model, product, leaf):
                results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                                'state': 'blocked', 'message': _('The employee-service analytic rule was changed and requires accountant review.')})
                continue
            results.append({'service_type': service_type, 'product': product, 'leaf': leaf,
                            'model': model, 'state': 'ready', 'message': _('Ready: 100% allocation is expected.')})
        return results

    def _baseer_prepare_hr_service_analytics(self):
        """Add only missing HR service rules for this company, or fail closed."""
        for original in self.sorted('id'):
            company = original.sudo().with_context(
                dict(clean_context(self.env.context), allowed_company_ids=[original.id], active_test=False)
            ).with_company(original)
            if company.parent_id or not company.chart_template or company.currency_id.name != 'SAR':
                raise ValidationError(_('Saudi accounting and SAR are required before employee-service preparation.'))
            company.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
            company.env.cr.execute('UPDATE res_company SET id = id WHERE id = %s', [company.id])
            company.invalidate_recordset()
            before = company._baseer_hr_service_analytic_status()
            blocked = [line for line in before if line['state'] == 'blocked']
            if blocked:
                raise ValidationError(_('Employee-service readiness is blocked: %s', blocked[0]['message']))

            company._baseer_hr_analytic_plan(create=True)
            for leaf_key, _arabic, _english in HR_SERVICE_ANALYTIC_LEAVES:
                company._baseer_hr_analytic_leaf(leaf_key, create=True)
            Native = company.env['account.analytic.distribution.model'].sudo()
            for service_type, _english, _arabic, _purpose in SERVICES[:15]:
                product = company._baseer_service_product((service_type, _english, _arabic, _purpose), {})
                leaf = company._baseer_hr_analytic_leaf(HR_SERVICE_ANALYTIC_MAP[service_type])
                model = company._baseer_hr_service_analytic_model(service_type)
                if model and model.product_id != product:
                    # The old rule remains attached to the legacy shared product
                    # for historical documents. Only a rule pointing elsewhere
                    # is unsafe to replace automatically.
                    if model.product_id.company_id:
                        raise ValidationError(_('The employee-service analytic rule was changed and requires accountant review.'))
                    model = Native
                candidates = Native.with_context(active_test=False).search([
                    ('company_id', 'in', [False, company.id]), ('product_id', '=', product.id),
                ])
                if candidates - model:
                    raise ValidationError(_('A product-specific analytic distribution already exists and requires accountant review.'))
                if not model:
                    model = Native.create({
                        'company_id': company.id, 'product_id': product.id,
                        'sequence': 10, 'analytic_distribution': {str(leaf.id): 100},
                    })
                    model = company._baseer_replace_hr_service_analytic_model(service_type, model)
                if not company._baseer_hr_service_analytic_distribution_is_valid(model, product, leaf):
                    raise ValidationError(_('The employee-service analytic rule was changed and requires accountant review.'))
            after = company._baseer_hr_service_analytic_status()
            if any(line['state'] != 'ready' for line in after):
                raise ValidationError(_('Employee-service analytic preparation did not reach a ready state.'))
        return True

    def _baseer_require_hr_service_analytic_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can prepare employee-service analytic rules.'))

    def action_baseer_open_hr_service_analytic_readiness(self):
        self.ensure_one()
        self._baseer_require_hr_service_analytic_manager()
        return self.env['baseer.hr.service.analytic.readiness']._baseer_open_for_company(self)

    def _baseer_seed_services(self):
        for original in self.sorted('id'):
            if original.parent_id or not original.chart_template or original.currency_id.name != 'SAR':
                continue
            company = original.sudo().with_context(
                dict(clean_context(self.env.context), allowed_company_ids=[original.id], active_test=False)
            ).with_company(original)
            company._baseer_lock_shared_providers()
            company.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
            # MVCC conflict forces concurrent Repeatable Read callers to retry
            # with a fresh snapshot. No business values or write_date are changed.
            company.env.cr.execute('UPDATE res_company SET id = id WHERE id = %s', [company.id])
            company.invalidate_recordset()
            accounts = {}
            for service in SERVICES:
                company._baseer_service_product(service, accounts)
            for provider in PROVIDERS:
                company._baseer_service_provider(provider)
            company._baseer_prepare_hr_service_analytics()

    def _baseer_refresh_onboarding(self, wizard):
        result = super()._baseer_refresh_onboarding(wizard)
        self.ensure_one()
        statuses = self._baseer_hr_service_analytic_status()
        if any(line['state'] == 'blocked' for line in statuses):
            state = 'blocked'
            message = _('خدمات الموظفين تحتاج مراجعة محاسبية قبل الإضافة.')
        elif all(line['state'] == 'ready' for line in statuses):
            state = 'ready'
            message = _('خدمات الموظفين الخمس عشرة وتوزيعها التحليلي جاهزة؛ وتبقى %s خدمة تشغيل عامة و%s مزوداً ضمن البذرة.') % (
                len(SERVICES) - 15, len(PROVIDERS),
            )
        else:
            state = 'missing'
            message = _('ستُجهز خدمات الموظفين الخمس عشرة وتوزيعها التحليلي، مع %s خدمة تشغيل عامة و%s مزوداً، مع الأساس السعودي.') % (
                len(SERVICES) - 15, len(PROVIDERS),
            )
        wizard.write({
            'employee_services_state': state,
            'employee_services_message': message,
            # A dependent feature is expected to be blocked before the Saudi
            # chart exists.  It must not disable the core setup button that
            # clears that prerequisite; a genuinely blocked company (country,
            # currency or branch) still stops the whole wizard.
            'state': 'blocked' if wizard.accounting_state == 'blocked' else
                     'ready' if wizard.accounting_state == 'ready' and state == 'ready' else 'review',
        })
        return result

    def _baseer_preflight_onboarding_apply(self, wizard):
        result = super()._baseer_preflight_onboarding_apply(wizard)
        if wizard.setup_core:
            self._baseer_require_hr_service_analytic_manager()
        return result

    def _baseer_apply_onboarding(self, wizard):
        result = super()._baseer_apply_onboarding(wizard)
        self.ensure_one()
        # The owner approved employee services as a Saudi-company foundation.
        # They are prepared atomically with the core setup, never by a UI-only
        # default, and retain the Accounting Manager safeguard for analytics.
        if wizard.setup_core:
            self._baseer_require_hr_service_analytic_manager()
            self._baseer_seed_services()
        return result

    def _baseer_onboarding_plan_lines(self, wizard):
        lines = super()._baseer_onboarding_plan_lines(wizard)
        statuses = self._baseer_hr_service_analytic_status()
        if all(line['state'] == 'ready' for line in statuses):
            lines.append(_('خدمات الموظفين والتوزيع التحليلي: جاهزة، ولن يعاد إنشاؤها.'))
        elif any(line['state'] == 'blocked' for line in statuses):
            lines.append(_('خدمات الموظفين والتوزيع التحليلي: متوقفة وتحتاج مراجعة محاسبية.'))
        else:
            lines.append(_('خدمات الموظفين والتوزيع التحليلي: ستُضاف مع المرحلة الأساسية.'))
        return lines
