"""Explicit stock and representative-custody setup choices per company."""
from odoo import _, Command, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerCompanyOnboarding(models.TransientModel):
    _inherit = 'baseer.company.onboarding'

    procurement_stock_mode = fields.Selection([
        ('none', 'لا نحتاج مخزون الآن'),
        ('single', 'مستودع واحد داخل المنشأة'),
        ('multiple', 'أكثر من مستودع'),
    ], string='المخزون وطلبات الشراء', default='none')
    setup_main_warehouse = fields.Boolean(string='إنشاء المستودع الرئيسي إن لم يوجد')
    procurement_warehouse_id = fields.Many2one(
        'stock.warehouse', string='مستودع طلبات الشراء', check_company=True,
        domain="[('company_id', '=', company_id)]",
    )
    procurement_stock_state = fields.Selection([
        ('not_selected', 'غير مختار'),
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة المخزون', readonly=True)
    procurement_stock_message = fields.Char(readonly=True)

    setup_representative_petty_cash = fields.Boolean(string='عهدة مندوبي المشتريات')
    representative_petty_cash_payment_journal_ids = fields.Many2many(
        'account.journal', string='نقاط دفع العهدة', check_company=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ['bank', 'cash']), ('active', '=', True)]",
    )
    representative_petty_cash_state = fields.Selection([
        ('not_selected', 'غير مختار'),
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة العهدة', readonly=True)
    representative_petty_cash_message = fields.Char(readonly=True)


class Company(models.Model):
    _inherit = 'res.company'

    def _baseer_procurement_warehouses(self):
        self.ensure_one()
        return self.env['stock.warehouse'].with_context(active_test=False).search([
            ('company_id', '=', self.id), ('active', '=', True),
        ], order='id')

    def _baseer_procurement_stock_status(self):
        self.ensure_one()
        warehouses = self._baseer_procurement_warehouses()
        default = self.baseer_procurement_default_warehouse_id
        if default and default not in warehouses:
            return 'blocked', _('مستودع طلبات الشراء الافتراضي مؤرشف أو تابع لشركة أخرى.')
        if not warehouses:
            return 'missing', _('لا يوجد مستودع. يمكن إنشاء مستودع رئيسي واحد من هذه النافذة.')
        if default:
            return 'ready', _('مستودع طلبات الشراء الافتراضي جاهز.')
        if len(warehouses) == 1:
            return 'missing', _('يوجد مستودع واحد؛ اختره ليكون افتراضياً لطلبات الشراء.')
        return 'missing', _('يوجد أكثر من مستودع؛ اختر مستودع طلبات الشراء الافتراضي.')

    def _baseer_representative_petty_cash_onboarding_status(self):
        self.ensure_one()
        # The setup wizard can target a company other than the one active in
        # the session. Inspect only that target's configuration, under sudo,
        # so account record rules do not turn a read-only preview into a
        # multi-company access error.
        company = self.sudo().with_context(allowed_company_ids=[self.id], active_test=False).with_company(self)
        account = company.baseer_procurement_representative_petty_cash_account_id
        journal = company.baseer_procurement_representative_petty_cash_journal_id
        if bool(account) != bool(journal):
            return 'blocked', _('إعداد العهدة الحالي غير مكتمل؛ راجع الحساب والدفتر قبل المتابعة.')
        issue = company._baseer_representative_petty_cash_setup_issue()
        if issue:
            return 'missing', _('لم تُنشأ بعد حسابات العهدة المشتركة.')
        if not company._baseer_representative_petty_cash_payment_points():
            return 'missing', _('اختر نقطة دفع نقدية أو بنكية واحدة على الأقل للعهدة.')
        return 'ready', _('حساب العهدة ودفترها ونقاط الدفع المختارة جاهزة.')

    def _baseer_refresh_onboarding(self, wizard):
        result = super()._baseer_refresh_onboarding(wizard)
        stock_state, stock_message = self._baseer_procurement_stock_status()
        warehouses = self._baseer_procurement_warehouses()
        if wizard.procurement_stock_mode == 'none':
            stock_state, stock_message = 'not_selected', _('لم يُختر المخزون؛ لن تُغيّر النافذة إعدادات المستودعات.')
        elif not wizard.procurement_warehouse_id and len(warehouses) == 1:
            wizard.procurement_warehouse_id = warehouses
        custody_state, custody_message = self._baseer_representative_petty_cash_onboarding_status()
        if not wizard.setup_representative_petty_cash:
            custody_state, custody_message = 'not_selected', _('لم تُختر العهدة؛ لن يُنشأ حساب أو دفتر أو نقطة دفع.')
        wizard.write({
            'procurement_stock_state': stock_state,
            'procurement_stock_message': stock_message,
            'representative_petty_cash_state': custody_state,
            'representative_petty_cash_message': custody_message,
        })
        return result

    def _baseer_create_main_procurement_warehouse(self):
        self.ensure_one()
        warehouses = self._baseer_procurement_warehouses()
        if warehouses:
            return warehouses
        codes = set(self.env['stock.warehouse'].with_context(active_test=False).search([]).mapped('code'))
        code = next((candidate for candidate in ('MAIN', 'MWH', 'WH') if candidate not in codes), False)
        if not code:
            raise ValidationError(_('تعذر اختيار رمز فريد للمستودع الرئيسي. أنشئه من المخزون ثم اختره هنا.'))
        return self.env['stock.warehouse'].with_company(self).create({
            'name': _('المستودع الرئيسي'), 'code': code, 'company_id': self.id,
        })

    def _baseer_apply_onboarding(self, wizard):
        result = super()._baseer_apply_onboarding(wizard)
        if wizard.procurement_stock_mode != 'none':
            if not self.env.user.has_group('stock.group_stock_manager'):
                raise AccessError(_('مدير المخزون فقط يمكنه إعداد مستودع طلبات الشراء.'))
            warehouses = self._baseer_procurement_warehouses()
            selected = wizard.procurement_warehouse_id
            if not warehouses and wizard.setup_main_warehouse:
                selected = self._baseer_create_main_procurement_warehouse()
            elif not selected and len(warehouses) == 1:
                selected = warehouses
            if not selected:
                raise ValidationError(_('اختر مستودع طلبات الشراء أو فعّل إنشاء المستودع الرئيسي.'))
            if selected.company_id != self or not selected.active:
                raise ValidationError(_('اختر مستودعاً نشطاً تابعاً للشركة الحالية.'))
            self.write({'baseer_procurement_default_warehouse_id': selected.id})
        if wizard.setup_representative_petty_cash:
            if not self.env.user.has_group('base.group_erp_manager'):
                raise AccessError(_('مدير ERP فقط يمكنه إعداد حساب ودفتر عهدة مندوبي المشتريات.'))
            payment_points = wizard.representative_petty_cash_payment_journal_ids
            if not payment_points:
                raise ValidationError(_('اختر نقطة دفع نقدية أو بنكية واحدة على الأقل للعهدة.'))
            invalid = payment_points.filtered(lambda journal: (
                journal.company_id != self or not journal.active or journal.type not in ('bank', 'cash')
                or not journal.default_account_id or journal.default_account_id.account_type != 'asset_cash'
            ))
            if invalid:
                raise ValidationError(_('نقطة دفع العهدة يجب أن تكون نقداً أو بنكاً نشطاً من الشركة الحالية.'))
            self._baseer_ensure_representative_petty_cash_setup(
                require_chart=True, raise_on_missing_chart=True,
            )
            self.write({'baseer_procurement_representative_petty_cash_payment_journal_ids': [
                Command.set(payment_points.ids),
            ]})
        return result

    def _baseer_onboarding_plan_lines(self, wizard):
        lines = super()._baseer_onboarding_plan_lines(wizard)
        if wizard.procurement_stock_mode == 'none':
            lines.append(_('المخزون وطلبات الشراء: لا اختيار؛ لن تتغير المستودعات.'))
        elif wizard.procurement_warehouse_id:
            lines.append(_('المخزون وطلبات الشراء: سيُستخدم «%s» مستودعاً افتراضياً.') %
                         wizard.procurement_warehouse_id.display_name)
        elif wizard.setup_main_warehouse:
            lines.append(_('المخزون وطلبات الشراء: سيُنشأ المستودع الرئيسي عند عدم وجود مستودع.'))
        else:
            lines.append(_('المخزون وطلبات الشراء: يحتاج اختيار مستودع أو إنشاء المستودع الرئيسي.'))
        if wizard.setup_representative_petty_cash:
            points = wizard.representative_petty_cash_payment_journal_ids
            if points:
                lines.append(_('عهدة مندوبي المشتريات: سيُربط حساب ودفتر العهدة بنقاط الدفع المختارة فقط.'))
            else:
                lines.append(_('عهدة مندوبي المشتريات: تحتاج اختيار نقطة دفع نقدية أو بنكية.'))
        else:
            lines.append(_('عهدة مندوبي المشتريات: لا اختيار؛ لن تُضاف نقطة دفع للعهدة.'))
        return lines
