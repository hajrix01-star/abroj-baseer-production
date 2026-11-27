from odoo.addons.baseer_zatca_pos_scope.models.pos_config import PosConfig as ScopePosConfig
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

    def test_scope_does_not_override_pos_opening(self):
        # Opening a POS goes through the full native MRO: Odoo's own ZATCA
        # journal gate (only for journals with the sa_zatca format) and every
        # other module's guard, e.g. baseer_pos_summary.
        self.assertNotIn('open_ui', vars(ScopePosConfig))

    def test_disabled_scope_preserves_other_pos_opening_guards(self):
        config = self._new_config()
        if 'baseer_summary_only' not in config._fields:
            self.skipTest('baseer_pos_summary is not installed in this test database')
        # Only one summary-only POS may exist per company (archived ones
        # count). A database copied from Live already has it: use that one.
        summary = self.env['pos.config'].with_context(active_test=False).search([
            ('company_id', '=', config.company_id.id),
            ('baseer_summary_only', '=', True),
        ], limit=1)
        if summary:
            config = summary
            config.write({'baseer_zatca_phase2_enabled': False})
        else:
            config.write({
                'baseer_zatca_phase2_enabled': False,
                'baseer_summary_only': True,
            })
        self.assertFalse(config.baseer_zatca_phase2_enabled)
        # baseer_pos_summary's own guard must answer, not a later session check.
        with self.assertRaisesRegex(AccessError, 'External Sales Summaries'):
            config.with_context(lang='en_US').open_ui()
