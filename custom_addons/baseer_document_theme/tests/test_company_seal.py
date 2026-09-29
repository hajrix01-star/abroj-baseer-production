import base64

from odoo.tests.common import TransactionCase, tagged


TEST_STAMP = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
).decode()


@tagged('post_install', '-at_install')
class TestCompanySeal(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({
            'name': 'Abroj Seal Test',
            'baseer_document_seal_enabled': True,
            'baseer_document_seal_image': TEST_STAMP,
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
        self.assertEqual(
            base64.b64decode(wizard.baseer_document_seal_image),
            base64.b64decode(TEST_STAMP),
        )
        self.assertEqual(wizard.baseer_document_seal_position, 'left')
        wizard.baseer_document_seal_enabled = False
        self.assertFalse(self.company.baseer_document_seal_enabled)

    def test_baseer_boxed_is_the_selectable_company_layout(self):
        selectable_layout = self.env.ref(
            'baseer_document_theme.report_layout_baseer_theme'
        )
        self.assertEqual(
            selectable_layout.view_id,
            self.env.ref('baseer_document_theme.external_layout_baseer_boxed'),
        )

    def test_seal_template_uses_uploaded_image(self):
        html = self.env['ir.ui.view']._render_template(
            'baseer_document_theme.company_seal',
            {'company': self.company},
        )
        self.assertIn('baseer-company-seal', html)
        self.assertIn('data:image', html)

    def test_seal_template_is_empty_when_disabled(self):
        self.company.baseer_document_seal_enabled = False
        html = self.env['ir.ui.view']._render_template(
            'baseer_document_theme.company_seal',
            {'company': self.company},
        )
        self.assertNotIn('baseer-company-seal', html)

    def test_seal_template_respects_selected_document_types(self):
        model = self.env['ir.model']._get('res.partner')
        self.company.write({
            'baseer_document_seal_scope': 'selected',
            'baseer_document_seal_model_ids': [(6, 0, [model.id])],
        })
        html = self.env['ir.ui.view']._render_template(
            'baseer_document_theme.company_seal',
            {'company': self.company, 'o': self.env['res.partner'].new({})},
        )
        self.assertIn('baseer-company-seal', html)
