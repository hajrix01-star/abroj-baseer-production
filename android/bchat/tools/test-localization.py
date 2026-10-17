#!/usr/bin/env python3
"""Translation and source contracts. These are not Android visual/runtime tests."""
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/baseer/freshchat'
RES = ROOT / 'app/src/main/res'
ARABIC = re.compile('[\u0600-\u06ff]')
LITERALS = re.compile(r'"(?:[^"\\]|\\.)*"')
FORMAT = re.compile(r'%(?:(\d+)\$)?([-#+ 0,(]*)(\d*)(?:\.(\d+))?([a-zA-Z%])')

def strings(folder):
    values = {}
    for path in sorted((RES / folder).glob('*.xml')):
        for item in ET.parse(path).getroot():
            if item.tag != 'string': continue
            if item.attrib['name'] in values: raise AssertionError('Duplicate string: ' + item.attrib['name'])
            values[item.attrib['name']] = item.text or ''
    return values

def source(name):
    return (JAVA / name).read_text(encoding='utf-8')

class LocalizationContracts(unittest.TestCase):
    def test_room_list_shows_every_authorized_company(self):
        room_list = source('OdooIdentityActivity.java').split('private void renderRooms() {', 1)[1]
        room_list = room_list.split('private void loadRooms()', 1)[0]
        self.assertNotIn('room.companyId != selectedChatCompanyId', room_list)
        self.assertIn('companyNameForId(room.companyId, "")', room_list)
        self.assertIn('labelColumn.addView(companyLabel, companySize)', room_list)
        self.assertIn('companyName.toLowerCase(Locale.ROOT).contains(query)', room_list)

    def test_complete_resource_key_parity(self):
        self.assertEqual(strings('values'), strings('values-ar'))
        self.assertEqual(set(strings('values')), set(strings('values-en')))
        self.assertGreater(len(strings('values-en')), 350)

    def test_bchat_brand_stays_latin_in_arabic_interface(self):
        for folder in ('values', 'values-ar'):
            catalogue = strings(folder)
            self.assertEqual(catalogue['auth_shell_brand'].strip('"'), 'BChat')
            self.assertIn('BChat', catalogue['auth_native_title'])
            self.assertNotIn('بيشات', ' '.join(catalogue.values()))

    def test_translations_are_nonempty_and_no_arabic_in_english_interface(self):
        for key, value in strings('values-en').items():
            if key != 'auth_native_ready': self.assertTrue(value.strip('" '), key)
            self.assertFalse(ARABIC.search(value), key)

    def test_positional_format_contracts_match(self):
        arabic, english = strings('values-ar'), strings('values-en')
        for key in arabic:
            self.assertEqual(sorted(FORMAT.findall(arabic[key])), sorted(FORMAT.findall(english[key])), key)
            for placeholder in FORMAT.findall(arabic[key]):
                self.assertTrue(placeholder[0] or placeholder[-1] == '%', key)
            self.assertEqual(arabic[key].count('\\n'), english[key].count('\\n'), key)

    def test_every_ui_reference_resolves(self):
        keys = set(strings('values'))
        for path in JAVA.glob('*.java'):
            for key in re.findall(r'R\.string\.(\w+)', path.read_text(encoding='utf-8')): self.assertIn(key, keys, f'{path.name}: {key}')

    def test_user_facing_classes_have_no_arabic_literals(self):
        for filename in ('MainActivity.java', 'Ui.java', 'AnchoredMenu.java', 'VoicePlayerView.java', 'AudioPlayback.java', 'DemoNotifications.java'):
            for literal in LITERALS.findall(source(filename)): self.assertFalse(ARABIC.search(literal), f'{filename}: {literal}')

    def test_user_facing_sinks_have_no_new_inline_english_sentences(self):
        # Technical identifiers, BChat/Chat, PDF, symbols and media digits are deliberate exceptions.
        allowed = {'BChat', 'Chat', 'PDF', '', '0/0', '↑', '↓', '✓', '▶', '1×', '⋮', '0:00 / --:--'}
        sink = re.compile(r'(?:set(?:Text|Hint|Title|Message|ContentDescription)|toast|text)\((?:this, |context, |activity, )?("(?:[^"\\]|\\.)*")')
        for filename in ('MainActivity.java','Ui.java','VoicePlayerView.java','AnchoredMenu.java','DemoNotifications.java'):
            for match in sink.finditer(source(filename)):
                literal = match.group(1)[1:-1]
                if re.search('[A-Za-z]', literal): self.assertIn(literal, allowed, f'{filename}: {literal}')

    def test_domain_diagnostic_catalogue_covers_all_arabic_errors(self):
        values = {value.strip('"').replace("\\'", "'").replace('\\n', '\n') for value in strings('values-ar').values()}
        for filename in ('AttachmentSupport.java','VoiceRecorder.java','AudioDiagnostic.java'):
            for literal in LITERALS.findall(source(filename)):
                if ARABIC.search(literal): self.assertIn(literal[1:-1], values, filename)
        self.assertIn('AppLocale.error(this, e.getMessage())', source('MainActivity.java'))
        self.assertIn('AppLocale.error(context, event.guidance())', source('AudioPlayback.java'))
        self.assertIn('AppLocale.error(getContext(), shown.guidance())', source('VoicePlayerView.java'))
        self.assertIn('resource == null || resource == 0 ? R.string.error_local_operation', source('AppLocale.java'))

    def test_locale_is_applied_before_activity_creation_and_persisted(self):
        main, prefs = source('MainActivity.java'), source('LocalSettings.java')
        self.assertIn('attachBaseContext(Context base) { super.attachBaseContext(AppLocale.wrap(base)); }', main)
        self.assertIn('"interface-language"', prefs)
        self.assertIn('.commit()', prefs)
        apply = main[main.index('private void applyLanguage('):main.index('private void showSoundSettings(')]
        for token in ('persistDraft(); persistPreview();', 'finishVoice(false)', 'stopAudio()', 'settings.language(selected)', 'recreate()'): self.assertIn(token, apply)
        self.assertLess(apply.index('persistDraft()'), apply.index('settings.language(selected)'))
        self.assertLess(apply.index('settings.language(selected)'), apply.index('recreate()'))

    def test_navigation_state_survives_recreation(self):
        main = source('MainActivity.java')
        for key in ('screen','mainSection','company','conversation','filter','listQuery','pickerQuery','pickerSharing','previewShareId','previewCompany','previewConversation','groupNameDraft','groupCompanyDraft'):
            self.assertRegex(main, r'saved\.get\w+\("' + key + r'"')
            self.assertRegex(main, r'out\.put\w+\("' + key + r'"')

    def test_restored_preview_loads_caption_and_selected_files_before_render(self):
        main = source('MainActivity.java')
        preview = main[main.index('private void showSharePreview()'):main.index('private void cleanupAttachments()')]
        self.assertIn('!pending.id.equals(previewShareId)', preview)
        self.assertIn('store.conversation(previewCompany, previewConversation)', preview)
        self.assertIn('if (previewText == null || previewEditor == null || previewMigrationBlocked) loadPreview(pending)', preview)
        self.assertLess(preview.index('loadPreview(pending)'), preview.index('base("preview"'))
        self.assertIn('prefs.getString("text", pending.text)', main)
        self.assertIn('if (ids.contains(file.id)) kept.add(file)', main)

    def test_picker_recreation_preserves_and_seeds_search(self):
        main = source('MainActivity.java')
        self.assertIn('else if ("picker".equals(old)) showPicker(pickerSharing, true)', main)
        self.assertIn('if (!restoreSelection) { pickerQuery = ""; pickerCompany = "all"; }', main)
        self.assertIn('q.setText(pickerQuery)', main)
        self.assertIn('showPicker(sharing, true)', main)

    def test_application_context_audio_and_notifications_are_localized(self):
        self.assertIn('this.context = AppLocale.wrap(context.getApplicationContext())', source('AudioPlayback.java'))
        notifications = source('DemoNotifications.java')
        self.assertIn('private static int lastResult', notifications)
        self.assertIn('static String status(Context context)', notifications)
        self.assertIn('context = AppLocale.wrap(context)', notifications)
        self.assertIn('setOnlyAlertOnce(true)', notifications)
        self.assertIn('existing.setName(AppLocale.s', notifications)

    def test_locale_direction_and_media_exceptions(self):
        self.assertIn('root.setLayoutDirection(AppLocale.direction(this))', source('MainActivity.java'))
        self.assertIn('t.setTextDirection(AppLocale.textDirection(c))', source('Ui.java'))
        self.assertIn('if (AppLocale.rtl(getContext()))', source('Ui.java'))
        self.assertIn('controls.setLayoutDirection(LAYOUT_DIRECTION_LTR)', source('VoicePlayerView.java'))
        self.assertIn('seek.setLayoutDirection(LAYOUT_DIRECTION_LTR)', source('VoicePlayerView.java'))
        self.assertIn('brand.setLayoutDirection(View.LAYOUT_DIRECTION_LTR)', source('MainActivity.java'))

    def test_store_is_platform_and_locale_independent(self):
        store = source('ChatStore.java')
        self.assertNotIn('AppLocale', store)
        self.assertNotIn('android.', store)
        main = source('MainActivity.java')
        self.assertIn('body = text(this, m.text', main)
        self.assertIn('store.writeConversationTranscript(co,cv,output,transcriptLabels())', main)
        self.assertIn('out.write(m.text+', store)
        self.assertRegex(store, r'out\.write\([^;]*m\.senderName')
        self.assertIn('Locale.ROOT', main)

    def test_audio_diagnostic_copy_is_bounded_and_dialog_dismisses(self):
        voice = source('VoicePlayerView.java')
        dialog = voice[voice.index('private void showPlaybackFailure()'):voice.index('protected void onDetachedFromWindow()')]
        self.assertIn('final String safeSummary = shown.summary()', dialog)
        self.assertIn('newPlainText(s(R.string.audio_code_label), safeSummary)', dialog)
        for forbidden in ('file.name', 'file.path', 'getMessage()', 'getDeviceId'): self.assertNotIn(forbidden, dialog)
        self.assertIn('if (!isAttachedToWindow()) return;', dialog)
        detach = voice[voice.index('protected void onDetachedFromWindow()'):]
        self.assertIn('failureDialog.dismiss(); failureDialog = null', detach)

    def test_current_changelog_and_real_language_choice(self):
        main = source('MainActivity.java')
        self.assertIn('this::showLanguageSettings', main)
        self.assertNotIn('R.string.ui_120', main)
        self.assertNotIn('R.string.ui_121', main)
        self.assertIn('R.string.whats_new_body', main)
        self.assertIn('getPackageInfo(getPackageName()', main)

    def test_employee_menu_has_its_own_real_version_and_changelog(self):
        employee = source('OdooIdentityActivity.java')
        self.assertIn('Ui.iconButton(this, "kebab", getString(R.string.bchat_account_menu))', employee)
        self.assertIn('this::showProfile', employee)
        self.assertIn('this::showAccountSettings', employee)
        self.assertIn('this::showAccountAbout', employee)
        self.assertIn('this::showLanguageSettings', employee)
        self.assertIn('getPackageInfo(getPackageName(), 0)', employee)
        self.assertIn('R.string.bchat_whats_new_body', employee)
        self.assertNotIn('R.string.whats_new_body', employee)
        for locale in ('values-ar', 'values-en'):
            copy = strings(locale)
            self.assertIn('BChat', copy['bchat_about_summary'])
            self.assertNotIn('لا يوجد اتصال', copy['bchat_whats_new_body'])
            self.assertNotIn('no Odoo connection', copy['bchat_whats_new_body'])

    def test_employee_profile_uses_one_localized_company_label_and_omits_empty_titles(self):
        employee = source('OdooIdentityActivity.java')
        profile = employee[employee.index('private void showProfile()'):
                           employee.index('private void showLanguageSettings()')]
        self.assertIn('localizedCompanyName(company)', profile)
        self.assertNotIn('company.optString("name")), 15, Ui.GREEN', profile)
        self.assertIn('if (jobs.length() > 0)', profile)
        self.assertNotIn('jobs.append(getString(R.string.bchat_profile_no_job))', profile)

if __name__ == '__main__': unittest.main(verbosity=2)
