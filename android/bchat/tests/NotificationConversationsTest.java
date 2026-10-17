package com.baseer.freshchat;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Real production parser and RAM buffer, without an Android/service/audio fixture. */
public final class NotificationConversationsTest {
    private static final String ACCOUNT = "00000000-0000-4000-8000-000000000001";
    private static final String OTHER = "00000000-0000-4000-8000-000000000002";
    private static int assertions;

    private static void check(boolean ok, String why) {
        if (!ok) throw new AssertionError(why);
        ++assertions;
    }

    private static Map<String, String> payload(String account, long room, long member,
            long message, long at, String mode) {
        Map<String, String> data = new HashMap<>();
        data.put("kind", "chat"); data.put("account_key", account);
        data.put("event_id", String.valueOf(message)); data.put("presentation_v", "1");
        data.put("room_key", NotificationPresentation.roomKey(account, 7, room, member));
        data.put("message_key", NotificationPresentation.messageKey(account, 7, room, member, message));
        data.put("sent_at_ms", String.valueOf(at));
        if (!"none".equals(mode)) {
            data.put("sender_key", NotificationPresentation.senderKey(account, 7, room, member, 13));
            data.put("sender_name", "مرسل Sender");
        }
        if ("full".equals(mode)) {
            data.put("conversation_title", "فريق Team"); data.put("is_group", "true");
            data.put("message_preview", "رسالة Message " + message);
        }
        return data;
    }

    private static NotificationPresentation frame(String account, long room, long member,
            long message, long at, String mode) {
        NotificationPresentation frame = NotificationPresentation.parse(
                payload(account, room, member, message, at, mode));
        if (frame == null) throw new AssertionError("Invalid test frame");
        return frame;
    }

    private static BChatNotificationConversations.Change append(long room, long message, long at) {
        return BChatNotificationConversations.append(frame(ACCOUNT, room, 23, message, at, "full"), "full");
    }

    private static void immutable(Runnable mutation, String why) {
        try { mutation.run(); throw new AssertionError(why); }
        catch (UnsupportedOperationException expected) { ++assertions; }
    }

    private static boolean current(BChatNotificationConversations.Conversation snapshot) {
        return BChatNotificationConversations.present(snapshot, () -> { });
    }

    private static int storedRooms() throws Exception {
        Field rooms = BChatNotificationConversations.class.getDeclaredField("ROOMS");
        rooms.setAccessible(true);
        return ((Map<?, ?>) rooms.get(null)).size();
    }

    private static void privacyMatrix() {
        String[] modes = {"none", "sender", "full"};
        for (int available = 0; available < modes.length; ++available) {
            for (int ceiling = 0; ceiling < modes.length; ++ceiling) {
                BChatNotificationConversations.reset();
                NotificationPresentation input = frame(ACCOUNT, 19, 23, 31, 1000, modes[available]);
                BChatNotificationConversations.Change change =
                        BChatNotificationConversations.append(input, modes[ceiling]);
                BChatNotificationConversations.Conversation room = change.conversation;
                BChatNotificationConversations.Message message = room.messages.get(0);
                int effective = Math.min(available, ceiling);
                check(room.mode.equals(modes[effective]), "least privacy ceiling " + available + "/" + ceiling);
                check(room.title.equals(effective == 2 ? input.title : ""), "room title full only");
                check(room.group == (effective == 2 && input.group), "group flag full only");
                check(message.senderKey.equals(effective > 0 ? input.senderKey : ""), "Person key absent at none");
                check(message.sender.equals(effective > 0 ? input.sender : ""), "sender name absent at none");
                check(message.text.equals(effective == 2 ? input.preview : ""), "preview absent below full");
                check(!message.attachment, "text has no attachment marker");
                check(message.messageKey.equals(input.messageKey) && message.sentAt == 1000,
                        "bounded immutable identity/time retained");
                check(room.account.equals(ACCOUNT) && room.roomKey.equals(input.roomKey), "canonical routing metadata");
                check(room.tag.equals(ACCOUNT + ":bchat-room:" + input.roomKey), "account/room/epoch tag");
                check(change.evictedTags.isEmpty() && !change.duplicate && current(room), "first projection owns snapshot");
            }
        }
        for (String ceiling : modes) {
            BChatNotificationConversations.reset();
            Map<String, String> data = payload(ACCOUNT, 19, 23, 31, 1000, "full");
            data.remove("message_preview"); data.put("message_preview_kind", "attachment");
            BChatNotificationConversations.Message message = BChatNotificationConversations.append(
                    NotificationPresentation.parse(data), ceiling).conversation.messages.get(0);
            check(message.text.isEmpty(), "attachment has no text/URI/data");
            check(message.attachment == "full".equals(ceiling), "attachment marker cannot reveal content below full");
        }
    }

