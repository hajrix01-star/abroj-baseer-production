import re
from pathlib import Path

from odoo.tests import TransactionCase, tagged


def blocks(source, selector):
    """Return bodies of matching SCSS blocks, including nested blocks."""
    results = []
    for match in re.finditer(selector + r'\s*\{', source):
        start = match.end()
        depth = 1
        for index in range(start, len(source)):
            depth += (source[index] == '{') - (source[index] == '}')
            if not depth:
                results.append(source[start:index])
                break
    return results


@tagged('post_install', '-at_install')
class TestLayoutCss(TransactionCase):
    def test_mobile_and_number_rules(self):
        source = (Path(__file__).resolve().parents[1] / 'static/src/report_engine.scss').read_text()
        mobile = '\n'.join(blocks(source, r'@media\s*\(max-width:\s*767px\)'))
        papers = blocks(mobile, r'\.o_bre_paper')
        self.assertTrue(papers)
        self.assertFalse(any(re.search(r'border-radius\s*:\s*0\b', body) for body in papers))
        self.assertRegex(source, r'border-radius\s*:\s*4px')
        self.assertRegex(mobile, r'\.o_bre_paper_inner[^{}]*\{\s*min-width\s*:\s*0\s*;')
        self.assertNotRegex(mobile, r'min-width\s*:\s*calc\(798px')
        self.assertRegex(mobile, r'\.o_bre_table:not\(\.o_bre_grid_table\)\s*\{[^{}]*width\s*:')
        clipping = blocks(mobile, r'\.o_bre_grid_table th:first-child,\s*\.o_bre_grid_table td:first-child,\s*\.o_bre_grid_table \.o_bre_label_col,\s*\.o_bre_ledger_table \.o_bre_ledger_label,\s*\.o_bre_partner_table \.o_bre_partner_label,\s*\.o_bre_aged_table \.o_bre_aged_label')
        self.assertEqual(len(clipping), 1)
        for declaration in (r'max-width\s*:\s*160px', r'overflow\s*:\s*hidden',
                            r'text-overflow\s*:\s*ellipsis', r'white-space\s*:\s*nowrap'):
            self.assertRegex(clipping[0], declaration)
        tobacco = blocks(mobile, r'\.o_bre_grid_table\.o_bre_tobacco_table')
        self.assertTrue(tobacco)
        self.assertRegex(tobacco[0], r'min-width\s*:\s*1000px')
        self.assertNotRegex(mobile, r'\.o_bre_tobacco_table\s*\{[^{}]*min-width\s*:\s*0\s*;')
        numbers = blocks(source, r'(?<![\w-])\.is-number')
        self.assertGreaterEqual(len(numbers), 3)
        for body in numbers:
            for declaration in re.finditer(r'(?<![\w-])(direction|text-align)\s*:', body):
                self.assertRegex(body[:declaration.start()], r'/\*rtl:ignore\*/\s*$')
        overrides = blocks(source, r'(?:&|\.o_baseer_report_engine)\[dir="rtl"\][^{}]*\.is-number')
        self.assertGreaterEqual(len(overrides), 2)
        for body in overrides:
            self.assertRegex(body, r'/\*rtl:ignore\*/\s*text-align\s*:\s*left\s*;')
