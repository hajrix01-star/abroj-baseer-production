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
class TestVatLayoutCss(TransactionCase):
    def test_mobile_layout(self):
        source = (Path(__file__).resolve().parents[1] / 'static/src/vat.scss').read_text()
        mobile = '\n'.join(blocks(source, r'@media\s*\(max-width:\s*767px\)'))
        vat = blocks(mobile, r'\.o_baseer_report_engine\.o_bre_vat\s+\.o_bre_table:not\(\.o_bre_grid_table\)')
        self.assertTrue(vat)
        values = blocks(vat[0], r'\.o_bre_value_col')
        labels = blocks(vat[0], r'\.o_bre_label_col')
        self.assertTrue(values and labels)
        width = re.search(r'width\s*:\s*(\d+)px', values[0])
        self.assertTrue(width)
        self.assertLess(int(width.group(1)), 130)
        self.assertRegex(labels[0], r'(?:min-)?width\s*:\s*(?:1[6-9]\d|200)px')
        self.assertNotRegex(mobile, r'min-width\s*:\s*calc\(798px')
        self.assertNotRegex(mobile, r'border-radius\s*:\s*0\b')
