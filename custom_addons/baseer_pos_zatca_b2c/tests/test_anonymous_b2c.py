from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAnonymousB2CPolicy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.saudi_company = cls.env['res.company'].new({
            'name': 'QA Saudi Company',
            'country_id': cls.env.ref('base.sa').id,
        })
        cls.consumer = cls.env['res.partner'].create({
            'name': 'Internal Anonymous Consumer',
            'company_type': 'person',
        })
        cls.config = cls.env['pos.config'].new({
            'name': 'QA POS',
            'company_id': cls.saudi_company,
            'baseer_zatca_allow_anonymous_b2c': True,
            'baseer_zatca_anonymous_partner_id': cls.consumer,
        })

    def test_assigns_internal_consumer_only_to_final_unnamed_b2c_sale(self):
        partner = self.config._baseer_zatca_anonymous_partner_for_order({
            'state': 'paid', 'to_invoice': True,
        })
        self.assertEqual(partner, self.consumer)

    def test_never_assigns_to_named_draft_or_shipping_order(self):
        named = {'state': 'paid', 'to_invoice': True, 'partner_id': self.consumer.id}
        draft = {'state': 'draft', 'to_invoice': True}
        shipping = {'state': 'paid', 'to_invoice': True, 'shipping_date': '2026-10-31'}
        self.assertFalse(self.config._baseer_zatca_anonymous_partner_for_order(named))
        self.assertFalse(self.config._baseer_zatca_anonymous_partner_for_order(draft))
        self.assertFalse(self.config._baseer_zatca_anonymous_partner_for_order(shipping))

    def test_internal_consumer_field_uses_no_client_side_domain(self):
        """The POS form cannot resolve partner-only fields in its own domain."""
        field = self.env['pos.config']._fields['baseer_zatca_anonymous_partner_id']
        self.assertFalse(field.domain)
