#!/usr/bin/env python3
"""Static contracts for the authenticated BChat login brand presentation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'app/src/main/java/com/baseer/freshchat'


class LoginBrandContracts(unittest.TestCase):
    def test_supplied_vector_mark_is_rendered_without_recoloring(self):
        mark = (JAVA / 'EntryMarkView.java').read_text(encoding='utf-8')
        login_brand = (JAVA / 'LoginBrandView.java').read_text(encoding='utf-8')
        vector = (ROOT / 'app/src/main/res/drawable/bchat_mark_hq.xml').read_text(encoding='utf-8')
        master = (ROOT / 'app/src/main/res/raw/bchat_mark_hq.svg').read_text(encoding='utf-8')
        self.assertIn('R.drawable.bchat_mark_hq', mark)
        self.assertIn('android:pathData', vector)
        self.assertIn('viewBox="0 0 2048 2048"', master)
        self.assertIn('original.draw(canvas)', mark)
        self.assertNotIn('BitmapFactory', mark)
        self.assertNotIn('setColorFilter', mark + login_brand)
        self.assertNotIn('setTint', mark + login_brand)

    def test_brand_is_static_with_one_subtle_ambient_shadow(self):
        login_brand = (JAVA / 'LoginBrandView.java').read_text(encoding='utf-8')
        self.assertIn('new ShadowView(context)', login_brand)
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
        self.assertIn('BidiFormatter.getInstance(AppLocale.rtl(this)).unicodeWrap', identity)
        self.assertIn('nativeForm.setFillViewport(false)', identity)
        self.assertIn('new ScrollView.LayoutParams(-1, -2)', identity)
        self.assertIn('loginReleaseFooter.setVisibility(View.VISIBLE)', identity)
        self.assertIn('loginReleaseFooter.setVisibility(View.GONE)', identity)
        self.assertNotIn('bchat_login_tagline', identity)
        self.assertNotIn('footerSpacer', identity)
        self.assertIn("versionCode 81; versionName '0.7.65-qa-media-ack-recovery'", build)
        for path in ('values/strings.xml', 'values-ar/strings.xml', 'values-en/strings.xml'):
            strings = (ROOT / 'app/src/main/res' / path).read_text(encoding='utf-8')
            self.assertIn('name="bchat_login_release_footer"', strings)
            self.assertIn('name="bchat_login_release_date"', strings)
            self.assertIn('•', strings)


if __name__ == '__main__':
    unittest.main(verbosity=2)