    private static void privacyTransitionsAndRejection() throws Exception {
        BChatNotificationConversations.reset();
        BChatNotificationConversations.Conversation oldA = append(19, 31, 1000).conversation;
        BChatNotificationConversations.Conversation oldB = append(20, 32, 1001).conversation;
        BChatNotificationConversations.Change sender = BChatNotificationConversations.append(
                frame(ACCOUNT, 19, 23, 33, 1002, "full"), "sender");
        check(new HashSet<>(sender.evictedTags).equals(new HashSet<>(Arrays.asList(oldA.tag, oldB.tag))),
                "local downgrade returns all tags, including replacement tag");
        check(!current(oldA) && !current(oldB), "local downgrade invalidates every old rich snapshot");
        check(storedRooms() == 1 && sender.conversation.messages.size() == 1,
                "local downgrade clears prior room content, not only visible fields");
        check(sender.conversation.messages.get(0).text.isEmpty() && sender.conversation.title.isEmpty(),
                "downgrade copies no hidden rich content");
        BChatNotificationConversations.Change none = BChatNotificationConversations.append(
                frame(ACCOUNT, 21, 23, 34, 1003, "none"), "full");
        check(none.evictedTags.equals(Collections.singletonList(sender.conversation.tag)),
                "weaker frame also lowers effective mode and clears old content");
        check(!current(sender.conversation) && none.conversation.mode.equals("none"),
                "server-none payload cannot reuse old sender names");
        BChatNotificationConversations.Change full = append(19, 35, 1004);
        check(full.evictedTags.equals(Collections.singletonList(none.conversation.tag)),
                "expansion also clears prior mode before accepting fresh authorized fields");
        check(full.conversation.messages.size() == 1 && full.conversation.messages.get(0).text.endsWith("35"),
                "expansion does not resurrect messages from before downgrade");
        BChatNotificationConversations.Conversation before = full.conversation;
        check(BChatNotificationConversations.append(null, "none") == null && current(before),
                "invalid frame cannot guess identity, clear, or publish");
        for (String ceiling : new String[]{null, "", "FULL", "unknown", "full "}) {
            check(BChatNotificationConversations.append(frame(OTHER, 20, 24, 41, 1100, "full"), ceiling) == null,
                    "unknown local ceiling rejected");
            check(current(before) && storedRooms() == 1, "rejected ceiling leaves ownership/content unchanged");
        }
        for (String badField : new String[]{"presentation_v", "message_key", "room_key", "sent_at_ms"}) {
            Map<String, String> bad = payload(OTHER, 20, 24, 42, 1101, "full");
            bad.remove(badField);
            check(BChatNotificationConversations.append(NotificationPresentation.parse(bad), "none") == null,
                    "old/incomplete payload remains outside buffer");
            check(current(before), "generic fallback cannot steal existing identity");
        }
        List<String> cancelled = BChatNotificationConversations.reset();
        check(cancelled.equals(Collections.singletonList(before.tag)) && !current(before), "rights reset cancels current rows");
        check(BChatNotificationConversations.reset().isEmpty(), "repeat reset no stale cancellation rows");
        check(!BChatNotificationConversations.present(null, () -> { })
                        && !BChatNotificationConversations.present(before, null), "null gate arguments do not execute");
        BChatNotificationConversations.Conversation returned = append(19, 35, 1004).conversation;
        check(returned != before && !current(before) && current(returned), "same-tag recreation cannot revive old ownership");
    }

