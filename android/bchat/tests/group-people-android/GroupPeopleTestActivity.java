package com.baseer.freshchat;

import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.os.Bundle;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Real standalone native Activity. All company/account/session/rights/server state below is
 * explicit synthetic Host data, not actual authentication, a journal or an HTTP transport. */
public final class GroupPeopleTestActivity extends Activity {
    static String language = "ar", surface = "picker";
    static boolean dark;
    static float scale = 1;
    static GroupPeopleProtocol.Mode mode = GroupPeopleProtocol.Mode.CREATE;
    BChatPeoplePickerPanel picker;
    BChatGroupEventsPanel events;
    PeopleHost peopleHost;
    EventsHost eventsHost;
    static final long COMPANY = 7, SELF = 41, ROOM = 17, MEMBER = 23;
    static final String STAMP = "2026-10-18T12:00:00Z";
    static final String AR_NAME = "عبدالرحمن بن عبدالله بن عبدالعزيز، فريق العمليات والتشغيل 👩🏽‍💻";
    static final String EN_NAME = "Alexandra Montgomery Operations and Customer Support Team 👩🏽‍💻";
    @Override protected void attachBaseContext(Context base) {
        Configuration config = new Configuration(base.getResources().getConfiguration());
        Locale locale = Locale.forLanguageTag(language); config.setLocale(locale); config.setLayoutDirection(locale); config.fontScale = scale;
        config.uiMode = (config.uiMode & ~Configuration.UI_MODE_NIGHT_MASK) | (dark ? Configuration.UI_MODE_NIGHT_YES : Configuration.UI_MODE_NIGHT_NO);
        config.densityDpi = Math.round(base.getResources().getDisplayMetrics().widthPixels * 160f / 360f);
        config.screenWidthDp = 360; config.smallestScreenWidthDp = 360;
        super.attachBaseContext(base.createConfigurationContext(config));
    }
    @Override public void onCreate(Bundle state) {
        setTheme(ChatAppearance.themeResource(this)); super.onCreate(state);
        TextView background = new TextView(this); background.setText("Isolated people component, fake Host");
        background.setBackgroundColor(UiPalette.canvas(this)); setContentView(background);
        if ("events".equals(surface)) {
            eventsHost = new EventsHost(); Map<Long, String> roster = new HashMap<>(); roster.put(51L, AR_NAME); roster.put(52L, EN_NAME);
            events = new BChatGroupEventsPanel(this, eventsHost, ROOM, MEMBER, roster); events.show();
        } else {
            peopleHost = new PeopleHost(mode); picker = new BChatPeoplePickerPanel(this, peopleHost,
                    GroupPeopleProtocol.Selection.empty(mode, COMPANY, SELF, Collections.emptyList()),
                    mode == GroupPeopleProtocol.Mode.ADD ? ROOM : 0, mode == GroupPeopleProtocol.Mode.ADD ? MEMBER : 0); picker.show();
        }
        // Keep the production Ui.decorateDialog width (328dp at the 360dp viewport).
        // Widening the Dialog to the viewport would hide actual wrapping failures.
    }
    Object panel() { return picker == null ? events : picker; }
    @Override protected void onPause() { if (picker != null) picker.pause(); if (events != null) events.pause(); super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (picker != null) picker.resume(); if (events != null) events.resume(); }
    @Override protected void onDestroy() { if (picker != null) picker.dismiss(); if (events != null) events.dismiss(); super.onDestroy(); }

