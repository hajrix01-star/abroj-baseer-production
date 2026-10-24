"""Read-only toolbar journeys on synthetic accounts; no performance SLA claim."""

from odoo import Command
from odoo.tests.common import HttpCase, tagged


@tagged('post_install', '-at_install', 'operations_browser', 'reports_toolbar_browser')
class TestReportToolbarBrowser(HttpCase):
    browser_size = '1280x812'

    def _check_toolbars(self, lang):
        self.env['res.lang']._activate_lang(lang)
        reader = self.env['res.users'].create({
            'name': 'Synthetic toolbar reader', 'login': 'toolbar.' + lang,
            'password': 'toolbar.test', 'lang': lang,
            'company_id': self.env.company.id,
            'company_ids': [Command.set(self.env.company.ids)],
            'group_ids': [Command.set([
                self.env.ref('base.group_user').id,
                self.env.ref('account.group_account_readonly').id,
                self.env.ref('point_of_sale.group_pos_user').id,
            ])],
        })
        self.env.flush_all()
        script = r"""
        (async () => {
            const visible = el => el && el.getClientRects().length > 0;
            const waitFor = async (predicate, description) => {
                const deadline = performance.now() + 20000;
                while (performance.now() < deadline) {
                    const result = predicate();
                    if (result) { return result; }
                    await new Promise(resolve => setTimeout(resolve, 25));
                }
                throw new Error('Toolbar timeout: ' + description);
            };
            const reportTitles = new Set([
                'تقرير ضريبة القيمة المضافة', 'Saudi VAT Report',
                'كشف رسوم التبغ من نقاط البيع', 'POS Tobacco Fee Register',
                'حركة حساب', 'Account Activity', 'الربح والخسارة', 'Profit and Loss',
                'ملخص المبيعات والمدفوعات', 'Sales and Payments Summary',
                'دفتر الأستاذ العام', 'General Ledger', 'ميزان المراجعة', 'Trial Balance',
                'الميزانية العمومية', 'Balance Sheet', 'أعمار الذمم المدينة', 'Aged Receivables',
                'مديونيات الموردين', 'Aged Payables',
            ]);
            const switcher = () => [...document.querySelectorAll('.o_baseer_reports_hub_body .o_baseer_report_switcher')]
                .find(el => visible(el) && !el.disabled);
            (await waitFor(switcher, 'report selector')).click();
            const menu = await waitFor(() => {
                // Desktop navbar entries also use dropdown-item; count report choices only.
                const items = [...document.querySelectorAll('.dropdown-item')]
                    .filter(el => visible(el) && reportTitles.has(el.textContent.trim()));
                return items.length === 10 && items;
            }, 'all ten authorized reports');
            const titles = menu.map(el => el.textContent.trim());
            for (let index = 0; index < titles.length; index++) {
                if (index) { switcher().click(); }
                const item = await waitFor(() => [...document.querySelectorAll('.dropdown-item')]
                    .find(el => visible(el) && el.textContent.trim() === titles[index]), 'report choice');
                item.click();
                const toolbar = await waitFor(() => {
                    const bar = document.querySelector('.o_baseer_reports_hub_body .o_baseer_report_toolbar');
                    return bar?.querySelector('.o_baseer_report_switcher')?.textContent.trim() === titles[index] &&
                        bar.querySelector('.o_baseer_report_filters') && bar;
                }, titles[index]);
                // Let the browser finish layout; this is not a timed SLA assertion.
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                const exports = toolbar.querySelector('.o_baseer_report_exports');
                const filters = toolbar.querySelector('.o_baseer_report_filters');
                const selector = toolbar.querySelector('.o_baseer_report_switcher');
                if (exports?.parentElement !== toolbar || filters.parentElement !== toolbar ||
                    !(selector.compareDocumentPosition(exports) & Node.DOCUMENT_POSITION_FOLLOWING) ||
                    !(exports.compareDocumentPosition(filters) & Node.DOCUMENT_POSITION_FOLLOWING)) {
                    throw new Error(titles[index] + ': selector/export/filter order differs');
                }
                const buttons = [...exports.querySelectorAll('button')];
                if (buttons.length !== 2 || !buttons[0].classList.contains('o_baseer_report_xlsx') ||
                    !buttons[1].classList.contains('o_baseer_pl_pdf') ||
                    toolbar.querySelector('.o_baseer_report_pdf')) {
                    throw new Error(titles[index] + ': duplicate or reordered export buttons');
                }
                const first = filters.querySelector('button,summary,select,input');
                if (!['الفترة', 'Period', 'حتى تاريخ', 'As of'].includes(first?.getAttribute('aria-label'))) {
                    throw new Error(titles[index] + ': period/cutoff is not the first filter');
                }
                for (const el of [toolbar, exports, filters, selector, ...buttons,
                    ...filters.querySelectorAll(':scope > label, :scope > button')]) {
                    const rect = el.getBoundingClientRect();
                    if (rect.left < -1 || rect.right > innerWidth + 1) {
                        throw new Error(titles[index] + ': toolbar control overflows viewport');
                    }
                }
                if (innerWidth <= 560 && filters.getBoundingClientRect().top < exports.getBoundingClientRect().bottom - 1) {
                    throw new Error(titles[index] + ': mobile filters do not occupy their own row');
                }
                if (toolbar.closest('[dir]').getAttribute('dir') !== '__DIRECTION__') {
                    throw new Error(titles[index] + ': incorrect reading direction');
                }
            }
            console.log('BASEER_TEN_TOOLBARS_PASS __LANG__ ' + innerWidth);
            console.log('test successful');
        })().catch(error => { console.error(error); throw error; });
        """.replace('__DIRECTION__', 'rtl' if lang.startswith('ar') else 'ltr').replace('__LANG__', lang)
        self.browser_js('/odoo/action-%s' % self.env.ref('baseer_reports_menu.action_baseer_reports_hub').id,
                        script, ready="!!document.querySelector('.o_baseer_reports_hub.o_action')", login=reader.login)

    def test_toolbars_ar(self):
        self._check_toolbars('ar_001')

    def test_toolbars_en(self):
        self._check_toolbars('en_US')


@tagged('post_install', '-at_install', 'operations_browser', 'reports_toolbar_browser')
class TestReportToolbarBrowserMobile(TestReportToolbarBrowser):
    browser_size = '375x812'
    touch_enabled = True

    def test_toolbars_ar(self):
        super().test_toolbars_ar()

    def test_toolbars_en(self):
        super().test_toolbars_en()
