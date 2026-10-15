#!/usr/bin/env python3
"""Source/palette tripwires only. Native UI tests are a separate release gate."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/baseer/freshchat'
MAIN = (JAVA / 'MainActivity.java').read_text()


def method(name):
    start = re.search(r'private [\w<>]+ ' + name + r'\(', MAIN).start()
    opening = MAIN.index('{', start); depth = 1; end = opening + 1
    while depth:
        depth += (MAIN[end] == '{') - (MAIN[end] == '}'); end += 1
    return MAIN[start:end]


class EntryLayoutContracts(unittest.TestCase):
    def test_demo_default_is_signed_out_without_touching_store(self):
        settings = (JAVA / 'LocalSettings.java').read_text()
        self.assertIn('getBoolean("demo-entry-active", false)', settings)
        self.assertIn('if (!settings.demoSessionActive()) {', MAIN)
        self.assertIn('showEntry(); return;', MAIN)
        self.assertNotIn('demo-entry', (JAVA / 'ChatStore.java').read_text())

    def test_only_read_only_credential_shell_and_separate_demo_action(self):
        entry, field = method('showEntry'), method('entryField')
        self.assertNotIn('EditText', entry + field)
        self.assertNotIn('realLogin', entry)
        self.assertIn('entry_minimal_demo_login', entry)
        self.assertIn('new CheckBox(this)', entry)
        self.assertIn('enterDemo()', entry)
        self.assertIn('entry_minimal_notice', entry)
        self.assertIn('entry_password_sample', field)
        self.assertNotIn('putString', entry + field)
        self.assertNotIn('setInputType', entry + field)

    def test_real_account_component_is_separate_from_demo(self):
        manifest = ET.parse(ROOT/'app/src/main/AndroidManifest.xml').getroot()
        ns = '{http://schemas.android.com/apk/res/android}'
        permissions = {p.get(ns+'name') for p in manifest.findall('uses-permission')}
        self.assertIn('android.permission.INTERNET', permissions)
        self.assertIn('startActivity(new Intent(this, OdooIdentityActivity.class))', method('showEntry'))
        identity = (JAVA / 'OdooIdentityActivity.java').read_text()
        self.assertNotIn('ChatStore', identity.replace('offline demo store', ''))
        self.assertIn('credentials:\'same-origin\'', identity)
        self.assertIn('MIXED_CONTENT_NEVER_ALLOW', identity)
        self.assertFalse(manifest.find('application').findall('service'))

    def test_back_from_real_chat_root_does_not_sign_out(self):
        identity = (JAVA / 'OdooIdentityActivity.java').read_text()
        back = identity.split('@Override public void onBackPressed() {', 1)[1]
        back = back.split('@Override protected void onDestroy()', 1)[0]
        self.assertIn('accountMenu.dismiss()', back)
        self.assertIn('moveTaskToBack(true)', back)
        self.assertLess(back.index('moveTaskToBack(true)'), back.index('logout();'))

    def test_logout_is_confirmed_and_preserves_local_data(self):
        self.assertIn('setNegativeButton', method('confirmLogout'))
        self.assertIn('if (!beforeNavigation(this::exitDemo)) return;', method('exitDemo'))
        self.assertIn('setPositiveButton', method('confirmLogout'))
        exit = method('exitDemo')
        for operation in ('persistDraft()', 'persistPreview()', 'finishVoice(false)', 'stopAudio()', 'DemoNotifications.cancel(this)', 'showEntry()'):
            self.assertIn(operation, exit)
        for destructive in ('delete', '.clear()', 'reset', 'cancelPendingShare', 'setDraft('):
            self.assertNotIn(destructive, exit)

    def test_share_intent_is_deferred_until_demo_entry(self):
        entry = method('enterDemo')
        self.assertLess(entry.index('settings.demoSessionActive(true,'), entry.index('handleIncomingShare'))
        self.assertIn('store.pendingShare() != null', entry)
        self.assertIn('deferredEntryIntent == null ? getIntent() : deferredEntryIntent', entry)
        self.assertIn('out.putParcelable("deferredEntryIntent", pendingStartupIntent != null ? pendingStartupIntent : deferredEntryIntent)', MAIN)
        self.assertIn('if (isEntryDestination(intent)) deferredEntryIntent = new Intent(intent)', MAIN)
        self.assertIn('"entry".equals(old)) showEntry()', MAIN)

    def test_intrinsic_logo_and_separate_flexible_spacer(self):
        toolbar = method('addMainToolbar')
        self.assertIn('toolbar.addView(brand, p(-2, d(46)))', toolbar)
        self.assertIn('toolbar.addView(new View(this), new LinearLayout.LayoutParams(0, 1, 1))', toolbar)
        self.assertNotIn('Gravity.CENTER', toolbar)
        self.assertLess(toolbar.index('toolbar.addView(brand'), toolbar.index('overflowButton'))

    def test_rows_have_isolated_metadata_and_interface_alignment(self):
        row = method('conversationRow')
        self.assertIn('metadata = column(this)', row)
        self.assertIn('r.addView(metadata, p(-2, -2))', row)
        self.assertIn('name.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START)', row)
        self.assertIn('sub.setTextAlignment(View.TEXT_ALIGNMENT_VIEW_START)', row)
        self.assertIn('outer.addView(r, p(-1, -2))', row)
        self.assertNotIn('d(86))', row.split('outer.addView')[1])
        self.assertIn('store.unreadCount(c.companyId, c.id) > 99 ? "99+"', row)
        self.assertIn('s(R.string.unread_count, store.unreadCount(c.companyId, c.id))', row)

    def test_single_original_b_and_reduced_motion_lifecycle(self):
        entry = method('showEntry')
        self.assertIn('new EntryMarkView(this)', entry)
        self.assertNotIn('BChatWordmarkView', entry)
        self.assertIn('ValueAnimator.areAnimatorsEnabled()', method('startEntryMotion'))
        self.assertIn('entryMotionPlayed', method('startEntryMotion'))
        self.assertIn('entryMotion.cancel()', method('stopEntryMotion'))
        self.assertIn('out.putBoolean("entryMotionPlayed", entryMotionPlayed)', MAIN)
        self.assertIn('addOnGlobalFocusChangeListener', entry)
        self.assertIn('event.getActionMasked() == MotionEvent.ACTION_DOWN) stopEntryMotion()', MAIN)
        self.assertIn('return super.dispatchTouchEvent(event)', MAIN)
        self.assertIn('if (losingFocus) stopEntryMotion()', MAIN)
        self.assertIn('!entryWindowFocused', method('startEntryMotion'))
        self.assertIn('onViewDetachedFromWindow', entry)
        self.assertIn('observer.removeOnGlobalFocusChangeListener(focusObserver)', entry)
        self.assertIn('observer.removeOnGlobalLayoutListener(layoutObserver)', entry)
        mark = (JAVA/'EntryMarkView.java').read_text()
        self.assertIn('R.drawable.baseer_mark_b', mark)
        self.assertEqual(mark.count('canvas.drawBitmap('), 1)
        self.assertNotIn('setColorFilter', mark)

    def test_remember_demo_does_not_store_credentials(self):
        settings = (JAVA/'LocalSettings.java').read_text()
        self.assertIn('processDemoSession || values.getBoolean("demo-entry-active", false)', settings)
        self.assertIn('"demo-entry-active", active && remember', settings)
        self.assertIn('"remember-demo-entry", false', settings)
        self.assertNotIn('password', settings.lower())

    def test_time_obeys_device_setting_and_bidi_isolates(self):
        self.assertIn('DateFormat.getTimeFormat(this)', method('displayTime'))
        self.assertIn('AppLocale.name(this', method('displayTime'))
        self.assertNotIn('new SimpleDateFormat("HH:mm"', MAIN)

    def test_neutral_theme_does_not_modify_brand(self):
        ui = (JAVA/'Ui.java').read_text()
        self.assertIn('Color.rgb(36, 40, 45)', ui)
        self.assertIn('Color.rgb(244, 245, 247)', ui)
        wallpaper = ui[ui.index('static class Wallpaper'):]
        self.assertNotIn('onDraw', wallpaper)
        for folder in ('values-v29', 'values-v35'):
            self.assertIn('forceDarkAllowed">false', (ROOT/'app/src/main/res'/folder/'styles.xml').read_text())
        self.assertIn('setBackgroundColor(Color.WHITE)', method('addMainToolbar'))

    def test_readable_palette_contrast(self):
        def luminance(rgb):
            channels = [x/255 for x in rgb]
            channels = [x/12.92 if x <= .04045 else ((x+.055)/1.055)**2.4 for x in channels]
            return sum(x*y for x,y in zip(channels,(.2126,.7152,.0722)))
        def ratio(a,b):
            a,b = sorted((luminance(a),luminance(b)))
            return (b+.05)/(a+.05)
        for foreground in ((36,40,45),(94,101,110),(25,102,183)):
            self.assertGreaterEqual(ratio(foreground,(255,255,255)),4.5)
        self.assertGreaterEqual(ratio((94,101,110),(231,241,253)),4.5)

    def test_media_retention_and_bubble_width_guards_remain(self):
        self.assertNotIn('.delete(', method('cleanupAttachments'))
        bubble = method('messageBubble')
        for child in ('sender','body','quote','removed'):
            self.assertIn('bubble.addView('+child+', p(-2, -2))', bubble)

if __name__ == '__main__': unittest.main(verbosity=2)
