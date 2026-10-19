"""Display-only rename: protect stable technical identifiers and approved asset."""
import ast
import csv
import hashlib
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
ADDON = ROOT / 'custom_addons/baseer_bchat'


class BWorkBrandingContracts(unittest.TestCase):
    def test_manifest_keeps_existing_dependencies(self):
        manifest = ast.literal_eval((ADDON / '__manifest__.py').read_text('utf-8'))
        self.assertEqual(manifest['name'], 'BWork')
        self.assertEqual(manifest['depends'], ['mail', 'project'])
        self.assertTrue(manifest['application'])
        self.assertFalse(manifest['auto_install'])

    def test_menu_and_actions_keep_technical_ids(self):
        xml = ET.parse(ADDON / 'views/bchat_admin_views.xml').getroot()
        menu = xml.find("menuitem[@id='menu_bchat_root']")
        self.assertEqual(menu.attrib['name'], 'BWork')
        self.assertEqual(menu.attrib['groups'], 'baseer_bchat.group_bchat_manager')
        self.assertEqual(menu.attrib['web_icon'], 'baseer_bchat,static/description/icon.png')
        for suffix, model in [('rooms', 'baseer.bchat.room'), ('memberships', 'baseer.bchat.membership')]:
            action = xml.find(f"record[@id='action_bchat_{suffix}']")
            self.assertEqual(action.find("field[@name='res_model']").text, model)

    def test_permission_view_keeps_capability_fields_and_system_guard(self):
        xml = ET.parse(ADDON / 'views/res_users_bchat_views.xml').getroot()
        group = xml.find(".//group[@name='bchat_capabilities']")
        self.assertEqual(group.attrib['string'], 'BWork')
        self.assertEqual(group.attrib['groups'], 'base.group_system')
        self.assertEqual({field.attrib['name'] for field in group.findall('field')}, {
            'bchat_chat_view', 'bchat_chat_send', 'bchat_media', 'bchat_group_create',
            'bchat_group_manage', 'bchat_task_view', 'bchat_task_manage',
            'bchat_room_admin_eligible', 'bchat_manage_rooms',
        })

    def test_no_private_source_acl_added(self):
        with (ADDON / 'security/ir.model.access.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 5)
        self.assertFalse(any(row['perm_unlink'] != '0' for row in rows))
        self.assertEqual({row['model_id:id'] for row in rows}, {
            'model_baseer_bchat_receipt', 'model_baseer_bchat_binding',
            'model_baseer_bchat_room', 'model_baseer_bchat_membership',
        })
        xml = ET.parse(ADDON / 'security/security.xml').getroot()
        self.assertEqual(xml.find("record[@id='group_bchat_manager']/field[@name='name']").text,
                         'BWork Conversation Manager')
        self.assertFalse(xml.findall(".//field[@name='users']"))

    def test_icon_is_existing_approved_asset_and_both_arabic_locales_have_brand(self):
        icon = ADDON / 'static/description/icon.png'
        approved = ROOT / 'mobile/chatwoot/assets/bwork/bwork-icon-1024.png'
        self.assertEqual(hashlib.sha256(icon.read_bytes()).digest(), hashlib.sha256(approved.read_bytes()).digest())
        for locale in ('ar', 'ar_001'):
            text = (ADDON / f'i18n/{locale}.po').read_text('utf-8')
            self.assertIn('msgid "BWork"\nmsgstr "بيورك"', text)
            self.assertIn('msgid "BWork Rooms"\nmsgstr "غرف بيورك"', text)


if __name__ == '__main__':
    unittest.main()
