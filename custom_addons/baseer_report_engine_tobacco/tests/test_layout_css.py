import re
from pathlib import Path

from odoo.tests import TransactionCase, tagged


def blocks(source, selector):
    results = []
    for match in re.finditer(selector + r'\s*\{', source):
        depth = 1
        for index in range(match.end(), len(source)):
            depth += (source[index] == '{') - (source[index] == '}')
            if not depth:
                results.append(source[match.end():index])
                break
    return results


@tagged('post_install', '-at_install')
class TestTobaccoLayoutCss(TransactionCase):
    def test_mobile_layout_and_amount_direction(self):
        source = (Path(__file__).resolve().parents[1] / 'static/src/tobacco.scss').read_text()
        mobile = '\n'.join(blocks(source, r'@media\s*\(max-width:\s*767px\)'))
        table = blocks(mobile, r'\.o_bre_grid_table\.o_bre_tobacco_table')
        self.assertTrue(table)
        self.assertNotRegex(table[0], r'min-width\s*:\s*0\s*;')
        self.assertRegex(table[0], r'min-width\s*:\s*1000px\s*;')
        self.assertRegex(table[0], r'white-space\s*:\s*nowrap\s*;')
        self.assertIn('.o_baseer_report_engine:has(.o_bre_tobacco_month, .o_bre_tobacco_table)', source)
        self.assertIn('max-width: 100%', source)
        self.assertIn('overflow-wrap: anywhere', source)
        self.assertIn('.o_bre_scroll { overflow-x: auto; }', source)
        self.assertRegex(source, r'/\*rtl:ignore\*/\s*direction\s*:\s*ltr\s*;')

    def test_month_picker_and_report_template(self):
        root = Path(__file__).resolve().parents[1]
        template = (root / 'static/src/tobacco.xml').read_text()
        js = (root / 'static/src/tobacco.js').read_text()
        self.assertIn('type="month"', template)
        self.assertIn('Date.UTC(year, month, 0)', js)
        self.assertIn('show_cumulative', js)
        for forbidden in ('سداد', 'Manual journal entries', 'قيود اليومية اليدوية', 'Fee account movement in the trial balance', 'reconciliation'):
            self.assertNotIn(forbidden, template)
            self.assertNotIn(forbidden, js)
