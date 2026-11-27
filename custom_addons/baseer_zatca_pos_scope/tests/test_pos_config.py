from unittest.mock import patch

from odoo.addons.l10n_sa_edi_pos.models.pos_config import PosConfig as L10nSaEdiPosConfig
from odoo.addons.l10n_sa_pos.models.pos_config import PosConfig as L10nSaPosConfig
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestZatcaPosScope(TransactionCase):
    def _new_config(self):
        return self.env['pos.config'].create({'name': 'ZATCA scope test'})

    def test_scope_flag_is_loaded_in_pos_session_data(self):
        config = self._new_config()
        self.assertIn('baseer_zatca_phase2_enabled', config._load_pos_data_fields(config))

        config.baseer_zatca_phase2_enabled = True
        payload = config._load_pos_data_read(config, config)
        self.assertTrue(payload[0]['baseer_zatca_phase2_enabled'])

    def test_disabled_scope_bypasses_only_the_native_zatca_opening_gate(self):
        config = self._new_config()
        config.baseer_zatca_phase2_enabled = False
        expected_action = {'type': 'ir.actions.act_url', 'url': '/pos/test'}

        # The method immediately below Odoo's EDI guard is patched so this
        # regression test proves the disabled path reaches the normal POS
        # opening chain without opening a real session.
        with patch.object(L10nSaPosConfig, 'open_ui', return_value=expected_action) as open_ui:
            self.assertEqual(config.open_ui(), expected_action)
        open_ui.assert_called_once_with()

    def test_enabled_scope_keeps_the_native_zatca_opening_gate(self):
        config = self._new_config()
        config.baseer_zatca_phase2_enabled = True
        expected_action = {'type': 'ir.actions.act_url', 'url': '/pos/test'}

        with patch.object(L10nSaEdiPosConfig, 'open_ui', return_value=expected_action) as open_ui:
            self.assertEqual(config.open_ui(), expected_action)
        open_ui.assert_called_once_with()

    def test_disabled_scope_preserves_other_pos_opening_guards(self):
        if 'baseer_summary_only' not in self.env['pos.config']._fields:
            self.skipTest('baseer_pos_summary is not installed in this test database')
        # Only one summary-only POS is allowed per company, and a copied
        # database already has one, so use a fresh company for this check.
        company = self.env['res.company'].create({
            'name': 'ZATCA scope summary test',
            'country_id': self.env.ref('base.sa').id,
        })
        self.env.user.company_ids |= company
        config = self.env['pos.config'].with_company(company).create({
            'name': 'ZATCA scope test',
            'company_id': company.id,
        })

        config.write({
            'baseer_zatca_phase2_enabled': False,
            'baseer_summary_only': True,
        })
        with self.assertRaises(AccessError):
            config.open_ui()
