"""BWork settings own these controls, not global company configuration."""
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ADDON = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retention_ui_catalog', ADDON / 'tests_contract/test_retention_ui_contract.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


class CompanyDisplayUiContract(unittest.TestCase):
    def test_native_bwork_only_views_do_not_enable_company_creation_or_legal_name_edits(self):
        document = ET.parse(ADDON / 'views/admin_views.xml')
        for name, tag in (('company_display_list', 'list'), ('company_display_form', 'form')):
            record = document.find(f".//record[@id='{name}']")
            self.assertIsNone(record.find("field[@name='inherit_id']"))
            self.assertEqual(record.find("field[@name='priority']").text, '99')
            view = record.find(f"field[@name='arch']/{tag}")
            self.assertEqual(view.get('create'), '0')
            self.assertEqual(view.get('delete'), '0')
            self.assertEqual(view.find(".//field[@name='name']").get('readonly'), '1')
            self.assertEqual({field.get('name') for field in view.iter('field')},
                {'name', 'bwork_short_name_ar', 'bwork_short_name_en', 'bwork_hidden'})
        menu = document.find(".//menuitem[@id='company_display_menu']")
        self.assertEqual(menu.get('parent'), 'settings_menu')
        self.assertEqual(menu.get('groups'), 'base.group_system')

    def test_settings_labels_are_translated_in_both_arabic_locales(self):
        for language in ('ar', 'ar_001'):
            translations = catalog.catalog(language)
            for label in ('Settings', 'Companies', 'Company', 'BWork company settings',
                    'These settings affect BWork only. Official company names, permissions and existing data stay unchanged.'):
                self.assertTrue(translations[label][0])
            self.assertIn('baseer_bwork_admin.company_display_menu', translations['Companies'][1])


if __name__ == '__main__':
    unittest.main()