    private static void orderingDedupAndImmutable() {
        BChatNotificationConversations.reset();
        BChatNotificationConversations.Change last = null;
        for (long message : new long[]{6, 1, 5, 2, 4, 3}) last = append(19, message, message * 1000);
        check(last.conversation.messages.size() == 5, "only last five distinct chronological messages");
        for (int i = 0; i < 5; ++i) check(last.conversation.messages.get(i).sentAt == (i + 2) * 1000,
                "out-of-order arrivals sort chronologically");
        BChatNotificationConversations.Conversation previous = last.conversation;
        Map<String, String> duplicateData = payload(ACCOUNT, 19, 23, 4, 99999, "full");
        duplicateData.put("message_preview", "replacement"); duplicateData.put("sender_name", "replacement");
        duplicateData.put("conversation_title", "replacement"); duplicateData.put("is_group", "false");
        BChatNotificationConversations.Change duplicate = BChatNotificationConversations.append(
                NotificationPresentation.parse(duplicateData), "full");
        check(duplicate.duplicate && duplicate.conversation == previous && duplicate.evictedTags.isEmpty(),
                "same message key is a RAM duplicate, keeps current immutable snapshot");
        BChatNotificationConversations.Message original = previous.messages.get(2);
        check(original.sentAt == 4000 && original.text.endsWith("4") && !original.sender.equals("replacement"),
                "late duplicate cannot rewrite timestamp/content/sender");
        check(previous.title.equals("فريق Team") && previous.group, "duplicate cannot rewrite canonical room display");
        BChatNotificationConversations.Change veryOld = append(19, 7, 1);
        check(!veryOld.duplicate && veryOld.conversation.messages.size() == 5
                && veryOld.conversation.messages.get(0).sentAt == 2000, "older-than-window arrival cannot push out newer content");
        check(!current(previous) && current(veryOld.conversation), "accepted append invalidates prior snapshot identity");
        BChatNotificationConversations.Change evictedDuplicate = append(19, 1, 1000);
        check(!evictedDuplicate.duplicate && evictedDuplicate.conversation.messages.size() == 5,
                "bounded RAM dedup is not an unbounded audio/history guarantee");

        BChatNotificationConversations.reset();
        List<String> tiedKeys = new ArrayList<>();
        for (long message : new long[]{3, 1, 7, 5, 2, 6, 4}) {
            tiedKeys.add(NotificationPresentation.messageKey(ACCOUNT, 7, 19, 23, message));
            last = append(19, message, 1000);
        }
        Collections.sort(tiedKeys);
        List<String> firstOrder = new ArrayList<>();
        for (BChatNotificationConversations.Message message : last.conversation.messages) firstOrder.add(message.messageKey);
        check(firstOrder.equals(tiedKeys.subList(2, 7)), "hash tie-break deterministic for presentation only");
        BChatNotificationConversations.reset();
        for (long message : new long[]{4, 6, 2, 5, 7, 1, 3}) last = append(19, message, 1000);
        List<String> secondOrder = new ArrayList<>();
        for (BChatNotificationConversations.Message message : last.conversation.messages) secondOrder.add(message.messageKey);
        check(secondOrder.equals(firstOrder), "same timestamps stable across opposite arrival orders");
        BChatNotificationConversations.Change frozen = last;
        immutable(() -> frozen.conversation.messages.clear(), "messages list mutable");
        immutable(() -> frozen.conversation.messages.add(original), "messages list extensible");
        immutable(() -> frozen.evictedTags.add("other"), "cancel tags list extensible");
        List<String> reset = BChatNotificationConversations.reset();
        immutable(reset::clear, "reset tags list mutable");
        check(frozen.conversation.messages.size() == 5, "old snapshot structurally immutable after reset");
        check(!current(frozen.conversation), "immutability does not confer current authorization");

        Map<String, String> mutable = payload(ACCOUNT, 19, 23, 40, 1000, "full");
        NotificationPresentation input = NotificationPresentation.parse(mutable);
        BChatNotificationConversations.Conversation copied = BChatNotificationConversations.append(input, "sender").conversation;
        mutable.put("sender_name", "mutated"); mutable.put("message_preview", "mutated private"); mutable.clear();
        check(copied.messages.get(0).sender.equals("مرسل Sender") && copied.messages.get(0).text.isEmpty(),
                "source map lifetime and rich fields are not retained by sender projection");
    }

