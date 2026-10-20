#!/usr/bin/env python3
"""Source contracts only; Android geometry, gestures and screenshots need device testing."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/bwork/legacy/MainActivity.java').read_text()


def method(name):
    start = re.search(r'private \w+ ' + re.escape(name) + r'\(', SOURCE).start()
    opening = SOURCE.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (SOURCE[end] == '{') - (SOURCE[end] == '}')
        end += 1
    return SOURCE[start:end]


class BottomNavigationContracts(unittest.TestCase):
    def test_only_main_list_and_modules_add_navigation(self):
        self.assertEqual(SOURCE.count('addMainSections();'), 2)
        for name in ('showList', 'showModule'):
            self.assertEqual(method(name).count('addMainSections();'), 1)

    def test_toolbar_has_no_section_navigation(self):
        self.assertNotIn('addMainSections', method('addMainToolbar'))
        for name in ('showList', 'showModule'):
            self.assertNotIn('addMainToolbar(); addMainSections();', method(name))

    def test_inbox_content_precedes_status_and_bottom_navigation(self):
        body = method('showList')
        self.assertLess(body.index('root.addView(inbox, new LinearLayout.LayoutParams(-1, 0, 1))'), body.index('demoBar(root, true)'))
        self.assertLess(body.index('demoBar(root, true)'), body.index('addMainSections()'))
        self.assertTrue(body.rstrip().endswith('addMainSections();\n    }'))

    def test_module_content_precedes_status_and_bottom_navigation(self):
        body = method('showModule')
        self.assertLess(body.index('root.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1))'), body.index('demoBar(root, true)'))
        self.assertLess(body.index('demoBar(root, true)'), body.index('addMainSections()'))
        self.assertTrue(body.rstrip().endswith('addMainSections();\n    }'))

    def test_navigation_is_a_root_sibling_not_scrolled_or_overlaid(self):
        body = method('addMainSections')
        self.assertIn('root.addView(tabs, p(-1, -2))', body)
        self.assertIn('LinearLayout tabs = row(this)', body)
        for forbidden in ('ScrollView', 'ListView', 'FrameLayout', 'setTranslationY', 'setY(', 'addFooterView'):
            self.assertNotIn(forbidden, body)
        self.assertIn('root = column(this)', method('base'))

    def test_no_navigation_inside_secondary_screens(self):
        for name in ('showChat', 'showPicker', 'showSharePreview', 'showSettings', 'showCreateGroup'):
            self.assertNotIn('addMainSections', method(name))
        self.assertNotIn('addMainSections', method('base'))

    def test_existing_order_labels_and_direction_are_preserved(self):
        self.assertIn('{{s(R.string.ui_065), "list"}, {s(R.string.ui_066), "orders"}, {s(R.string.ui_067), "tasks"}}', method('addMainSections'))
        ui = (ROOT / 'app/src/main/java/com/baseer/bwork/legacy/Ui.java').read_text()
        self.assertIn('l.setLayoutDirection(AppLocale.direction(c))', ui)
        for folder in ('values-ar', 'values-en'):
            strings = {node.attrib['name']: node.text for node in ET.parse(ROOT / 'app/src/main/res' / folder / 'strings.xml').getroot() if node.tag == 'string'}
            self.assertTrue(all(strings[key] for key in ('ui_065', 'ui_066', 'ui_067', 'selected_section')))

    def test_selected_state_and_accessibility_stay_localized(self):
        body = method('addMainSections')
        for token in ('choice[1].equals(mainSection)', 'tab.setSelected(selected)',
                      's(R.string.selected_section, choice[0])', 'clickable(tab)'):
            self.assertIn(token, body)

    def test_labels_can_wrap_and_targets_are_at_least_48dp(self):
        body = method('addMainSections')
        self.assertIn('tab.setMinHeight(d(48))', body)
        self.assertIn('new LinearLayout.LayoutParams(0, -2, 1)', body)
        for forbidden in ('setSingleLine', 'setMaxLines', 'setEllipsize'):
            self.assertNotIn(forbidden, body)

    def test_bottom_navigation_keeps_existing_system_bar_safe_theme(self):
        themes = ROOT / 'app/src/main/res'
        self.assertIn('windowOptOutEdgeToEdgeEnforcement">true', (themes / 'values-v35/styles.xml').read_text())
        self.assertNotIn('LAYOUT_HIDE_NAVIGATION', SOURCE)
        self.assertNotIn('setDecorFitsSystemWindows(false)', SOURCE)

    def test_screen_and_selected_section_survive_recreation(self):
        for token in ('saved.getString("mainSection", "list")', 'out.putString("mainSection", mainSection)',
                      '"orders".equals(old) || "tasks".equals(old)) showModule(old)',
                      'mainSection = "list";', 'mainSection = section;'):
            self.assertIn(token, SOURCE)

    def test_back_and_menu_context_contracts_remain(self):
        self.assertIn('if ("chat".equals(screen)) showList();', SOURCE)
        self.assertIn('if (overflowMenu != null && overflowMenu.dismiss()) return;', SOURCE)
        self.assertIn('dismissMenuContext()', method('base'))
        self.assertIn('anchor -> showChatMenu(anchor, co, cv)', SOURCE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
