from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestReceiptNumbering(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env['abroj.cost.project'].create({
            'name': 'Receipt numbering regression project',
            'agreement_amount': 1000,
        })

    def test_create_without_name_gets_a_receipt_reference(self):
        receipt = self.env['abroj.cost.receipt'].create({
            'project_id': self.project.id,
            'amount': 100,
        })
        self.assertRegex(receipt.name, r'^RCV/\d{4}/\d{5}$')

    def test_project_receipt_default_shows_the_reference_before_save(self):
        values = self.env['abroj.cost.receipt'].with_context(
            default_project_id=self.project.id,
        ).default_get(['name', 'project_id'])
        self.assertRegex(values['name'], r'^RCV/\d{4}/\d{5}$')

    def test_native_receipt_template_adapter_keeps_project_totals_in_backend(self):
        first = self.env['abroj.cost.receipt'].create({
            'project_id': self.project.id,
            'amount': 100,
        })
        second = self.env['abroj.cost.receipt'].create({
            'project_id': self.project.id,
            'amount': 250,
        })
        summary = second._get_project_receipt_summary()
        self.assertEqual(summary['prior_receipts'], first)
        self.assertEqual(summary['prior_amount'], 100)
        self.assertEqual(summary['received_after'], 350)
        self.assertEqual(summary['remaining_after'], 650)
        self.assertEqual(second._get_payment_receipt_report_values(), {
            'display_payment_method': False,
            'display_invoices': False,
        })
