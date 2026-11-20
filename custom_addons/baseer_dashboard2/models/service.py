import calendar
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

FORBIDDEN_COMPANY_IDS = {54, 56}
SOURCES = {
    'sales_net': 'المبيعات دون الضريبة: رصيد الدائن مطروحاً منه المدين للحسابات المصنفة مبيعات؛ account.move.line المرحّلة حسب التاريخ والشركة.',
    'expenses': 'المصاريف: المدين مطروحاً منه الدائن حسب تصنيف الحساب؛ account.move.line المرحّلة.',
    'profit': 'مجمل الربح = المبيعات − تكلفة الأكل؛ التشغيلي يطرح المصاريف التشغيلية؛ الصافي يضيف الإيرادات الأخرى ويطرح الزكاة والضريبة.',
    'ratios': 'النسب تقسم تكلفة الأكل والرواتب ومجموعهما وصافي الربح على المبيعات دون الضريبة.',
    'breakeven': 'التعادل = التكاليف الثابتة ÷ (١ − نسبة التكاليف المتغيرة)؛ الثابتة الرواتب والإيجار والخدمات والإهلاك.',
    'purchases': 'المشتريات: فواتير الموردين المرحّلة ناقص المرتجعات حسب تاريخ الفاتورة؛ account.move.',
    'gross_sales_by_channel': 'المبيعات شاملة الضريبة حسب اليوم والقناة من pos.payment أو الملخصات اليومية المرحّلة؛ لا يجمع المصدران لليوم نفسه.',
    'apps': 'التطبيقات: مجموع المبيعات الإجمالية للقنوات المصنفة تطبيقات.',
    'apps_unreceived': 'التطبيقات غير المستلمة حتى اليوم: المتبقي على حسابات الذمم ذات الصلة؛ account.move.line.',
    'customers': 'عدد العملاء هو صافي عدد طلبات pos.order المدفوعة أو المكتملة أو المفوترة؛ غير متاح لأيام الملخصات اليومية.',
    'hours': 'الساعات: عدد الطلبات وإجماليها حسب اليوم والساعة المحلية؛ pos.order.',
    'inout': 'الداخل مبيعات القنوات شاملة الضريبة؛ الخارج أرصدة السيولة الدائنة المدفوعة فعلياً دون التحويلات الداخلية؛ account.move.line.',
    'unpaid_bills': 'فواتير الموردين غير المسددة رصيد حتى اليوم ولا تدخل في الخارج؛ account.move.',
    'timeline': 'المسار الزمني: المبيعات دون الضريبة حسب الشهر أو السنة؛ account.move.line المرحّلة.',
    'heatmap': 'التقويم: المبيعات اليومية والعملاء والمناسبات بحسب الشركة والتاريخ؛ pos.order وaccount.move وbaseer.dashboard2.event.',
}

# Category sources share the same posted-entry domain and debit/credit basis.
for _key, _label in {
    'food_cost': 'تكلفة الأكل', 'salaries': 'الرواتب', 'rent': 'الإيجار',
    'utilities': 'الخدمات', 'marketing': 'التسويق', 'commissions': 'العمولات',
    'other_opex': 'المصاريف التشغيلية الأخرى', 'depreciation': 'الإهلاك',
    'zakat_tax': 'الزكاة والضريبة',
}.items():
    SOURCES[_key] = '%s: المدين ناقص الدائن؛ account.move.line المرحّلة للحسابات المصنفة ضمن الفئة في الفترة والشركات المحددة.' % _label
