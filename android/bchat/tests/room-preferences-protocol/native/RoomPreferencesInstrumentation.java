package com.baseer.freshchat;

import android.app.Instrumentation;
import android.content.Context;
import android.os.Build;
import android.os.Bundle;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import org.json.JSONObject;

/** Actual Android35 JSON text decoding/encoding plus production models; no Activity or transport. */
public final class RoomPreferencesInstrumentation extends Instrumentation {
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    @Override public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context = getContext();
            if (!"com.baseer.bchat.room.preferences.protocol.test".equals(context.getPackageName()))
                throw new IllegalStateException("Refusing non-test namespace");
            if (Build.VERSION.SDK_INT != 35) throw new IllegalStateException("Evidence requires Android35");
            int shared = RoomPreferencesCases.run();
            textCases();
            int total = shared + nativeChecks;
            JSONObject evidence = new JSONObject().put("schema", 1).put("passed", true).put("sdk", Build.VERSION.SDK_INT)
                    .put("assertions", total).put("shared_value_checks", shared).put("native_text_checks", nativeChecks)
                    .put("scope", "Production RoomPreferencesProtocol with real Android35 JSONObject/UTC; no store, HTTP, controller, FCM, UI or C17 completion");
            try (FileOutputStream out = new FileOutputStream(new File(context.getFilesDir(), "room-preferences-protocol-results.json"))) {
                out.write(evidence.toString(2).getBytes(StandardCharsets.UTF_8));
            }
            result.putString("stream", "PASS " + total + " actual Android35 room preference protocol assertions ("
                    + shared + " shared value + " + nativeChecks + " native JSON text); no storage/HTTP/controller/FCM\n");
            finish(0, result);
        } catch (Throwable error) {
            result.putString("stream", "FAIL " + error + " " + Arrays.toString(error.getStackTrace()) + "\n");
            finish(1, result);
        }
    }

    private int nativeChecks;
    private interface Action { void run() throws Exception; }
    private void check(boolean value, String why) { ++nativeChecks; if (!value) throw new AssertionError("Native JSON " + why); }
    private void rejected(Action action) throws Exception {
        try { action.run(); } catch (IllegalArgumentException expected) { ++nativeChecks; return; }
        throw new AssertionError("Native JSON invalid type accepted");
    }
    private RoomPreferencesProtocol.Snapshot parse(String body) throws Exception {
        return RoomPreferencesCases.fresh(new JSONObject(body));
    }
    private void textCases() throws Exception {
        String base = RoomPreferencesCases.response(1, null, false, false, false, false).toString();
        check(parse(base).revision == 1, "Real native string decode");
        check(new JSONObject(base).opt("revision") instanceof Integer, "Native small integer type observed");
        check(parse(base.replace("\"revision\":1", "\"revision\":2147483647")).revision == Integer.MAX_VALUE, "Int32 upper bound via raw JSON");
        for (String field : new String[]{"revision", "room_id", "membership_id"}) {
            String numeric = "\"" + field + "\":" + (field.equals("revision") ? 1 : field.equals("room_id") ? RoomPreferencesCases.ROOM : RoomPreferencesCases.MEMBER);
            for (String invalid : new String[]{"1.0", "1e0", "\"1\"", "true", "null", "2147483648", "9223372036854775807"})
                rejected(() -> parse(base.replace(numeric, "\"" + field + "\":" + invalid)));
        }
        for (String invalid : new String[]{"2.0", "2e0", "\"2\"", "true", "null"})
            rejected(() -> parse(base.replace("\"api_version\":2", "\"api_version\":" + invalid)));
        for (String field : new String[]{"mute_forever", "muted", "pinned", "archived"})
            for (String invalid : new String[]{"\"false\"", "0", "null"})
                rejected(() -> parse(base.replace("\"" + field + "\":false", "\"" + field + "\":" + invalid)));
        RoomPreferencesProtocol.Pending pending = RoomPreferencesCases.pending();
        JSONObject actualPayload = new JSONObject(pending.payload);
        check(actualPayload.length() == 8, "Actual payload exact field count");
        check(actualPayload.opt("pinned") instanceof Boolean && actualPayload.opt("archived") instanceof Boolean
                && actualPayload.opt("mute_forever") instanceof Boolean && actualPayload.opt("muted_until") == JSONObject.NULL,
                "Payload native booleans and JSON null");
        check(RoomPreferencesProtocol.restorePending(actualPayload, RoomPreferencesCases.ACCOUNT, RoomPreferencesCases.ROOM)
                .payload.equals(pending.payload), "Native decoding preserves canonical retry string");
        RoomPreferencesProtocol.Pending timed = RoomPreferencesProtocol.newPending(
                parse(RoomPreferencesCases.response(8, RoomPreferencesCases.PAST, false, true, false, false).toString()),
                RoomPreferencesCases.UUID, RoomPreferencesCases.PAST, false, false, true);
        check(RoomPreferencesProtocol.restorePending(new JSONObject(timed.payload), RoomPreferencesCases.ACCOUNT,
                RoomPreferencesCases.ROOM).payload.equals(timed.payload), "Expired-looking pending string not rewritten on native restore");
        String reply = RoomPreferencesCases.ack(pending, 2, false).toString();
        check(RoomPreferencesProtocol.acknowledgement(200, new JSONObject(reply), pending).operationRevision == 2,
                "Native decoded exact receipt accepted");
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200,
                new JSONObject(reply.replace("\"replayed\":false", "\"replayed\":\"false\"")), pending));
        rejected(() -> RoomPreferencesProtocol.acknowledgement(200,
                new JSONObject(reply.replace("\"operation_revision\":2", "\"operation_revision\":2.0")), pending));
        check(!RoomPreferencesProtocol.supported(new JSONObject("{\"api_version\":2,\"room_preferences_contract_version\":1.0}")), "Native decimal feature is unsupported");
        check(RoomPreferencesProtocol.supported(new JSONObject("{\"api_version\":2,\"room_preferences_contract_version\":1}")), "Native advertised one accepted");
        check(!parse(RoomPreferencesCases.response(3, RoomPreferencesCases.PAST, false, false, false, false).toString()).muted,
                "Native server-expired timed state accepted without local clock");
    }
}
