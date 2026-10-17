package com.baseer.freshchat;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.*;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;

/** Production parser/hash/ledger; explicit in-memory preference adapter, not Android/FCM. */
public final class NotificationPresentationContractTest {
    static final String ACCOUNT = "00000000-0000-4000-8000-000000000001";
    static final String ROOM = "f204a34ee307e864d1c4db0eb36ab19cb8fca1e92d3d7da323773f7444fb6218";
    static final String MESSAGE = "3372699fdfc412a5fda6fbbbd3dd5e71343a3b80906fbabf30ff44aac30275d1";
    static final String SENDER = "2650f7f5758fa2582e2dbde9cfa8596e63625cdac6458718a3cc564f06f5977c";
    static final long NOW = 1792238400123L;
    static int assertions;
    static void check(boolean ok, String why) { if (!ok) throw new AssertionError(why); ++assertions; }
    static Map<String, String> payload() {
        Map<String, String> data = new HashMap<>();
        data.put("account_key", ACCOUNT); data.put("kind", "chat"); data.put("event_id", "41");
        data.put("presentation_v", "1"); data.put("room_key", ROOM); data.put("message_key", MESSAGE);
        data.put("sent_at_ms", String.valueOf(NOW)); return data;
    }
    static void invalid(String key, String value) {
        Map<String, String> data = payload(); data.put(key, value);
        check(NotificationPresentation.parse(data) == null, "reject " + key + "=" + value);
    }
    static final class Store extends Context {
        final Prefs prefs = new Prefs();
        public Context getApplicationContext() { return this; }
        public SharedPreferences getSharedPreferences(String name, int mode) { return prefs; }
    }
    static final class Prefs implements SharedPreferences {
        final Map<String, Set<String>> memory = new HashMap<>(), disk = new HashMap<>();
        boolean writable = true;
        public Set<String> getStringSet(String key, Set<String> fallback) { return memory.getOrDefault(key, fallback); }
        public Editor edit() {
            return new Editor() {
                final Map<String, Set<String>> changes = new HashMap<>();
                public Editor putStringSet(String key, Set<String> value) { changes.put(key, new HashSet<>(value)); return this; }
                public boolean commit() {
                    // Android commit(false) may already have updated process RAM.
                    memory.putAll(changes);
                    if (writable) disk.putAll(changes);
                    return writable;
                }
            };
        }
    }
    public static void main(String[] args) throws Exception {
        check(NotificationPresentation.roomKey(ACCOUNT, 7, 19, 23).equals(ROOM), "cross-language room vector");
        check(NotificationPresentation.messageKey(ACCOUNT, 7, 19, 23, 31).equals(MESSAGE), "cross-language message vector");
        check(NotificationPresentation.senderKey(ACCOUNT, 7, 19, 23, 13).equals(SENDER), "cross-language sender vector");
        check(!NotificationPresentation.roomKey(ACCOUNT, 7, 19, 24).equals(ROOM), "recipient epoch isolates room");
        check(!NotificationPresentation.messageKey(ACCOUNT, 7, 19, 24, 31).equals(MESSAGE), "recipient epoch isolates tone");
        try { NotificationPresentation.roomKey("a".repeat(64), 7, 19, 23); throw new AssertionError("local scope accepted"); }
        catch (IllegalArgumentException expected) { ++assertions; }
        try { NotificationPresentation.roomKey(ACCOUNT, 7, 19, 0); throw new AssertionError("bad ID accepted"); }
        catch (IllegalArgumentException expected) { ++assertions; }
        Map<String, String> data = payload();
        NotificationPresentation minimal = NotificationPresentation.parse(data);
        check(minimal != null && !minimal.full && minimal.sender.isEmpty() && minimal.title.isEmpty(), "none metadata only");
        data.put("sender_key", SENDER); data.put("sender_name", "اسم المرسل");
        NotificationPresentation sender = NotificationPresentation.parse(data);
        check(sender != null && !sender.full && sender.title.isEmpty(), "sender has no room title/group");
        data.put("conversation_title", "غرفة"); data.put("is_group", "true"); data.put("message_preview", "رسالة😀");
        NotificationPresentation full = NotificationPresentation.parse(data);
        check(full != null && full.full && full.group && full.preview.equals("رسالة😀"), "full valid frame");
        data.put("message_preview", "changed");
        check(full.preview.equals("رسالة😀"), "frame snapshots mutable source map");
        data.remove("message_preview"); data.put("message_preview_kind", "attachment");
        check(NotificationPresentation.parse(data).attachment, "attachment marker has no URI/bytes");
        data.put("message_preview", "both");
        check(NotificationPresentation.parse(data) == null, "no contradictory text/attachment");
        for (String field : new String[]{"account_key", "room_key", "message_key", "presentation_v", "sent_at_ms", "event_id"}) {
            Map<String, String> missing = payload(); missing.remove(field);
            check(NotificationPresentation.parse(missing) == null, "missing " + field + " quiet fallback");
        }
        invalid("presentation_v", "2"); invalid("presentation_v", "01"); invalid("room_key", ROOM.toUpperCase());
        invalid("kind", "task"); invalid("account_key", "a".repeat(64)); invalid("event_id", "01");
        invalid("event_id", "2147483648"); invalid("sent_at_ms", "0"); invalid("sent_at_ms", "01");
        invalid("sent_at_ms", "253402300800000"); invalid("sent_at_ms", "١٧٩٢٢٣٨٤٠٠١٢٣");
        invalid("sender_name", "unbound"); invalid("sender_key", SENDER); invalid("conversation_title", "unbound");
        invalid("message_preview", "unbound"); invalid("is_group", "true");
        Map<String, String> overflow = payload(); overflow.put("unknown", "😀".repeat(800));
        check(NotificationPresentation.parse(overflow) == null, "UTF8 complete envelope bound");
        overflow = payload(); overflow.put("unknown", "\ud800");
        check(NotificationPresentation.parse(overflow) == null, "unpaired surrogate quiet fallback");
        check(NotificationPresentation.quotedBytes("😀\n\"\\\u0001") == 18, "JSON UTF8 escaping exact byte count");

        Store store = new Store();
        check(BChatNotificationLedger.claimSound(store, ACCOUNT, MESSAGE, NOW, NOW, "system"), "durable first system reservation");
        check(!BChatNotificationLedger.claimSound(store, ACCOUNT, MESSAGE, NOW, NOW, "soft"), "FCM to live cannot switch route");
        Store restart = new Store(); restart.prefs.memory.putAll(store.prefs.disk);
        check(!BChatNotificationLedger.claimSound(restart, ACCOUNT, MESSAGE, NOW, NOW, "system"), "claim survives restart before audible effect");
        Store soft = new Store();
        check(BChatNotificationLedger.claimSound(soft, ACCOUNT, MESSAGE, NOW, NOW, "soft"), "live first reservation");
        check(!BChatNotificationLedger.claimSound(soft, ACCOUNT, MESSAGE, NOW, NOW, "system"), "live to FCM cannot duplicate tone");
        String other = "00000000-0000-4000-8000-000000000002";
        check(BChatNotificationLedger.claimSound(soft, other, MESSAGE, NOW, NOW, "silent"), "accounts isolate claims");
        Store failed = new Store(); failed.prefs.writable = false;
        check(!BChatNotificationLedger.claimSound(failed, ACCOUNT, MESSAGE, NOW, NOW, "system"), "failed commit forbids sound");
        failed.prefs.writable = true;
        check(!BChatNotificationLedger.claimSound(failed, ACCOUNT, MESSAGE, NOW, NOW, "soft"), "memory changed on commit failure remains conservative");
        Store failedRestart = new Store(); failedRestart.prefs.memory.putAll(failed.prefs.disk);
        check(BChatNotificationLedger.claimSound(failedRestart, ACCOUNT, MESSAGE, NOW, NOW, "system"), "unplayed uncommitted claim may retry after restart");
        check(!BChatNotificationLedger.claimSound(new Store(), ACCOUNT, MESSAGE, NOW - BChatNotificationLedger.MAX_AGE_MILLIS - 1,
                NOW, "system"), "old event never makes a new tone");
        check(!BChatNotificationLedger.claimSound(new Store(), ACCOUNT, MESSAGE, NOW + 300001, NOW, "system"), "untrusted future time quiet");
        check(!BChatNotificationLedger.claimSound(soft, ACCOUNT, MESSAGE, NOW, NOW - 1, "system"), "backwards wall clock does not free claim");
        Store corrupt = new Store(); corrupt.prefs.memory.put("sound-claims-v1", new HashSet<>(List.of("malformed")));
        check(!BChatNotificationLedger.claimSound(corrupt, ACCOUNT, MESSAGE, NOW, NOW, "system"), "corrupt claim set fails closed");
        Store bounded = new Store();
        for (int i = 1; i <= 512; i++) check(BChatNotificationLedger.claimSound(bounded, ACCOUNT,
                String.format(Locale.ROOT, "%064x", i), NOW, NOW, "system"), "claim " + i);
        check(!BChatNotificationLedger.claimSound(bounded, ACCOUNT, MESSAGE, NOW, NOW, "system"), "capacity does not evict unexpired claim");
        for (int i = 1; i <= 600; i++) BChatNotificationLedger.recordShown(bounded,
                BChatNotificationLedger.key(ACCOUNT, "chat", String.valueOf(i)), NOW);
        check(bounded.prefs.memory.get("sound-claims-v1").size() == 512, "shown-ledger eviction cannot evict sound claim");
        check(BChatNotificationLedger.claimSound(bounded, ACCOUNT, MESSAGE, NOW + BChatNotificationLedger.MAX_AGE_MILLIS + 1,
                NOW + BChatNotificationLedger.MAX_AGE_MILLIS + 1, "system"), "only expired claims reclaimed");
        Store concurrent = new Store(); CountDownLatch go = new CountDownLatch(1); AtomicInteger won = new AtomicInteger();
        List<Thread> workers = new ArrayList<>();
        for (int i = 0; i < 20; i++) {
            Thread thread = new Thread(() -> { try { go.await();
                if (BChatNotificationLedger.claimSound(concurrent, ACCOUNT, MESSAGE, NOW, NOW, "system")) won.incrementAndGet();
            } catch (InterruptedException interrupted) { throw new AssertionError(interrupted); } });
            thread.start(); workers.add(thread);
        }
        go.countDown(); for (Thread thread : workers) thread.join();
        check(won.get() == 1, "one durable winner across same-process concurrent callbacks");
        System.out.println("PASS " + assertions + " parser/hash/ledger assertions; explicit preference adapter, no Android audio/FCM/device");
    }
}