SOURCES.update({
    'other_income': 'الإيرادات الأخرى: الدائن ناقص المدين؛ account.move.line المرحّلة على حسابات الإيرادات الأخرى.',
    'gross_profit': 'مجمل الربح: المبيعات دون الضريبة ناقص تكلفة الأكل؛ account.move.line المرحّلة.',
    'operating_profit': 'الربح التشغيلي: مجمل الربح ناقص المصاريف التشغيلية والإهلاك؛ account.move.line المرحّلة.',
    'net_profit': 'صافي الربح: الربح التشغيلي زائد الإيرادات الأخرى ناقص الزكاة والضريبة؛ account.move.line المرحّلة.',
    'sales_vat': 'ضريبة المبيعات: صافي دائن حسابات ضريبة المبيعات على الملخصات اليومية أو نقاط البيع المرحّلة في الفترة؛ account.move.line.',
})



class DashboardService(models.AbstractModel):
    _name = 'baseer.dashboard2.service'
    _description = 'Dashboard data service'

    def _check_reader(self):
        if not self.env.user.has_group('account.group_account_readonly') and not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('You cannot access this dashboard.'))

    def _companies(self):
        self._check_reader()
        # The private system-parameter accessor reads this fixed key without granting
        # users access to the rest of ir.config_parameter.
        raw = self.env['ir.config_parameter']._get_param('baseer_dashboard2.company_map') or '1:أرز,2:الشامي,3:الدوحة'
        allowed = set(self.env.user.company_ids.ids) - FORBIDDEN_COMPANY_IDS
        pairs = []
        for item in raw.split(','):
            number, sep, label = item.partition(':')
            if sep and number.strip().isdigit() and label.strip():
                cid = int(number.strip())
                if cid in allowed and cid not in [p[0] for p in pairs]:
                    pairs.append((cid, label.strip()))
        existing = self.env['res.company'].browse([p[0] for p in pairs]).exists()
        return [(cid, label, existing.browse(cid).name) for cid, label in pairs if cid in existing.ids]

    def _scope(self, key):
        companies = self._companies()
        ids = [c[0] for c in companies]
        if key == 'all' and len(ids) >= 2:
            return ids
        if str(key).isdigit() and int(key) in ids:
            return [int(key)]
        raise AccessError(_('The selected company is not available.'))

    @api.model
    def get_meta(self):
        companies = self._companies()
        ids = [c[0] for c in companies]
        options = [{'key': str(cid), 'id': cid, 'label': label, 'name': name} for cid, label, name in companies]
        if len(ids) >= 2:
            options.append({'key': 'all', 'label': 'المجموع'})
        months, last = [], False
        if ids:
            lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
            domain = [('company_id', 'in', ids), ('parent_state', '=', 'posted')]
            rows = lines._read_group(domain, ['date:month'], ['date:max'], order='date:month DESC', limit=36)
            months = [fields.Date.to_string(row[0])[:7] for row in rows if row[0]]
            last = max((row[1] for row in rows if row[1]), default=False)
        today = fields.Date.context_today(self)
        previous_month = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
        default_month = next((month for month in months if month <= previous_month), previous_month)
        return {'default_month': default_month, 'companies': options, 'default_company_key': str(self.env.company.id if self.env.company.id in ids else ids[0]) if ids else False,
                'months_available': months, 'today': fields.Date.to_string(fields.Date.context_today(self)),
                'last_data_date': fields.Date.to_string(last) if last else False,
                'can_edit': self.env.user.has_group('account.group_account_manager'), 'tz': self.env.user.tz or 'Asia/Riyadh',
                'currency_symbol': 'ر.س', 'flags': {'empty_scope': not bool(ids)}}

    def _period(self, period):
        try:
            if period.get('mode') == 'month':
                start = date.fromisoformat(period['month'] + '-01')
                end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
            elif period.get('mode') == 'range':
                start, end = date.fromisoformat(period['date_from']), date.fromisoformat(period['date_to'])
            else:
                raise ValueError()
            if end < start:
                raise ValueError()
            return start, end
        except (ValueError, KeyError, TypeError):
            raise UserError(_('Invalid dashboard period.'))

    def _category(self, account, categories):
        code = account.code or ''
        for category in categories:
            if any(code.startswith(prefix.strip()) for prefix in (category.account_code_prefixes or '').split(',') if prefix.strip()):
                return category.code
        for category in categories:
            if account.account_type in [v.strip() for v in (category.account_type_fallback or '').split(',') if v.strip()]:
                return category.code
        return 'other_opex' if (account.account_type or '').startswith('expense') else False

    def _accounting(self, ids, start, end):
        categories = self.env['baseer.dashboard2.category'].with_context(allowed_company_ids=ids).search([])
        lines = self.env['account.move.line'].with_context(allowed_company_ids=ids)
        rows = lines._read_group([('company_id', 'in', ids), ('parent_state', '=', 'posted'), ('date', '>=', start), ('date', '<=', end)], ['company_id', 'account_id'], ['debit:sum', 'credit:sum'])
        totals = {cat.code: 0.0 for cat in categories}
        accounts = []
        arabic_lang = 'ar_001' if self.env['res.lang']._get_data(code='ar_001').code else self.env.lang
        for company, account, debit, credit in rows:
            account = account.with_company(company)
            key = self._category(account, categories)
            if key:
                amount = (credit - debit) if key in ('revenue', 'other_income') else (debit - credit)
                totals[key] = totals.get(key, 0.0) + amount
                accounts.append({'company_id': company.id, 'account_id': account.id, 'code': account.code, 'name': account.with_context(lang=arabic_lang).name or account.name, 'category': key, 'amount': round(amount, 2)})
        sales = totals.get('revenue', 0.0)
        gross = sales - totals.get('food_cost', 0.0)
        operating = gross - sum(totals.get(k, 0.0) for k in ('salaries', 'rent', 'utilities', 'marketing', 'commissions', 'other_opex', 'depreciation'))
        net = operating + totals.get('other_income', 0.0) - totals.get('zakat_tax', 0.0)
        fixed = sum(totals.get(k, 0.0) for k in ('salaries', 'rent', 'utilities', 'depreciation'))
        variable = sum(totals.get(k, 0.0) for k in ('food_cost', 'commissions', 'marketing', 'other_opex'))
        breakeven = fixed / (1 - variable / sales) if sales and variable / sales < 1 else None
        return {'available': True, 'categories': {k: round(v, 2) for k, v in totals.items()}, 'accounts': accounts,
                'sales_net': round(sales, 2), 'gross_profit': round(gross, 2), 'operating_profit': round(operating, 2), 'net_profit': round(net, 2),
                'breakeven': round(breakeven, 2) if breakeven is not None else None,
                'safety_margin': round(sales - breakeven, 2) if breakeven is not None else None,
                'fixed_costs': round(fixed, 2), 'variable_ratio_pct': round(variable / sales * 100, 2) if sales else None,
                'ratios': {k: round(v / sales * 100, 2) if sales else None for k, v in {
                    'food_pct': totals.get('food_cost', 0), 'salaries_pct': totals.get('salaries', 0),
                    'prime_pct': totals.get('food_cost', 0) + totals.get('salaries', 0), 'net_margin_pct': net}.items()}}

    @api.model
    def save_target(self, company_key, key, value):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can edit targets.'))
        ids = self._scope(company_key)
        if key not in ('food_pct', 'salaries_pct', 'prime_pct', 'net_margin_pct'):
            raise UserError(_('Unknown target.'))
        try:
            value = float(value)
            if not 0 <= value <= 100:
                raise ValueError()
        except (ValueError, TypeError):
            raise UserError(_('Invalid target value.'))
        company_id = False if company_key == 'all' else ids[0]
        model = self.env['baseer.dashboard2.target'].with_context(allowed_company_ids=ids)
        target = model.search([('company_id', '=', company_id), ('key', '=', key)], limit=1)
        vals = {'value': value, 'operator': 'ge' if key == 'net_margin_pct' else 'le'}
        if target:
            target.write(vals)
        else:
            model.create(dict(vals, company_id=company_id, key=key))
        return True
