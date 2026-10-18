package com.baseer.freshchat;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.view.WindowManager;
import android.widget.TextView;
import com.baseer.freshchat.sync.AccountScope;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real native Activity lifecycle; the production app Activity and network are intentionally absent. */
public final class ReceiptDetailsTestActivity extends Activity {
    static final AccountScope ACCOUNT = new AccountScope("https://receipt-details.invalid", "isolated_receipts", 7);
    static final long ROOM = 11, MEMBER = 22, MESSAGE = 33, GENERATION = 44;
    static String language = "ar";
    static boolean dark;
    static float scale = 1;
    static int viewportDp = 360;
    BChatReceiptDetailsPanel panel;
    FakeHost host;

    @Override protected void attachBaseContext(Context base) {
        Configuration config = new Configuration(base.getResources().getConfiguration());
        Locale locale = Locale.forLanguageTag(language);
        config.setLocale(locale); config.setLayoutDirection(locale); config.fontScale = scale;
        config.uiMode = (config.uiMode & ~Configuration.UI_MODE_NIGHT_MASK)
                | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
        // Only this Activity: 320px at density142 is 360.56dp. No device wm/global changes.
        config.densityDpi = Math.round(base.getResources().getDisplayMetrics().widthPixels * 160f / viewportDp);
        config.screenWidthDp = viewportDp; config.smallestScreenWidthDp = viewportDp;
        super.attachBaseContext(base.createConfigurationContext(config));
    }
    @Override public void onCreate(Bundle state) {
        setTheme(ChatAppearance.themeResource(this)); super.onCreate(state);
        TextView root = new TextView(this); root.setText("Isolated receipt details component test");
        root.setBackgroundColor(UiPalette.canvas(this)); setContentView(root);
        host = new FakeHost();
        panel = new BChatReceiptDetailsPanel(this, host, ACCOUNT, ROOM, MEMBER, MESSAGE, GENERATION); panel.show();
        AlertDialog dialog = ReceiptDetailsInstrumentation.field(panel, "dialog", AlertDialog.class);
        dialog.getWindow().setLayout(getResources().getDisplayMetrics().widthPixels, WindowManager.LayoutParams.WRAP_CONTENT);
    }
    @Override protected void onPause() { if (panel != null) panel.pause(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (panel != null) panel.resume(); }
    @Override protected void onDestroy() { if (panel != null) panel.dismiss(); super.onDestroy(); }

    /** HTTP-shaped fakes, not proof of a backend, authorization, delivery or SQLite operation. */
    static final class FakeHost implements BChatReceiptDetailsPanel.Host {
        AccountScope account = ACCOUNT;
        long room = ROOM, member = MEMBER, message = MESSAGE, generation = GENERATION;
        final List<Long> afterIds = new ArrayList<>();
        boolean hold, dispatch = true, background;
        int status = 200, firstCount = 3;
        JSONObject override;
        BChatReceiptDetailsPanel.Reply heldReply;
        JSONObject heldBody;
        public AccountScope account() { return account; }
        public boolean current(AccountScope captured, long roomId, long membershipId, long messageId, long binding) {
            return account != null && captured.key.equals(account.key) && roomId == room && membershipId == member
                    && messageId == message && binding == generation;
        }
        public boolean load(long after, BChatReceiptDetailsPanel.Reply reply) {
            afterIds.add(after);
            if (!dispatch) return false;
            JSONObject body = override != null ? override : response(after, after == 0 ? firstCount : 2, after == 0);
            if (hold) { heldReply = reply; heldBody = body; }
            else if (background) new Thread(() -> reply.complete(status, body), "isolated-fake-receipt-reply").start();
            else reply.complete(status, body);
            return true;
        }
    }
    static JSONObject response(long after, int count, boolean more) {
        try {
            JSONArray rows = new JSONArray();
            for (int index = 1; index <= count; index++) {
                String name = index == 1 ? "عبدالرحمن بن عبدالله، فريق المشتريات والتشغيل"
                        : index == 2 ? "User" : "Alexandra Montgomery Operations Team " + index;
                rows.put(new JSONObject().put("id", after == 0 ? 100 + index : after + index)
                        .put("user_id", 500 + index).put("user_name", name)
                        .put("delivered_at", index == 3 ? JSONObject.NULL : "2026-10-18 01:02:03")
                        .put("read_at", index == 1 ? "2026-10-18 01:02:03" : JSONObject.NULL));
            }
            return new JSONObject().put("api_version", 2).put("room_id", ROOM).put("membership_id", MEMBER)
                    .put("message_id", MESSAGE).put("state", "sent")
                    .put("counts", new JSONObject().put("eligible", 100).put("delivered", 80).put("read", 20))
                    .put("receipts", rows).put("next_after_id", count == 0 ? 0 : after == 0 ? 100 + count : after + count)
                    .put("has_more", count > 0 && more);
        } catch (Exception invalid) { throw new AssertionError(invalid); }
    }
}
