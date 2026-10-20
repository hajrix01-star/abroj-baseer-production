"""Source contracts for the BWork visual adaptation of Rocket.Chat measurements."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "app/src/main/java/com/baseer/bwork/legacy"
UI = (JAVA / "Ui.java").read_text(encoding="utf-8")
ACTIVITY = (JAVA / "BWorkIdentityActivity.java").read_text(encoding="utf-8")


class RocketVisualContracts(unittest.TestCase):
    def test_shared_chat_tokens_have_one_owner(self):
        for token in (
            "CHAT_TIME_SP = 13",
            "CHAT_HEADER_TITLE_SP = 16",
            "CHAT_TEXT_LINE_DP = 22",
            "ROOM_TITLE_SP = 17",
            "ROOM_ROW_MIN_DP = 75",
            "ROOM_AVATAR_DP = 48",
        ):
            self.assertIn(token, UI)

    def test_room_rows_expand_with_accessibility_font_scale(self):
        self.assertIn("getResources().getConfiguration().fontScale", ACTIVITY)
        self.assertIn("setMinimumHeight(Ui.dp(this, Ui.ROOM_ROW_MIN_DP * Math.max(1f, fontScale)))", ACTIVITY)
        self.assertIn("dp(Ui.ROOM_AVATAR_DP)", ACTIVITY)
        self.assertIn("Ui.ROOM_TITLE_SP", ACTIVITY)
        self.assertIn("Ui.CHAT_TIME_SP, Ui.MUTED", ACTIVITY)
        self.assertIn("new LinearLayout.LayoutParams(dp(48), dp(48))", ACTIVITY)
        self.assertIn("new LinearLayout.LayoutParams(-1, dp(48))", ACTIVITY)

    def test_bubbles_and_composer_retain_native_features(self):
        self.assertIn("new Ui.ReplySwipeLayout", ACTIVITY)
        self.assertIn("Ui.CHAT_TEXT_LINE_DP", ACTIVITY)
        self.assertIn("Ui.CHAT_TIME_SP, Ui.MUTED", ACTIVITY)
        self.assertIn("chooseConnectedMedia()", ACTIVITY)
        self.assertIn("toggleConnectedVoice()", ACTIVITY)
        self.assertIn("new LinearLayout.LayoutParams(dp(48), dp(48))", ACTIVITY)
        self.assertIn("new TouchDelegate(hit, stamp)", ACTIVITY)
        self.assertIn("new LinearLayout.LayoutParams(0, -2, 1)", ACTIVITY)

    def test_inbox_tools_are_compact_but_still_accessible(self):
        self.assertIn("roomSearchSurface.setVisibility(View.GONE)", ACTIVITY)
        self.assertIn("roomSearchButton.setOnClickListener(v -> toggleRoomSearch())", ACTIVITY)
        self.assertIn("roomPendingButton.setOnClickListener(v -> showGlobalPending(0))", ACTIVITY)
        self.assertIn("roomPendingButton.setVisibility(hasPending ? View.VISIBLE : View.GONE)", ACTIVITY)
        self.assertIn("roomSearchInput.requestFocus()", ACTIVITY)
        self.assertIn("keyboard.showSoftInput(roomSearchInput", ACTIVITY)

    def test_room_header_alignment_and_pending_review_are_not_duplicated(self):
        self.assertIn("chatTitle.setGravity(roomTextGravity | Gravity.CENTER_VERTICAL)", ACTIVITY)
        self.assertIn("roomSubtitle.setGravity(roomTextGravity | Gravity.CENTER_VERTICAL)", ACTIVITY)
        self.assertIn('if (pending != null || stale != null) chatNotice.setText("")', ACTIVITY)
        self.assertIn("pendingActionsRow.setVisibility(pending == null ? View.GONE : View.VISIBLE)", ACTIVITY)
        self.assertIn("stalePendingButton.setVisibility(stale == null ? View.GONE : View.VISIBLE)", ACTIVITY)

    def test_previous_order_share_is_only_reformatted_for_display(self):
        self.assertIn("previousOrderShareCard(body, contentWidth)", ACTIVITY)
        self.assertIn("View orderCard = offlineHistory ? null", ACTIVITY)
        self.assertIn("bubble.addView(orderCard, new LinearLayout.LayoutParams(contentWidth, -2))", ACTIVITY)
        self.assertIn("getString(R.string.order_share_heading", ACTIVITY)
        self.assertIn("getString(R.string.order_share_total", ACTIVITY)
        self.assertIn("lines[i].trim(), 14, Ui.INK, false", ACTIVITY)
        self.assertIn("lines[totalIndex].trim(), 15, Ui.INK, true", ACTIVITY)
        self.assertIn("showMessageActions(v, room, id, authorName, replyBody, body", ACTIVITY)


if __name__ == "__main__":
    unittest.main()
