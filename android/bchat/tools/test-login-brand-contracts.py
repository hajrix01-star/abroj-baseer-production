#!/usr/bin/env python3
"""Static contracts for the authenticated BChat login brand presentation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/baseer/freshchat'


class LoginBrandContracts(unittest.TestCase):
    def test_original_mark_is_reused_without_recoloring(self):
        mark = (JAVA / 'EntryMarkView.java').read_text(encoding='utf-8')
        login_brand = (JAVA / 'LoginBrandView.java').read_text(encoding='utf-8')
        self.assertIn('R.drawable.baseer_mark_b', mark)
        self.assertIn('setDrawShadow(false)', login_brand)
        self.assertNotIn('setColorFilter', mark + login_brand)
        self.assertNotIn('setTint', mark + login_brand)

    def test_brand_is_static_with_one_subtle_ambient_shadow(self):
        login_brand = (JAVA / 'LoginBrandView.java').read_text(encoding='utf-8')
        self.assertIn('setDrawShadow(false)', login_brand)
        self.assertIn('shadow.setAlpha(.22f);', login_brand)
        self.assertIn('mark.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO)', login_brand)
        self.assertNotIn('ValueAnimator', login_brand)
        self.assertNotIn('onVisibilityAggregated', login_brand)
        self.assertNotIn('setTranslationY(', login_brand)
        self.assertNotIn('setRotation(', login_brand)

    def test_login_has_only_brand_controls_and_release_footer(self):
        identity = (JAVA / 'OdooIdentityActivity.java').read_text(encoding='utf-8')
        build = (ROOT / 'app/build.gradle').read_text(encoding='utf-8')
        self.assertIn('new LoginBrandView(this)', identity)
        self.assertIn('bchat_login_release_footer', identity)
        self.assertIn('bchat_login_release_date', identity)
        self.assertIn('installedBChatReleaseName()', identity)
        self.assertNotIn('bchat_login_tagline', identity)
        self.assertNotIn('footerSpacer', identity)
        self.assertIn("versionCode 77; versionName '0.7.61-qa-brand-motion'", build)
        for path in ('values/strings.xml', 'values-ar/strings.xml', 'values-en/strings.xml'):
            strings = (ROOT / 'app/src/main/res' / path).read_text(encoding='utf-8')
            self.assertIn('name="bchat_login_release_footer"', strings)
            self.assertIn('name="bchat_login_release_date"', strings)
            self.assertIn('•', strings)


if __name__ == '__main__':
    unittest.main(verbosity=2)
