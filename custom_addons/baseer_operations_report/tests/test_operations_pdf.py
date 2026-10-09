"""A direct report URL cannot print the deliberately incomplete source."""

from unittest.mock import patch

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..models.operations import BaseerOperationsReport


@tagged('post_install', '-at_install')
class TestOperationsPdfGuard(TransactionCase):

    def setUp(self):
        super().setUp()
        self.filters = {
            'company_id': self.env.company.id,
            'date_from': '2041-06-01', 'date_to': '2041-06-30',
            'journal_ids': [],
        }

    def test_direct_invocation_denies_incomplete_source_and_bad_scope(self):
        portrait = self.env['report.baseer_operations_report.operations_pdf_portrait']
        landscape = self.env['report.baseer_operations_report.operations_pdf_landscape']
        for data in (None, {}, {'filters': []}):
            with self.assertRaises(ValidationError):
                portrait._get_report_values([], data)
        with self.assertRaises(ValidationError):
            portrait._get_report_values([1], {'filters': self.filters})
        for invalid_id in (True, 0, self.env.company.id + 100000):
            with self.assertRaises(AccessError):
                portrait._get_report_values([], {
                    'filters': {**self.filters, 'company_id': invalid_id},
                })
        with patch.object(BaseerOperationsReport, 'get_source_snapshot',
                          return_value={'complete': False}) as source:
            for adapter in (portrait, landscape):
                with self.assertRaises(AccessError):
                    adapter._get_report_values([], {'filters': self.filters})
            self.assertEqual(source.call_count, 2)
            with self.assertRaises(AccessError):
                self.env['ir.actions.report']._render_qweb_html(
                    'baseer_operations_report.operations_pdf_portrait',
                    docids=[], data={'filters': self.filters},
                )

    def test_both_a4_formats_registered_without_a_user_menu(self):
        portrait = self.env.ref('baseer_operations_report.action_operations_pdf_portrait')
        landscape = self.env.ref('baseer_operations_report.action_operations_pdf_landscape')
        self.assertEqual(portrait.paperformat_id.format, 'A4')
        self.assertEqual(portrait.paperformat_id.orientation, 'Portrait')
        self.assertEqual(landscape.paperformat_id.format, 'A4')
        self.assertEqual(landscape.paperformat_id.orientation, 'Landscape')
        self.assertFalse(portrait.binding_model_id)
        self.assertFalse(landscape.binding_model_id)
