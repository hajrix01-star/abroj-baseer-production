"""Explicit company-onboarding choices for Baseer sales summaries."""
from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


SUMMARY_METHODS = (
    ('cash', 'نقدي'),
    ('bank', 'بنك / بطاقة / تحويل'),
    ('hungerstation', 'هنقرستيشن'),
    ('keeta', 'كيتا'),
    ('jahez', 'جاهز'),
)


class BaseerCompanyOnboarding(models.TransientModel):
    _inherit = 'baseer.company.onboarding'

    sales_mode = fields.Selection([
        ('none', 'لا نستخدم تسجيل مبيعات الآن'),
        ('summary', 'ملخصات المبيعات الخارجية'),
        ('direct_pos', 'نقطة بيع مباشرة'),
    ], string='أسلوب المبيعات', default='none')
    setup_summary_cash = fields.Boolean(string='نقدي')
    setup_summary_bank = fields.Boolean(string='بنك / بطاقة / تحويل')
    setup_summary_hungerstation = fields.Boolean(string='هنقرستيشن')
    setup_summary_keeta = fields.Boolean(string='كيتا')
    setup_summary_jahez = fields.Boolean(string='جاهز')
    sales_summary_state = fields.Selection([
        ('not_selected', 'غير مختار'),
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة ملخصات المبيعات', readonly=True)
    sales_summary_message = fields.Char(readonly=True)
    direct_pos_state = fields.Selection([
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة نقطة البيع المباشرة', readonly=True)
    direct_pos_message = fields.Char(readonly=True)

    def _baseer_selected_summary_methods(self):
        self.ensure_one()
        return {
            key for key, _label in SUMMARY_METHODS
            if self[f'setup_summary_{key}']
        }

    def action_open_direct_pos_settings(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('مدير نقطة البيع فقط يمكنه إعداد نقطة البيع المباشرة.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('نقطة البيع المباشرة'),
            'res_model': 'pos.config',
            'view_mode': 'kanban,list,form',
            'domain': [('company_id', '=', self.company_id.id), ('baseer_summary_only', '=', False)],
            'context': {
                'default_company_id': self.company_id.id,
                'allowed_company_ids': [self.company_id.id],
            },
        }


class Company(models.Model):
    _inherit = 'res.company'

    def _baseer_summary_onboarding_status(self):
        self.ensure_one()
        if self.parent_id or self.chart_template != 'sa' or self.currency_id.name != 'SAR':
            return 'blocked', _('أكمل الحسابات السعودية والريال السعودي قبل ضبط ملخصات المبيعات.')
        company = self.sudo().with_context(
            allowed_company_ids=[self.id], active_test=False
        ).with_company(self)
        config = company.env['pos.config'].search([
            ('company_id', '=', self.id), ('baseer_summary_only', '=', True)], limit=1)
        owned = company._baseer_pos_identity('config', 'pos.config')
        if config and config != owned:
            return 'blocked', _('يوجد ملخص مبيعات سابق يحتاج مراجعة قبل أن تعدله النافذة.')
        if not config:
            return 'missing', _('اختر فقط طرق التحصيل التي تستخدمها؛ لا تُضاف تطبيقات تلقائياً.')
        if not config.active:
            return 'blocked', _('ملخص المبيعات مؤرشف؛ راجعه من إعدادات ملخصات المبيعات.')
        try:
            config._validate_baseer_setup()
        except ValidationError as error:
            return 'blocked', error.args[0]
        return 'ready', _('ملخصات المبيعات وطرق التحصيل المختارة جاهزة.')

    def _baseer_direct_pos_onboarding_status(self):
        self.ensure_one()
        company = self.sudo().with_context(
            allowed_company_ids=[self.id], active_test=False
        ).with_company(self)
        configs = company.env['pos.config'].search([
            ('company_id', '=', self.id), ('baseer_summary_only', '=', False)], order='active desc, id')
        if not configs:
            return 'missing', _('لم تُنشأ نقطة بيع مباشرة بعد.')
        if not configs.filtered('active'):
            return 'blocked', _('كل نقاط البيع المباشرة مؤرشفة؛ راجع إعدادات نقطة البيع.')
        return 'ready', _('نقطة البيع المباشرة جاهزة؛ تضبط وسائلها التفصيلية من إعداداتها الأصلية.')

    def _baseer_refresh_onboarding(self, wizard):
        result = super()._baseer_refresh_onboarding(wizard)
        state, message = self._baseer_summary_onboarding_status()
        if wizard.sales_mode == 'none':
            state, message = 'not_selected', _('لم تُختر ملخصات المبيعات؛ لن يُنشأ أي إعداد تحصيل.')
        direct_state, direct_message = self._baseer_direct_pos_onboarding_status()
        wizard.write({
            'sales_summary_state': state,
            'sales_summary_message': message,
            'direct_pos_state': direct_state,
            'direct_pos_message': direct_message,
        })
        return result

    def _baseer_apply_onboarding(self, wizard):
        result = super()._baseer_apply_onboarding(wizard)
        if wizard.sales_mode == 'none':
            return result
        if not self.env.user.has_group('point_of_sale.group_pos_manager'):
            raise AccessError(_('مدير نقطة البيع فقط يمكنه إعداد نقطة البيع أو ملخصات المبيعات.'))
        if wizard.sales_mode == 'direct_pos':
            company = self.sudo().with_context(
                allowed_company_ids=[self.id], active_test=False
            ).with_company(self)
            configs = company.env['pos.config'].search([
                ('company_id', '=', self.id), ('baseer_summary_only', '=', False)], limit=1)
            if not configs:
                company.env['pos.config'].create({
                    'name': _('نقطة البيع الرئيسية'), 'company_id': self.id,
                })
            return result
        selected = wizard._baseer_selected_summary_methods()
        if not selected:
            raise ValidationError(_('اختر طريقة تحصيل واحدة على الأقل لملخصات المبيعات.'))
        self._baseer_apply_summary_payment_choices(selected)
        return result

    def _baseer_onboarding_plan_lines(self, wizard):
        lines = super()._baseer_onboarding_plan_lines(wizard)
        if wizard.sales_mode == 'none':
            lines.append(_('المبيعات والتحصيل: لا اختيار؛ لن يُنشأ إعداد مبيعات.'))
        elif wizard.sales_mode == 'direct_pos':
            lines.append(_('المبيعات والتحصيل: ستُجهز نقطة البيع الرئيسية فقط؛ وسائلها التفصيلية من إعدادات Odoo الأصلية.'))
        else:
            labels = dict(SUMMARY_METHODS)
            selected = [labels[key] for key, _label in SUMMARY_METHODS
                        if key in wizard._baseer_selected_summary_methods()]
            if selected:
                lines.append(_('ملخصات المبيعات: ستُضاف طرق التحصيل المختارة فقط: %s.') % '، '.join(selected))
            else:
                lines.append(_('ملخصات المبيعات: لم تختر طريقة تحصيل بعد.'))
        return lines