    private static void roomBoundsAndEpochs() throws Exception {
        BChatNotificationConversations.reset();
        List<BChatNotificationConversations.Conversation> rooms = new ArrayList<>();
        for (int room = 1; room <= 20; ++room) {
            BChatNotificationConversations.Change change = append(room, 1, 1000);
            rooms.add(change.conversation);
            check(change.evictedTags.isEmpty(), "first twenty rooms retained");
        }
        check(storedRooms() == 20, "room RAM limit twenty");
        check(current(rooms.get(1)), "presentation read succeeds but must not change LRU");
        BChatNotificationConversations.Change touch = append(1, 1, 1000);
        check(touch.duplicate && touch.conversation == rooms.get(0), "duplicate append touches room LRU only");
        BChatNotificationConversations.Change twentyOne = append(21, 1, 1000);
        check(twentyOne.evictedTags.equals(Collections.singletonList(rooms.get(1).tag)),
                "twenty-first room evicts exact least recently appended room");
        check(!current(rooms.get(1)) && current(rooms.get(0)) && storedRooms() == 20,
                "eviction invalidates old snapshot while touching preserves room");
        check(rooms.get(0).title.equals(rooms.get(1).title) && !rooms.get(0).tag.equals(rooms.get(1).tag),
                "same room names never merge identities");
        for (int room = 21; room <= 40; ++room) {
            for (int message = 2; message <= 9; ++message) {
                BChatNotificationConversations.Change change = append(room, message, message * 1000);
                check(change.conversation.messages.size() <= 5 && storedRooms() <= 20, "bounded after repeated replacements");
            }
        }
        List<String> boundedTags = BChatNotificationConversations.reset();
        check(boundedTags.size() == 20 && new HashSet<>(boundedTags).size() == 20, "at most twenty unique OS cancel tags");

        BChatNotificationConversations.Conversation epochA = append(19, 31, 1000).conversation;
        BChatNotificationConversations.Conversation epochB = BChatNotificationConversations.append(
                frame(ACCOUNT, 19, 24, 31, 1000, "full"), "full").conversation;
        check(!epochA.tag.equals(epochB.tag) && !epochA.messages.get(0).messageKey.equals(epochB.messages.get(0).messageKey),
                "membership epoch isolates room and message keys, never merged by name");
        check(current(epochA) && current(epochB), "buffer does not invent rights; root must invoke explicit rights reset");
        List<String> revoked = BChatNotificationConversations.reset();
        check(revoked.size() == 2 && !current(epochA) && !current(epochB), "rights invalidation clears both old/new epoch snapshots");
        BChatNotificationConversations.Conversation first = append(19, 31, 1000).conversation;
        BChatNotificationConversations.Change other = BChatNotificationConversations.append(
                frame(OTHER, 19, 23, 31, 1000, "full"), "full");
        check(other.evictedTags.equals(Collections.singletonList(first.tag)) && !current(first), "account change cancels old account row");
        check(other.conversation.account.equals(OTHER) && !other.conversation.tag.equals(first.tag)
                && storedRooms() == 1, "account switch retains only incoming account");
        BChatNotificationConversations.Change returned = append(19, 31, 1000);
        check(returned.evictedTags.equals(Collections.singletonList(other.conversation.tag)) && !returned.duplicate,
                "returning account never resurrects its old buffer");
    }

    private static Thread start(AtomicReference<Throwable> failure, Runnable action) {
        Thread thread = new Thread(() -> {
            try { action.run(); } catch (Throwable problem) { failure.compareAndSet(null, problem); }
        });
        thread.setDaemon(true); thread.start(); return thread;
    }

    private static void await(CountDownLatch latch) {
        try { if (!latch.await(3, TimeUnit.SECONDS)) throw new AssertionError("Latch timeout"); }
        catch (InterruptedException interrupted) { throw new AssertionError(interrupted); }
    }

    private static void join(Thread thread) throws Exception {
        thread.join(3000);
        check(!thread.isAlive(), "worker completed without deadlock");
    }

