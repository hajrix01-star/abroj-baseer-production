import base64
import io
import zipfile

from openpyxl import load_workbook

from odoo.tests.common import tagged
from odoo.tools.misc import format_date

from .common import EngineCase


@tagged('post_install', '-at_install')
class TestProfitAndLoss(EngineCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._company(cls, 'P&L test')
        cls.engine = cls._engine(cls, cls.company)
        cls.journal = cls._journal(cls, cls.company, 'PLT')
        cls.cash = cls._account(cls, cls.company, '1000', 'asset_cash')
        kinds = ['income', 'expense_direct_cost', 'expense', 'income_other', 'expense_other', 'expense_depreciation']
        cls.accounts = {kind: cls._account(cls, cls.company, str(4000 + i), kind) for i, kind in enumerate(kinds)}
        for kind, amount in zip(kinds, [1000, 300, 200, 50, 20, 30]):
            account = cls.accounts[kind]
            debit, credit = (cls.cash, account) if kind.startswith('income') else (account, cls.cash)
            cls._entry(cls, cls.company, cls.journal, '2041-04-15', debit, credit, amount)
        cls._entry(cls, cls.company, cls.journal, '2040-04-15', cls.cash, cls.accounts['income'], 100)

    def test_values_reconciliation_and_drill(self):
        options = self._options(date_from='2041-01-01', date_to='2041-06-30', comparison=1, comparison_mode='year')
        report = self.engine.get_report('profit_and_loss', options)
        for code, value in {'REV': 1000, 'COR': 300, 'GROSS': 700, 'OPEX': 230, 'OPERATING': 470, 'OTHINC': 50, 'OTHEXP': 20, 'NET_OTHER': 30, 'NET': 500}.items():
            self.assertEqual(float(self._value(report, code)), value, code)
        self.assertEqual(float(self._value(report, 'REV', 'c1')), 100)
        self.assertEqual(float(self._value(report, 'REV', 'variation')), 900)
        grouped = self.env['account.move.line']._read_group([('company_id', '=', self.company.id), ('parent_state', '=', 'posted'), ('date', '>=', '2041-01-01'), ('date', '<=', '2041-06-30'), ('account_id.account_type', 'in', list(self.accounts))], [], ['balance:sum'])
        self.assertEqual(float(self._value(report, 'NET')), -grouped[0][0])
        bs = self.engine.get_report('balance_sheet', self._options(as_of='2041-06-30'))
        self.assertEqual(float(self._value(report, 'NET')), float(self._value(bs, 'CY_EARN')))
        # CY_UNA includes the negative balance of current-year equity_unaffected.
        equity = self._account(self.company, '3999', 'equity_unaffected')
        self._entry(self.company, self.journal, '2041-05-01', self.cash, equity, 25)
        bs = self.engine.get_report('balance_sheet', self._options(as_of='2041-06-30'))
        self.assertEqual(float(self._value(report, 'NET')), float(self._value(bs, 'CY_UNA')) - float(self._value(bs, 'CY_ALLOC')))
        for code, kinds, sign in [('REV', ['income'], -1), ('COR', ['expense_direct_cost'], 1), ('OPEX', ['expense', 'expense_depreciation'], 1), ('OTHINC', ['income_other'], -1), ('OTHEXP', ['expense_other'], 1)]:
            rows = self.engine.get_line_accounts('profit_and_loss', options, code)['accounts']
            self.assertEqual({r['id'] for r in rows}, {self.accounts[kind].id for kind in kinds})
            action = self.engine.get_move_line_action('profit_and_loss', options, code, 'c0')
            move_lines = self.env['account.move.line'].search(action['domain'])
            self.assertEqual(sum(move_lines.mapped('balance')) * sign, float(self._value(report, code)))

    def test_menu_translations_and_export(self):
        self.env['res.lang']._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(['baseer_report_engine'], ['ar_001'], overwrite=True)
        menu = self.env.ref('baseer_report_engine.menu_profit_and_loss')
        self.assertEqual(menu.parent_id, self.env.ref('baseer_report_engine.menu_new_version'))
        self.assertEqual(menu.sequence, 20)
        action = self.env.ref('baseer_report_engine.action_profit_and_loss')
        definition = self.env.ref('baseer_report_engine.report_profit_and_loss')
        for lang, name, menu_name in [
            ('en_US', 'Profit and Loss', 'Profit and Loss (New)'),
            ('ar_001', 'الربح والخسارة', 'الربح والخسارة (جديد)'),
        ]:
            self.assertEqual(definition.with_context(lang=lang).name, name)
            self.assertEqual(action.with_context(lang=lang).name, menu_name)
            self.assertEqual(menu.with_context(lang=lang).name, menu_name)
        for xmlid, english, arabic in [
            ('report_balance_sheet', 'Balance Sheet', 'الميزانية العمومية'),
            ('report_trial_balance', 'Trial Balance', 'ميزان المراجعة'),
            ('report_general_ledger', 'General Ledger', 'دفتر الأستاذ العام'),
            ('report_partner_ledger', 'Partner Ledger', 'دفتر الأستاذ العام للشركاء'),
            ('report_aged_receivable', 'Aged Receivable', 'أعمار الديون المدينة'),
            ('report_aged_payable', 'Aged Payable', 'أعمار الديون الدائنة'),
            ('report_cash_flow', 'Cash Flow Statement', 'قائمة التدفقات النقدية'),
        ]:
            other = self.env.ref('baseer_report_engine.' + xmlid)
            self.assertEqual(other.with_context(lang='en_US').name, english)
            self.assertEqual(other.with_context(lang='ar_001').name, arabic)
        self.assertEqual(self.env.ref('baseer_report_engine.line_pl_net').with_context(lang='ar_001').name, 'صافي الربح')
        report_id = self.env.ref('baseer_report_engine.report_profit_and_loss').ids
        for lang, name, period in [('en_US', 'Profit and Loss', 'From %s to %s' % (format_date(self.env, '2041-01-01', lang_code='en_US'), format_date(self.env, '2041-06-30', lang_code='en_US'))), ('ar_001', 'الربح والخسارة', 'من %s إلى %s' % (format_date(self.env, '2041-01-01', lang_code='ar_001'), format_date(self.env, '2041-06-30', lang_code='ar_001')))]:
            html, output = self.env['ir.actions.report'].with_company(self.company).with_context(lang=lang, allowed_company_ids=[self.company.id])._render_qweb_html('baseer_report_engine.report_pdf', docids=report_id, data={'report_code': 'profit_and_loss', 'options': self._options()})
            self.assertEqual(output, 'html')
            self.assertIn(name.encode(), html)
            self.assertIn(period.encode(), html)
            self.assertIn(b'500.00', html)
        arabic_result = self.engine.with_context(lang='ar_001').export_xlsx('profit_and_loss', self._options())
        workbook = load_workbook(io.BytesIO(base64.b64decode(arabic_result['content'])))
        self.assertEqual(workbook.active.title, 'الربح والخسارة')
        self.assertIn('الربح والخسارة', workbook.active['A1'].value)
        result = self.engine.export_xlsx('profit_and_loss', self._options())
        self.assertEqual(result['filename'], 'profit-and-loss.xlsx')
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['content']))) as archive:
            self.assertIn(b'500', archive.read('xl/worksheets/sheet1.xml'))

    def test_filters(self):
        other = self._journal(self.company, 'PLU')
        self._entry(self.company, other, '2041-02-01', self.cash, self.accounts['income'], 80)
        isolated = self._options(date_from='2041-04-01', date_to='2041-04-30')
        self.assertEqual(float(self._value(self.engine.get_report('profit_and_loss', isolated), 'NET')), 500)
        empty = self.engine.get_report('profit_and_loss', self._options(date_from='2041-07-01', date_to='2041-07-31', hide_zero=True))
        self.assertEqual([line['code'] for line in empty['lines']], ['NET'])
        options = self._options(hide_zero=True, journal_ids=[self.journal.id])
        self.assertEqual(float(self._value(self.engine.get_report('profit_and_loss', options), 'NET')), 500)
        self._entry(self.company, self.journal, '2041-05-01', self.cash, self.accounts['income'], 10, posted=False)
        options['posted_only'] = False
        self.assertEqual(float(self._value(self.engine.get_report('profit_and_loss', options), 'NET')), 510)
