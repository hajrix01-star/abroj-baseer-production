#!/usr/bin/env python3
"""Regression checks for the BChat authenticated-read recovery path."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
GRADLE = (ROOT / 'app/build.gradle').read_text(encoding='utf-8')


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

    def test_expired_web_session_keeps_offline_snapshots(self):
        recovery = method('recoverExpiredPrivateBridgeSession', 'boolean')
        self.assertNotIn('purgeHistory()', recovery)
        self.assertIn('showLoginForm()', recovery)
        self.assertIn('openWeb(LOGIN)', recovery)

    def test_login_screen_and_package_identify_the_candidate(self):
        screen = method('buildScreen')
        self.assertIn('bchat_installed_version', screen)
        self.assertIn('installedBChatVersion()', screen)
        self.assertIn("versionCode 66; versionName '0.7.50-qa-direct-read-recovery'", GRADLE)

    def test_recovery_candidate_keeps_diagnostics_off_for_user_acceptance(self):
        self.assertIn("BCHAT_TRANSPORT_DIAGNOSTICS', 'false'", GRADLE)
        self.assertIn('private void traceTransport(String stage)', SOURCE)
        self.assertIn('D05_V2_SLOT_TIMEOUT', SOURCE)
        self.assertIn('D06_V2_RESPONSE_REJECTED', SOURCE)
        self.assertIn('D10_V1_PROBE_', SOURCE)
        self.assertNotIn('getCookie(', SOURCE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
