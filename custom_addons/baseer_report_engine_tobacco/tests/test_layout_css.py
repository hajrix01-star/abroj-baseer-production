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
        self.assertTrue(blocks(mobile, r'\.o_bre_grid_table\.o_bre_tobacco_exceptions'))
        self.assertRegex(source, r'/\*rtl:ignore\*/\s*direction\s*:\s*ltr\s*;')
