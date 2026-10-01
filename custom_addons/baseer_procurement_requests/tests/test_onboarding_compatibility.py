import importlib.util
from pathlib import Path
from unittest.mock import patch

from lxml import etree
from psycopg2.extras import Json

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class OnboardingCompatibilityCase(TransactionCase):

    def test_legacy_parent_cleanup_is_scoped_translated_and_idempotent(self):
        script = Path(__file__).parents[1] / 'migrations/19.0.14.0.6/pre-migration.py'
        spec = importlib.util.spec_from_file_location('procurement_parent_compatibility', script)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        parent = self.env.ref('baseer_company_setup.view_baseer_company_onboarding_form')
        other = self.env.ref('baseer_company_setup.view_company_form_onboarding')
        self.env['ir.ui.view'].flush_model(['arch_db'])
        self.env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', [other.id])
        other_arch = self.env.cr.fetchone()[0]
        legacy = '<form string="Keep"><group name="keep"><field name="setup_core"/><field name="setup_tobacco_fee"/><label for="tobacco_fee_state"/><field name="tobacco_fee_state"/><field name="tobacco_fee_message"/></group><div>Custom text</div></form>'
        arches = {'en_US': legacy, 'ar_001': legacy.replace('Keep', 'احتفظ')}
        self.env.cr.execute('UPDATE ir_ui_view SET arch_db = %s WHERE id = %s', [Json(arches), parent.id])
        # Supported fields must never be removed, even with legacy controls.
        wizard_fields = self.env['baseer.company.onboarding']._fields
        with patch.dict(wizard_fields, {name: wizard_fields['setup_core'] for name in migration._LEGACY_FIELDS}):
            migration.migrate(self.env.cr, '19.0.14.0.5')
        self.env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', [parent.id])
        self.assertEqual(self.env.cr.fetchone()[0], arches)
        migration.migrate(self.env.cr, '19.0.14.0.5')
        self.env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', [parent.id])
        cleaned = self.env.cr.fetchone()[0]
        self.assertEqual(set(cleaned), set(arches))
        for language, arch in cleaned.items():
            root = etree.fromstring(arch.encode())
            self.assertEqual(root.get('string'), 'احتفظ' if language == 'ar_001' else 'Keep')
            self.assertEqual(root.xpath('//field/@name'), ['setup_core'])
            self.assertFalse(root.xpath('//label'))
            self.assertEqual(root.xpath('//group/@name'), ['keep'])
            self.assertEqual(root.xpath('//div/text()'), ['Custom text'])
        migration.migrate(self.env.cr, '19.0.14.0.5')
        self.env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', [parent.id])
        self.assertEqual(self.env.cr.fetchone()[0], cleaned)
        self.env.cr.execute('SELECT arch_db FROM ir_ui_view WHERE id = %s', [other.id])
        self.assertEqual(self.env.cr.fetchone()[0], other_arch)
