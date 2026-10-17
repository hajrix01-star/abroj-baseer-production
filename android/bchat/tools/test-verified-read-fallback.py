#!/usr/bin/env python3
"""Regression checks for the BChat authenticated-read recovery path."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
GRADLE = (ROOT / 'app/build.gradle').read_text(encoding='utf-8')
PUSH_STATE = (ROOT / 'app/src/main/java/com/baseer/freshchat/BChatPushState.java').read_text(encoding='utf-8')


def method(name, return_type='void'):
    start = SOURCE.index('private ' + return_type + ' ' + name + '(')
    opening = SOURCE.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    return SOURCE[start:end]


class VerifiedReadFallbackContracts(unittest.TestCase):
    def test_only_authenticated_gets_can_use_webview_recovery(self):
        fallback = method('fetchVerifiedGetInWebView', 'boolean')
        self.assertIn('!"GET".equals(method)', fallback)
        self.assertIn("credentials:'same-origin'", fallback)
        self.assertIn("redirect:'manual'", fallback)
        self.assertIn('TextDecoder', fallback)
        self.assertIn('webV2GetFallbackBusy', fallback)
        self.assertNotIn('getCookie(', fallback)
        poll = method('pollVerifiedGetFallback')
        self.assertIn('expectedEpoch != epoch', poll)
        self.assertIn('new JSONArray("[" + value + "]").getString(0)', poll)
        self.assertIn('!(ORIGIN + path).equals(finalUrl)', poll)

    def test_port_failure_and_timeout_both_try_read_fallback(self):
        transport = method('fetchV2Internal')
        self.assertIn('|| webV2GetFallbackBusy ||', transport)
        self.assertGreaterEqual(transport.count('fetchVerifiedGetInWebView(method, path, maximum'), 2)
        self.assertIn('if (fetchVerifiedGetInWebView(method, path, maximum, currentWeb, currentPage,', transport)

    def test_all_authenticated_reads_bypass_transferred_message_port(self):
        direct = method('fetchV2ReadDirectlyInWebView', 'boolean')
        self.assertIn('V1_BOOTSTRAP.equals(path)', direct)
        self.assertIn('path.matches("/bchat/api/v2/', direct)
        self.assertIn('v2Busy', direct)
        self.assertIn('fetchVerifiedGetInWebView("GET", path, maximum', direct)
        fetch = method('fetchV2')
        self.assertIn('"GET".equals(method)', fetch)
        self.assertIn('payload == null', fetch)
        self.assertIn('fetchV2ReadDirectlyInWebView(path, callback)', fetch)
        self.assertLess(fetch.index('fetchV2ReadDirectlyInWebView(path, callback)'),
                        fetch.index('fetchV2Internal('))

    def test_initial_room_read_precedes_push_registration(self):
        verify = method('verifyV2')
        self.assertLess(verify.index('if (chatAllowed()) loadRooms();'),
                        verify.index('handler.post(this::maybeRegisterPush);'))
        direct = method('fetchVerifiedGetInWebView', 'boolean')
        self.assertIn('v2Busy = true;', direct)
        complete = method('completeVerifiedGetFallback')
        self.assertLess(complete.index('v2Busy = false;'), complete.index('callback.complete(statusCode, body);'))

    def test_push_registration_uses_one_scoped_direct_callback(self):
        registration = method('registerPushDirectlyInWebView', 'boolean')
        self.assertIn('V2_PUSH_REGISTER', registration)
        self.assertIn('postSmallFormDirectlyInWebView(V2_PUSH_REGISTER, "payload", payload, callback)', registration)
        self.assertNotIn('fetchV2(', registration)
        self.assertNotIn('postWebMessage', registration)
        direct = method('postSmallFormDirectlyInWebView', 'boolean')
        self.assertIn("method:'POST'", direct)
        self.assertIn("credentials:'same-origin'", direct)
        self.assertIn("redirect:'manual'", direct)
        self.assertIn("p.set('csrf_token'", direct)
        self.assertIn('new URLSearchParams', direct)
        self.assertIn('pollVerifiedGetFallback', direct)
        self.assertIn('V2_PUSH_REGISTER.equals(path)', direct)
        caller = method('maybeRegisterPush')
        self.assertIn('registerPushDirectlyInWebView(payload.toString()', caller)
        self.assertNotIn('fetchV2("POST", V2_PUSH_REGISTER', caller)
        self.assertIn('schedulePushRegistration();', caller)

    def test_header_keeps_account_menu_outside_company_label(self):
        screen = method('buildScreen')
        self.assertIn('FrameLayout headerCompanySlot', screen)
        self.assertIn('new LinearLayout.LayoutParams(0, dp(48), 1f)', screen)
        self.assertLess(screen.index('brandBar.addView(headerCompanySlot'),
                        screen.index('brandBar.addView(headerAttention'))
        self.assertNotIn('companyLabelWidth', screen)

    def test_recheck_preserves_confirmed_push_route_and_dialog_updates(self):
        self.assertIn('if (account.key.equals(state.getString(SCOPE, null))) return;', PUSH_STATE)
        resume_start = SOURCE.index('@Override protected void onResume()')
        resume_end = SOURCE.index('@Override public void onBackPressed()', resume_start)
        self.assertNotIn('BChatPushState.clearAccount(this)', SOURCE[resume_start:resume_end])
        settings = method('showNotificationSettings')
        self.assertIn('maybeRegisterPush();', settings)
        self.assertIn('refreshNotificationStatus(dialog, permissionGranted, enabled, channelMuted);', settings)
        refresh = method('refreshNotificationStatus')
        self.assertIn('dialog.setMessage(notificationStatusMessage(', refresh)
        self.assertIn('handler.postDelayed', refresh)
        self.assertNotIn('maybeRegisterPush()', refresh)

    def test_expired_web_session_keeps_offline_snapshots(self):
        recovery = method('recoverExpiredPrivateBridgeSession', 'boolean')
        self.assertNotIn('purgeHistory()', recovery)
        self.assertIn('showLoginForm()', recovery)
        self.assertIn('openWeb(LOGIN)', recovery)

    def test_login_screen_and_package_identify_the_candidate(self):
        screen = method('buildScreen')
        self.assertIn('bchat_login_release_footer', screen)
        self.assertIn('installedBChatReleaseName()', screen)
        self.assertIn("versionCode 87; versionName '0.7.71-qa-media-journey'", GRADLE)

    def test_recovery_candidate_disables_diagnostic_ui(self):
        self.assertIn("BCHAT_TRANSPORT_DIAGNOSTICS', 'false'", GRADLE)
        labels = method('transportReadLabel', 'String')
        self.assertIn('V2_BOOTSTRAP.equals(path)', labels)
        self.assertIn('V2_ROOMS.equals(path)', labels)
        self.assertIn('V1_BOOTSTRAP.equals(path)', labels)
        self.assertNotIn('url', labels.lower())
        self.assertIn('private void traceTransport(String stage)', SOURCE)
        self.assertIn('D14_" + label + "_SLOT_TIMEOUT', SOURCE)
        self.assertIn('D15_" + label + "_RESPONSE_REJECTED', SOURCE)
        self.assertIn('D16_" + label + "_CALLBACK_', SOURCE)
        self.assertIn('D10_V1_PROBE_', SOURCE)
        self.assertNotIn('getCookie(', SOURCE)

    def test_qa_push_trace_reveals_only_fixed_registration_stages(self):
        self.assertIn("BCHAT_PUSH_REGISTRATION_DIAGNOSTICS', 'true'", GRADLE)
        trace = method('tracePushRegistration')
        self.assertIn('BCHAT_PUSH_REGISTRATION_DIAGNOSTICS', trace)
        caller = method('maybeRegisterPush')
        for stage in ('P05_WAITING_FOR_READ', 'P08_DISPATCHED', 'P09_HTTP_',
                      'P10_HTTP_', 'P11_RESPONSE_EMPTY', 'P12_API_VERSION',
                      'P13_INSTALLATION_MISMATCH', 'P14_PUSH_FLAG_INVALID',
                      'P15_LINKED', 'P16_LOCAL_SAVE_REJECTED',
                      'P17_RESPONSE_MALFORMED', 'P18_DIRECT_PATH_UNAVAILABLE'):
            self.assertIn(stage, caller)
        self.assertNotIn(' + token', trace)
        self.assertNotIn(' + csrf', trace)
        self.assertNotIn(' + account', trace)


if __name__ == '__main__':
    unittest.main(verbosity=2)