    static final class PeopleHost implements BChatPeoplePickerPanel.Host {
        final GroupPeopleProtocol.Mode mode;
        boolean active = true, holdCandidates, holdRequests, accept = true, background;
        int account = 1, session = 1, global = 1, repository = 1, candidateStatus = 200, requestStatus = 200;
        long company = COMPANY, room, member;
        JSONObject requestOverride;
        final List<GroupPeopleProtocol.CandidateQuery> queries = new ArrayList<>();
        final List<BChatPeoplePickerPanel.Reply> candidateReplies = new ArrayList<>(), requestReplies = new ArrayList<>();
        final List<JSONObject> candidateBodies = new ArrayList<>(), requestBodies = new ArrayList<>();
        final List<GroupPeopleProtocol.Intent> requests = new ArrayList<>();
        PeopleHost(GroupPeopleProtocol.Mode mode) { this.mode = mode; room = mode == GroupPeopleProtocol.Mode.ADD ? ROOM : 0; member = room == 0 ? 0 : MEMBER; }
        public boolean current(long c, long r, long m) {
            return active && account == 1 && session == 1 && global == 1 && repository == 1 && c == company && r == room && m == member;
        }
        public boolean candidates(GroupPeopleProtocol.CandidateQuery query, BChatPeoplePickerPanel.Reply reply) {
            if (!current(query.companyId, room, member)) return false;
            queries.add(query); JSONObject body = directory(query); candidateReplies.add(reply); candidateBodies.add(body);
            if (!accept) return false;
            if (!holdCandidates) deliver(() -> reply.complete(candidateStatus, body)); return true;
        }
        public boolean request(GroupPeopleProtocol.Intent intent, BChatPeoplePickerPanel.Reply reply) {
            if (!current(intent.companyId, intent.roomId, intent.membershipId)) return false;
            requests.add(intent); JSONObject body = requestOverride == null ? acknowledgement(intent, false) : requestOverride;
            requestReplies.add(reply); requestBodies.add(body); if (!accept) return false;
            if (!holdRequests) deliver(() -> reply.complete(requestStatus, body)); return true;
        }
        private void deliver(Runnable callback) { if (background) new Thread(callback, "isolated-fake-people-reply").start(); else callback.run(); }
    }
    static JSONObject directory(GroupPeopleProtocol.CandidateQuery query) {
        try {
            JSONArray rows = new JSONArray(); long next;
            if (query.text.equals("filtered") && query.afterUserId == 0) next = 400;
            else {
                int start = query.afterUserId > 0 ? (int) query.afterUserId + 1 : query.text.equals("more") ? 200 : 100;
                int count = query.afterUserId == 139 ? 9 : query.afterUserId >= 400 || query.text.equals("more") ? 1 : 40;
                for (int i = 0; i < count; i++) rows.put(new JSONObject().put("user_id", start + i).put("name", i % 2 == 0 ? AR_NAME : EN_NAME));
                next = query.afterUserId == 0 && count == 40 ? start + count - 1 : 0;
            }
            return new JSONObject().put("api_version", 2).put("users", rows).put("next_after_user_id", next == 0 ? JSONObject.NULL : next);
        } catch (Exception invalid) { throw new AssertionError(invalid); }
    }
    static JSONObject acknowledgement(GroupPeopleProtocol.Intent intent, boolean replayed) {
        try {
            JSONObject body = new JSONObject().put("api_version", 2).put("room_id", ROOM).put("replayed", replayed);
            if (intent.mode == GroupPeopleProtocol.Mode.ADD) {
                JSONArray ids = new JSONArray(); for (long id : intent.userIds) ids.put(id);
                return body.put("client_uuid", intent.clientUuid).put("added_user_ids", ids);
            }
            body.put("membership_id", MEMBER);
            if (intent.mode == GroupPeopleProtocol.Mode.DIRECT) body.put("created", false).put("client_uuid", intent.clientUuid)
                    .put("peer", new JSONObject().put("user_id", intent.userIds.get(0)).put("name", AR_NAME));
            return body;
        } catch (Exception invalid) { throw new AssertionError(invalid); }
    }
    static final class EventsHost implements BChatGroupEventsPanel.Host {
        boolean active = true, hold, accept = true, background;
        int status = 200, firstCount = 12;
        long room = ROOM, member = MEMBER;
        JSONObject override;
        final List<GroupPeopleProtocol.EventsQuery> queries = new ArrayList<>();
        final List<BChatGroupEventsPanel.Reply> replies = new ArrayList<>();
        final List<JSONObject> bodies = new ArrayList<>();
        public boolean current(long r, long m) { return active && r == room && m == member; }
        public boolean load(GroupPeopleProtocol.EventsQuery query, BChatGroupEventsPanel.Reply reply) {
            if (!current(query.roomId, query.membershipId)) return false;
            queries.add(query); JSONObject body = override == null ? eventPage(query, query.beforeId == 0 ? firstCount : 2) : override;
            replies.add(reply); bodies.add(body); if (!accept) return false;
            if (!hold) { if (background) new Thread(() -> reply.complete(status, body), "isolated-fake-events-reply").start(); else reply.complete(status, body); }
            return true;
        }
    }
    static JSONObject eventPage(GroupPeopleProtocol.EventsQuery query, int count) {
        try {
            JSONArray rows = new JSONArray(); long start = query.beforeId == 0 ? 150 : query.beforeId - 1;
            for (int i = 0; i < count; i++) {
                GroupPeopleProtocol.Action action = GroupPeopleProtocol.Action.values()[i % 12];
                JSONObject metadata = new JSONObject().put("unused", "PRIVATE_METADATA_NOT_RENDERED");
                if (action == GroupPeopleProtocol.Action.ADD_MEMBERS) metadata.put("user_ids", new JSONArray().put(53).put(54));
                rows.put(new JSONObject().put("id", start - i).put("action", action.wire).put("actor_user_id", 51)
                        .put("actor_membership_id", JSONObject.NULL).put("target_user_id", i % 2 == 0 ? 52 : JSONObject.NULL)
                        .put("metadata", metadata).put("created_at", STAMP));
            }
            return new JSONObject().put("api_version", 2).put("room_id", ROOM).put("membership_id", MEMBER)
                    .put("audit_started_at", "2026-10-17T10:00:00Z").put("historical_actions_backfilled", false)
                    .put("events", rows).put("next_before_id", query.beforeId == 0 && count > 0 ? start - count + 1 : JSONObject.NULL);
        } catch (Exception invalid) { throw new AssertionError(invalid); }
    }
}
