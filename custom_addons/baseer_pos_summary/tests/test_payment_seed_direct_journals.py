from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPaymentSeedDirectJournals(TransactionCase):

    def test_new_company_uses_one_journal_per_platform(self):
        """Fresh company defaults keep platform liquidity and receivables apart."""
        country = self.env.ref('base.sa')
        company = self.env['res.company'].create({
            'name': 'Direct platform journals test company',
            'currency_id': country.currency_id.id,
            'country_id': country.id,
        })
        company = company.with_context(allowed_company_ids=[company.id]).with_company(company)
        company._baseer_prepare_accounting()

        expected = {
            'hungerstation': ('هنقرستيشن | HungerStation', 'HUNG', '101008', '102110'),
            'keeta': ('كيتا | Keeta', 'KEET', '101007', '102111'),
            'jahez': ('جاهز | Jahez', 'JAHZ', '101009', '102112'),
        }
        methods = self.env['pos.payment.method'].search([('company_id', '=', company.id)])
        platform_methods = methods.filtered(lambda method: method.baseer_category_id.kind == 'platform')

        self.assertEqual(len(platform_methods), len(expected))
        self.assertEqual(len(platform_methods.mapped('journal_id')), len(expected))
        for key, (name, journal_code, liquidity_code, clearing_code) in expected.items():
            method = company._baseer_pos_identity('method_' + key, 'pos.payment.method')
            self.assertTrue(method)
            self.assertEqual(method.journal_id.name, name)
            self.assertEqual(method.journal_id.code, journal_code)
            self.assertEqual(method.journal_id.type, 'bank')
            self.assertEqual(method.journal_id.default_account_id.code, liquidity_code)
            self.assertEqual(method.journal_id.default_account_id.account_type, 'asset_cash')
            self.assertEqual(method.outstanding_account_id.code, clearing_code)
            self.assertEqual(method.outstanding_account_id.account_type, 'asset_current')
            self.assertTrue(method.outstanding_account_id.reconcile)

        company._baseer_create_pos_defaults()
        self.assertEqual(len(self.env['account.journal'].search([('company_id', '=', company.id),
            ('code', 'in', [values[1] for values in expected.values()])])), len(expected))
