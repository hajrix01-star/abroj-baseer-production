"""Native form/translation contracts; not a substitute for installed Odoo tests."""
import ast
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ADDON = Path(__file__).resolve().parents[1]


def view(record_id):
    root = ET.parse(ADDON / 'views/retention_views.xml')
    return root.find(f".//record[@id='{record_id}']/field[@name='arch']")


def catalog(language):
    result = {}
    for block in (ADDON / f'i18n/{language}.po').read_text(encoding='utf-8').split('\n\n'):
        key = re.search(r'^msgid (".*")$', block, re.M)
        value = re.search(r'^msgstr (".*")$', block, re.M)
        if key and value:
            label = json.loads(key[1])
            if label:
                if label in result:
                    raise AssertionError(f'duplicate catalog key: {label}')
                result[label] = (json.loads(value[1]), block)
    return result


class RetentionUiContract(unittest.TestCase):
    def test_manual_action_is_modal_preview_not_execution(self):
        doc = ET.parse(ADDON / 'views/retention_views.xml')
        self.assertEqual(doc.find(".//record[@id='retention_wizard_action']/field[@name='target']").text, 'new')
        form = view('retention_wizard_form').find('form')
        self.assertEqual(form.get('create'), '0')
        actions = [b.get('name') for b in form.iter('button') if b.get('type') == 'object']
        self.assertEqual(actions, ['action_preview'])
        fields = {f.get('name') for f in form.iter('field')}
        self.assertTrue({'company_id', 'scope_mode', 'room_ids', 'mode', 'cutoff_mode', 'cutoff_date', 'older_than_days', 'timezone'} <= fields)

    def test_run_discloses_frozen_scope_limits_and_permanent_confirmation(self):
        form = view('retention_run_form').find('form')
        self.assertEqual(form.get('create'), '0')
        self.assertEqual(form.get('delete'), '0')
        confirm = form.find(".//button[@name='action_confirm']")
        self.assertIn('permanently', confirm.get('confirm'))
        self.assertEqual(confirm.get('invisible'), "state != 'preview'")
        check = form.find(".//field[@name='confirmation_checked']")
        self.assertEqual(check.get('readonly'), "state != 'preview'")
        fields = {f.get('name') for f in form.iter('field')}
        self.assertTrue({'eligible_total', 'remaining_eligible', 'batch_limited', 'expires_at', 'candidate_bytes_display', 'protected_display', 'audit_ids'} <= fields)
        self.assertFalse({'message_id', 'media_id'} & fields, 'native display_name must not expand private content ACL')

    def test_policy_schedule_is_separate_from_explicit_readiness(self):
        form = view('retention_policy_form').find('form')
        fields = {f.get('name') for f in form.iter('field')}
        self.assertTrue({'enabled', 'retention_days', 'schedule_hour', 'schedule_minute', 'timezone', 'readiness_status', 'ack_clients_updated', 'ack_legacy_offline'} <= fields)
        self.assertIn('base.group_system', form.find(".//button[@name='action_confirm_readiness']").get('groups'))
        self.assertIn('base.group_system', form.find(".//button[@name='action_revoke_readiness']").get('groups'))
        model = ast.parse((ADDON / 'models/retention.py').read_text(encoding='utf-8'))
        policy = next(n for n in model.body if isinstance(n, ast.ClassDef) and any(isinstance(a, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_name' for t in a.targets) and isinstance(a.value, ast.Constant) and a.value.value == 'baseer.bwork.retention.policy' for a in n.body))
        enabled = next(n.value for n in policy.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'enabled' for t in n.targets))
        self.assertTrue(any(k.arg == 'default' and isinstance(k.value, ast.Constant) and k.value.value is False for k in enabled.keywords))

    def test_new_native_and_owl_copy_has_real_arabic_catalog_bindings(self):
        for language in ('ar', 'ar_001'):
            translations = catalog(language)
            for relative in ('views/retention_views.xml', 'static/src/media_gallery.xml'):
                root = ET.parse(ADDON / relative)
                is_owl = relative.startswith('static/')
                records = list(root.iter('record')) if not is_owl else [root.getroot()]
                for record in records:
                    if not is_owl and record.get('model') != 'ir.ui.view':
                        continue
                    reference = 'code:addons/baseer_bwork_admin/static/src/media_gallery.xml:0' if is_owl else 'model_terms:ir.ui.view,arch_db:baseer_bwork_admin.' + record.get('id')
                    arch = record if is_owl else record.find("field[@name='arch']")
                    if arch is None:
                        continue
                    for node in arch.iter():
                        labels = [node.get(k) for k in ('string', 'confirm', 'help', 'aria-label', 'alt')]
                        labels += [(node.text or '').strip(), (node.tail or '').strip()]
                        for label in labels:
                            if not label or not re.search('[A-Za-z]', label):
                                continue
                            self.assertIn(label, translations, (language, label))
                            translated, block = translations[label]
                            self.assertRegex(translated, '[\u0600-\u06ff]')
                            self.assertIn('#: ' + reference, block)
                            self.assertEqual(translated.count('%s'), label.count('%s'))
            for mode in ('attachments', 'messages_and_attachments', 'expired_uploads'):
                for model in ('wizard', 'run'):
                    expected = f'model:ir.model.fields.selection,name:baseer_bwork_admin.selection__baseer_bwork_retention_{model}__mode__{mode}'
                    self.assertTrue(any('#: ' + expected in block for _, block in translations.values()), expected)

    def test_overview_hides_new_and_css_is_feature_scoped(self):
        root = ET.parse(ADDON / 'views/admin_views.xml')
        form = root.find(".//record[@id='console_form']/field[@name='arch']/form")
        self.assertEqual(form.get('create'), '0')
        self.assertEqual(len(form.findall(".//div[@class='o_bwork_admin_kpi']")), 3)
        css = (ADDON / 'static/src/media_gallery.scss').read_text(encoding='utf-8')
        self.assertIn('.o_bwork_admin_console, .o_bwork_retention_form {', css)
        self.assertIn('flex-wrap: wrap', css)
        self.assertIn('overflow-wrap: anywhere', css)
        self.assertNotIn('body {', css)
        self.assertNotIn('!important', css)


if __name__ == '__main__':
    unittest.main()
