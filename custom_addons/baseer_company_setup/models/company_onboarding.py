"""Explicit, company-scoped readiness check for Saudi company setup."""
from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError

from .company import ACCOUNT_DEFAULTS


class BaseerCompanyOnboarding(models.TransientModel):
    _name = 'baseer.company.onboarding'
    _description = 'Baseer Company Onboarding'

    company_id = fields.Many2one('res.company', string='الشركة', required=True, readonly=True, ondelete='cascade')
    state = fields.Selection([
        ('review', 'يحتاج مراجعة'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], required=True, default='review', readonly=True)
    summary = fields.Text(readonly=True)
    setup_core = fields.Boolean(string='الحسابات السعودية والدفاتر الأساسية', default=True)
    setup_configuration_loaded = fields.Boolean(
        default=False,
        help='Technical guard: load the current company setup once without overwriting a choice made in this wizard.',
    )
    setup_step = fields.Selection([
        ('foundation', '1. الأساس والخدمات'),
        ('sales', '2. المبيعات والتحصيل'),
        ('operations', '3. التشغيل والعهدة'),
        ('review', '4. المراجعة والتطبيق'),
    ], string='مرحلة التهيئة', required=True, default='foundation')
    plan_preview = fields.Text(string='ملخص ما سيجري', readonly=True)
    accounting_state = fields.Selection([
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة الحسابات', readonly=True)
    accounting_message = fields.Char(readonly=True)
    setup_payroll_analytics = fields.Boolean(string='تجهيز التحليل الافتراضي للرواتب', default=False)
    payroll_analytics_state = fields.Selection([
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('disabled', 'متوقف'),
        ('blocked', 'متوقف'),
    ], string='حالة تحليل الرواتب', readonly=True)
    payroll_analytics_message = fields.Char(readonly=True)

    @classmethod
    def _baseer_open_for_company(cls, company):
        company._baseer_require_onboarding_manager()
        wizard = company.env[cls._name].create({'company_id': company.id})
        wizard.action_refresh()
        return {
            'type': 'ir.actions.act_window',
            'name': _('تهيئة الشركة'),
            'res_model': cls._name,
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _require_manager(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('مديرو ERP فقط يمكنهم فحص أو تطبيق تهيئة الشركة.'))
        for wizard in self:
            wizard.company_id._baseer_require_onboarding_manager()

    def action_refresh(self):
        self._require_manager()
        for wizard in self:
            wizard.company_id._baseer_refresh_onboarding(wizard)
            wizard.plan_preview = wizard.company_id._baseer_onboarding_plan_preview(wizard)
            # Extension hooks use this one-time marker to prefill the current
            # company configuration on opening. Later refreshes must preserve
            # the manager's explicit transient choices.
            wizard.setup_configuration_loaded = True
        return True

    def _baseer_reopen(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('تهيئة الشركة'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_next_step(self):
        self._require_manager()
        steps = ('foundation', 'sales', 'operations', 'review')
        self.action_refresh()
        for wizard in self:
            wizard.setup_step = steps[min(steps.index(wizard.setup_step) + 1, len(steps) - 1)]
        return self._baseer_reopen()

    def action_previous_step(self):
        self._require_manager()
        steps = ('foundation', 'sales', 'operations', 'review')
        for wizard in self:
            wizard.setup_step = steps[max(steps.index(wizard.setup_step) - 1, 0)]
        return self._baseer_reopen()

    def action_apply_selected(self):
        self._require_manager()
        # Check every selected stage before the first write. This preserves the
        # single Odoo transaction and avoids discovering a missing role after a
        # preceding extension has already prepared master data.
        for wizard in self:
            wizard.company_id._baseer_preflight_onboarding_apply(wizard)
        for wizard in self:
            wizard.company_id._baseer_apply_onboarding(wizard)
        self.action_refresh()
        self.setup_step = 'review'
        return self._baseer_reopen()


class Company(models.Model):
    _inherit = 'res.company'

    def _baseer_require_onboarding_manager(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('مديرو ERP فقط يمكنهم فحص أو تطبيق تهيئة الشركة.'))
        # A manager can open setup from the company administration list even
        # when a different company is active in this browser session.  The
        # durable authority is the user's assigned companies, not the
        # transient ``allowed_company_ids`` request context.
        if self not in self.env.user.company_ids:
            raise AccessError(_('لا يمكنك تهيئة شركة غير مُعيّنة لحسابك.'))

    def _baseer_preflight_onboarding_apply(self, wizard):
        """Extension point for stage roles; it must not write data."""
        self.ensure_one()
        if wizard.setup_payroll_analytics:
            state, message = self._baseer_payroll_analytic_status()
            # Missing Saudi accounting is allowed when this same apply action
            # also prepares the foundational company accounting first.
            if state == 'blocked':
                raise ValidationError(message)
        return True

    def action_baseer_open_onboarding(self):
        self.ensure_one()
        return self.env['baseer.company.onboarding']._baseer_open_for_company(self)

    def _baseer_onboarding_accounting_status(self):
        self.ensure_one()
        # A manager may open the selected company's setup while another
        # company is active. Read only this company-owned accounting setup in
        # its own allowed-company context; never broaden the user's records.
        company = self.sudo().with_context(allowed_company_ids=[self.id], active_test=False).with_company(self)
        if company.parent_id:
            return 'blocked', _('الفرع يستخدم حسابات الشركة الأم ولا يأخذ تهيئة مستقلة.')
        saudi = company.env.ref('base.sa')
        sar = company.env.ref('base.SAR')
        if company.country_id and company.country_id != saudi:
            return 'blocked', _('هذه الشركة ليست مضبوطة على المملكة العربية السعودية.')
        if company.currency_id and company.currency_id != sar:
            return 'blocked', _('عملة هذه الشركة ليست الريال السعودي.')
        if company.chart_template != 'sa':
            return 'missing', _('الشجرة السعودية والدفاتر الأساسية غير جاهزة.')
        missing = [field for field, *_definition in ACCOUNT_DEFAULTS if not company[field]]
        if missing or not company.baseer_payroll_journal_id or not company.baseer_eos_journal_id:
            return 'missing', _('بعض إعدادات الرواتب أو الدفاتر الأساسية ناقصة.')
        starter_types = ('sale', 'purchase', 'bank', 'cash')
        missing_starters = [journal_type for journal_type in starter_types if not company.env['account.journal'].search_count([
            ('company_id', '=', company.id), ('type', '=', journal_type), ('active', '=', True),
        ], limit=1)]
        if missing_starters:
            return 'missing', _('دفاتر البيع أو الشراء أو البنك أو النقد الأساسية ناقصة أو مؤرشفة.')
        return 'ready', _('الشجرة السعودية والدفاتر الأساسية جاهزة.')

    def _baseer_refresh_onboarding(self, wizard):
        self.ensure_one()
        state, message = self._baseer_onboarding_accounting_status()
        wizard.write({
            'accounting_state': state,
            'accounting_message': message,
            'state': 'ready' if state == 'ready' else 'blocked' if state == 'blocked' else 'review',
            'summary': message,
        })
        analytics_state, analytics_message = self._baseer_payroll_analytic_status()
        values = {
            'payroll_analytics_state': analytics_state,
            'payroll_analytics_message': analytics_message,
        }
        if not wizard.setup_configuration_loaded:
            values['setup_payroll_analytics'] = analytics_state == 'missing'
        wizard.write(values)
        return True

    def _baseer_onboarding_plan_lines(self, wizard):
        """Return the server-authoritative preview for the selected company."""
        self.ensure_one()
        if wizard.accounting_state == 'ready':
            lines = [_('الأساس السعودي والدفاتر الأساسية: جاهزة، ولن يعاد إنشاؤها.')]
        elif wizard.accounting_state == 'blocked':
            lines = [_('الأساس السعودي والدفاتر الأساسية: متوقف حتى تُصحح بيانات الشركة.')]
        else:
            lines = [_('الأساس السعودي والدفاتر الأساسية: سيُضاف الناقص للشركة الحالية فقط.')]
        if wizard.setup_payroll_analytics:
            lines.append(_('تحليل الرواتب: سيُجهّز الحساب التحليلي الناقص فقط للمسيرات الجديدة؛ لا تتغير المسيرات أو القيود السابقة.'))
        elif wizard.payroll_analytics_state == 'ready':
            lines.append(_('تحليل الرواتب: جاهز، ولن يعاد إنشاؤه.'))
        elif wizard.payroll_analytics_state == 'disabled':
            lines.append(_('تحليل الرواتب: الحساب جاهز لكن التوزيع التلقائي متوقف.'))
        return lines

    def _baseer_onboarding_plan_preview(self, wizard):
        self.ensure_one()
        return '\n'.join(self._baseer_onboarding_plan_lines(wizard))

    def _baseer_apply_onboarding(self, wizard):
        self.ensure_one()
        if not wizard.setup_core:
            return True
        state, message = self._baseer_onboarding_accounting_status()
        if state == 'blocked':
            raise ValidationError(message)
        if self.chart_template != 'sa':
            self.action_baseer_initialize_saudi_accounting()
        else:
            self._baseer_prepare_company_accounting()
        if wizard.setup_payroll_analytics:
            self._baseer_prepare_payroll_analytics()
        return True