    private static void atomicGates() throws Exception {
        for (boolean modeChange : new boolean[]{false, true}) {
            BChatNotificationConversations.reset();
            BChatNotificationConversations.Conversation snapshot = append(19, 31, 1000).conversation;
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            CountDownLatch invalidationStarted = new CountDownLatch(1), invalidated = new CountDownLatch(1);
            AtomicInteger effects = new AtomicInteger(); AtomicReference<Throwable> failure = new AtomicReference<>();
            Thread presenter = start(failure, () -> {
                if (!BChatNotificationConversations.present(snapshot, () -> {
                    entered.countDown(); await(release); effects.incrementAndGet();
                })) throw new AssertionError("Current snapshot rejected");
            });
            await(entered);
            Thread invalidator = start(failure, () -> {
                invalidationStarted.countDown();
                if (modeChange) BChatNotificationConversations.append(frame(ACCOUNT, 19, 23, 32, 1001, "full"), "none");
                else BChatNotificationConversations.reset();
                invalidated.countDown();
            });
            await(invalidationStarted);
            try {
                check(!invalidated.await(80, TimeUnit.MILLISECONDS), "reset/mode-change cannot interleave check and effect");
            } finally { release.countDown(); }
            join(presenter); join(invalidator);
            check(failure.get() == null && effects.get() == 1, "one bounded effect finishes before invalidation");
            check(!current(snapshot) && !BChatNotificationConversations.present(snapshot, effects::incrementAndGet)
                    && effects.get() == 1, "late callback cannot show a reset/downgraded snapshot");
        }
        BChatNotificationConversations.reset();
        AtomicReference<Throwable> failure = new AtomicReference<>(); CountDownLatch go = new CountDownLatch(1);
        List<Thread> workers = new ArrayList<>();
        for (int i = 1; i <= 24; ++i) {
            long message = i;
            workers.add(start(failure, () -> {
                await(go); append(19, message, message * 1000); append(19, message, message * 1000);
            }));
        }
        go.countDown(); for (Thread worker : workers) join(worker);
        check(failure.get() == null && storedRooms() == 1, "concurrent distinct/duplicate appends remain one bounded room");
        BChatNotificationConversations.Conversation concurrent = append(19, 24, 24000).conversation;
        check(concurrent.messages.size() == 5, "concurrent append has exactly five distinct messages");
        for (int i = 0; i < 5; ++i) check(concurrent.messages.get(i).sentAt == (i + 20) * 1000,
                "concurrent scheduling cannot change deterministic latest-five projection");
        try {
            BChatNotificationConversations.present(concurrent, () -> { throw new IllegalStateException("notify failed"); });
            throw new AssertionError("effect failure swallowed");
        } catch (IllegalStateException expected) { ++assertions; }
        check(current(concurrent), "effect failure does not corrupt lock or buffer ownership");
    }

    private static void representationContract() {
        for (Class<?> type : new Class<?>[]{BChatNotificationConversations.Message.class,
                BChatNotificationConversations.Conversation.class, BChatNotificationConversations.Change.class}) {
            check(Modifier.isFinal(type.getModifiers()), "snapshot value type is final");
            for (Field field : type.getDeclaredFields()) {
                check(Modifier.isFinal(field.getModifiers()), "snapshot field immutable: " + field.getName());
                Class<?> fieldType = field.getType();
                check(fieldType == String.class || fieldType == boolean.class || fieldType == long.class
                        || fieldType == List.class || fieldType == BChatNotificationConversations.Conversation.class,
                        "no rawframe/map/Android/media/hidden mutable payload field: " + field.getName());
            }
        }
        Set<String> messageFields = new HashSet<>();
        for (Field field : BChatNotificationConversations.Message.class.getDeclaredFields()) messageFields.add(field.getName());
        check(messageFields.equals(new HashSet<>(Arrays.asList("messageKey", "senderKey", "sender", "text", "sentAt", "attachment"))),
                "only explicit projected message fields retained");
        Set<String> roomFields = new HashSet<>();
        for (Field field : BChatNotificationConversations.Conversation.class.getDeclaredFields()) roomFields.add(field.getName());
        check(roomFields.equals(new HashSet<>(Arrays.asList("tag", "account", "roomKey", "mode", "title", "group", "messages"))),
                "only explicit projected room fields retained, no event/auth/avatar/rawframe");
    }

    public static void main(String[] args) throws Exception {
        try {
            privacyMatrix(); privacyTransitionsAndRejection(); orderingDedupAndImmutable();
            roomBoundsAndEpochs(); atomicGates(); representationContract();
            System.out.println("PASS " + assertions + " production parser/RAM conversation assertions; no Android/FCM/audio/service execution");
        } finally { BChatNotificationConversations.reset(); }
    }
}
