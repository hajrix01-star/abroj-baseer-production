from types import SimpleNamespace

from odoo.tests.common import TransactionCase, tagged

from ..models.note import normalize_detail_notes, plain_note
from .note_cases import CASES


@tagged('post_install', '-at_install')
class TestKitchenNotes(TransactionCase):
    def test_structured_and_legacy_notes(self):
        for value, expected in CASES:
            with self.subTest(value=value):
                self.assertEqual(plain_note(value), expected)

    def test_normalize_detail_notes(self):
        details = {'note': '[{"text":"أول"}]', 'customer_note': '[{"text":"ثان"}]', 'name': 'Food'}
        self.assertEqual(normalize_detail_notes(details), {
            'note': 'أول', 'customer_note': 'ثان', 'name': 'Food',
        })
        self.assertEqual(details['note'], '[{"text":"أول"}]')
        self.assertEqual(normalize_detail_notes({'name': 'Food'}), {'name': 'Food'})

    def test_details_and_comparison(self):
        model = self.env['baseer.print.preparation.state']
        line = SimpleNamespace(
            uuid='new', product_id=SimpleNamespace(id=1, display_name='Food'),
            full_product_name='Food', note='[{"text":"أول"}]',
            customer_note='[{"text":"ثان"}]', qty=1, _fields={},
        )
        current = model._line_details(line)
        self.assertEqual((current['note'], current['customer_note']), ('أول', 'ثان'))
        stored = dict(current, line_uuid='old', note='[{"text":"أول"}]',
                      customer_note='[{"text":"ثان"}]')
        state = SimpleNamespace(details=stored)
        self.assertTrue(model._same_logical_line(state, current))
        self.assertFalse(model._details_changed(state, current))
        current['note'] = 'مختلف'
        self.assertFalse(model._same_logical_line(state, current))
        self.assertTrue(model._details_changed(state, current))

    def test_preparation_payload_normalizes_saved_notes(self):
        printer = SimpleNamespace(machine_identifier='test', paper_width=80)
        lines = [{'name': 'Food', 'note': '[{"text":"أول"}]',
                  'customer_note': '[{"text":"ثان"}]'}]
        payload = self.env['baseer.print.job']._job_payload('preparation', False, printer, lines)
        self.assertEqual(payload['lines'], [{'name': 'Food', 'note': 'أول', 'customer_note': 'ثان'}])
        self.assertEqual(lines[0]['note'], '[{"text":"أول"}]')
