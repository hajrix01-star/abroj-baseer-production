from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCompanySeal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Abroj Seal Test',
            'baseer_document_seal_enabled': True,
        })
        cls.company.partner_id.write({
            'company_registry': '4030507223',
            'city': 'الخبر',
        })

    def test_seal_is_company_scoped(self):
        wizard = self.env['base.document.layout'].create({
            'company_id': self.company.id,
        })
        self.assertTrue(wizard.baseer_document_seal_enabled)
        wizard.baseer_document_seal_enabled = False
        self.assertFalse(self.company.baseer_document_seal_enabled)

    def test_seal_template_reads_current_company_data(self):
        html = self.env['ir.ui.view']._render_template(
            'baseer_document_theme.company_seal',
            {'company': self.company},
        )
        self.assertIn('4030507223', html)
        self.assertIn('الخبر', html)
        self.assertIn('Abroj Seal Test', html)

    def test_seal_template_is_empty_when_disabled(self):
        self.company.baseer_document_seal_enabled = False
        html = self.env['ir.ui.view']._render_template(
            'baseer_document_theme.company_seal',
            {'company': self.company},
        )
        self.assertNotIn('baseer-company-seal', html)
