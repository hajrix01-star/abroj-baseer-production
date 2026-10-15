#!/usr/bin/env python3
"""Source contracts only: these do not execute Android layout, touch or lifecycle behavior."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'app/src/main/java/com/baseer/freshchat/MainActivity.java').read_text()
MENU = (ROOT / 'app/src/main/java/com/baseer/freshchat/AnchoredMenu.java').read_text()


STRINGS = {node.text.strip('"'): node.attrib['name'] for node in ET.parse(ROOT / 'app/src/main/res/values-ar/strings.xml').getroot() if node.tag == 'string'}
def label(value):
    return 's(R.string.' + STRINGS[value] + ')'


def section(start, end):
    return SOURCE[SOURCE.index(start):SOURCE.index(end, SOURCE.index(start))]


class MenuSourceContracts(unittest.TestCase):
    def test_both_toolbar_buttons_pass_actual_tapped_view(self):
        self.assertIn('this::showInboxMenu', SOURCE)
        self.assertIn('anchor -> showChatMenu(anchor, co, cv)', SOURCE)
        self.assertIn('button.setOnClickListener(open::accept)', SOURCE)

    def test_main_overflow_is_no_longer_alert_dialog(self):
        block = section('private void showInboxMenu(View anchor)', 'private void updateInbox()')
        self.assertIn('overflowMenu.show(anchor,', block)
        self.assertNotIn('new AlertDialog', block)

    def test_chat_and_group_share_same_anchored_surface(self):
        block = section('private void showChatMenu(View anchor', 'private void copyChatTranscript')
        self.assertIn('overflowMenu.show(anchor,', block)
        self.assertNotIn('.setItems(', block)
        self.assertIn('demoMembers(co, cv)', block)

    def test_menu_surface_does_not_dim_or_title_like_a_modal(self):
        self.assertIn('new PopupWindow(scroll, -2, -2, true)', MENU)
        self.assertNotIn('AlertDialog', MENU)
        self.assertNotIn('FLAG_DIM_BEHIND', MENU)
        self.assertNotIn('setTitle(', MENU)

    def test_rtl_edge_and_row_alignment_are_anchor_relative(self):
        self.assertIn('showAsDropDown(source, 0, Ui.dp(activity, 4), Gravity.END)', MENU)
        self.assertIn('row.setLayoutDirection(anchor.getLayoutDirection())', MENU)
        self.assertIn('Gravity.START | Gravity.CENTER_VERTICAL', MENU)
        self.assertNotIn('Shift · الوردية', SOURCE)

    def test_minimum_48dp_targets_and_wrapping_text(self):
        self.assertIn('row.setMinimumHeight(Ui.dp(activity, 48))', MENU)
        self.assertIn('button.setLayoutParams(p(d(48), d(48)))', SOURCE)
        self.assertNotIn('setSingleLine', MENU)
        self.assertNotIn('setMaxLines', MENU)

    def test_narrow_short_and_keyboard_windows_have_scroll_bounds(self):
        for required in ('new ScrollView(activity)', 'getWindowVisibleDisplayFrame(visible)',
                         'Math.min(Ui.dp(activity, 288)', 'getMaxAvailableHeight(anchor,',
                         'View.MeasureSpec.AT_MOST', 'SOFT_INPUT_ADJUST_RESIZE'):
            self.assertIn(required, MENU)

    def test_outside_touch_back_and_detach_dismiss(self):
        self.assertIn('setOutsideTouchable(true)', MENU)
        self.assertIn('onViewDetachedFromWindow(View view) { if (popup == window) dismiss(); }', MENU)
        self.assertIn('if (overflowMenu != null && overflowMenu.dismiss()) return;', SOURCE)

    def test_navigation_pause_destroy_invalidate_popup_and_child_dialog(self):
        for block in (section('protected void onPause()', 'protected void onSaveInstanceState'),
                      section('private LinearLayout base(', 'private void spacer('),
                      SOURCE[SOURCE.index('protected void onDestroy()'):]):
            self.assertIn('dismissMenuContext()', block)
        self.assertIn('menuContextEpoch++;', SOURCE)
        self.assertIn('menuDialog.dismiss()', SOURCE)

    def test_callbacks_fence_replaced_pages_and_old_windows(self):
        self.assertIn('popup != window || revision != pageRevision', MENU)
        self.assertIn('if (!isCurrent()) { dismiss(); return; }', MENU)
        self.assertIn('if (!entry.keepOpen) dismiss();', MENU)

    def test_context_contains_screen_root_company_conversation_and_epoch(self):
        block = section('private AnchoredMenu.Scope menuScope(', 'private void dismissMenuContext(')
        for required in ('menuHostActive', 'epoch == menuContextEpoch', 'originalRoot == root',
                         'Objects.equals(originalScreen, screen)', 'Objects.equals(co, companyId)',
                         'Objects.equals(cv, conversationId)', 'anchor.isAttachedToWindow()'):
            self.assertIn(required, block)

    def test_filter_subpage_reuses_one_window_and_retains_list(self):
        block = section('private void showInboxFilters(', 'private void updateInbox()')
        self.assertIn('overflowMenu.replace(', block)
        self.assertIn('filter = choice[1]; updateInbox();', block)
        self.assertNotIn('showList()', block)
        self.assertIn('popup.update(anchor,', MENU)

    def test_nonconversation_sections_do_not_offer_conversation_filter(self):
        self.assertIn('if ("list".equals(screen)) entries.add(AnchoredMenu.Entry.page(' + label('تصفية المحادثات'), SOURCE)

    def test_unavailable_features_are_disabled_not_fake_actions(self):
        for title in ('الوردية · بعد ربط الخادم', 'المؤشرات · بعد ربط الخادم',
                      'المهام المرتبطة · بعد الربط', 'طلبات الشراء المرتبطة · بعد الربط'):
            self.assertIn('AnchoredMenu.Entry.disabled(' + label(title) + ')', SOURCE)
        self.assertIn('row.setEnabled(entry.action != null)', MENU)
        self.assertIn('if (entry.action != null) {', MENU)

    def test_chat_actions_keep_captured_scope(self):
        block = section('private void showChatMenu(View anchor', 'private void buildChatSearchBar')
        for required in ('copyChatTranscript(co, cv, scope)', 'settings.mute(co, cv,',
                         'showNotificationTest(co, cv, scope)', 'if(scope.isCurrent())saveTranscript(co,cv,scope)' ):
            self.assertIn(required, block)
        self.assertIn('new BoundedTextWriter(128*1024)', block)
        self.assertIn('targetStore.writeConversationTranscript(co,cv,writer,labels)', block)
        self.assertIn('transcriptFuture=queryOperation', block)
        notification = section('private void showNotificationTest(', 'private void requestNotificationTest')
        self.assertEqual(notification.count('if (scope.isCurrent()) requestNotificationTest(co, cv,'), 2)
        self.assertIn('showMenuDialog(dialog, scope)', notification)

    def test_destructive_confirmation_and_draft_persistence_remain(self):
        self.assertIn('confirmLocalDelete', SOURCE)
        self.assertIn('setPositiveButton(' + label('حذف محلي'), SOURCE)
        self.assertIn('persistDraft();', section('protected void onPause()', 'protected void onSaveInstanceState'))
        self.assertIn('persistDraft();', section('private void showChat(', 'private void renderHistory('))


if __name__ == '__main__':
    unittest.main(verbosity=2)
