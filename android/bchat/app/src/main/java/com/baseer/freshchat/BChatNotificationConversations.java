package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;

/**
 * Bounded, process-only notification presentation. This is not history, authorization,
 * a business unread count, a receipt, or an audio deduplication authority.
 *
 * Callers supply an already parsed production frame and their current local privacy ceiling.
 * Only fields permitted by the lesser of those two modes are copied; the frame is never kept.
 * A privacy/account/rights change must also call reset under the authenticated routing gate,
 * discard prior snapshots, and cancel its returned tags. Old immutable Java values held by a
 * caller cannot be erased, but present will never authorize those stale snapshots again.
 *
 * Lock order at integration: routing -> channel state -> this RAM lock, never the reverse.
 * No disk, network, preferences, Android object, avatar, or media access belongs in this module.
 */
final class BChatNotificationConversations {
    static final int MAX_ROOMS = 20;
    static final int MAX_MESSAGES = 5;
    private static final Object LOCK = new Object();
    // Insertion order is explicitly touched on append, not on a presentation lookup.
    private static final LinkedHashMap<String, Conversation> ROOMS = new LinkedHashMap<>();
    private static String activeAccount;
    private static String activeMode;

    static final class Message {
        final String messageKey, senderKey, sender, text;
        final long sentAt;
        final boolean attachment;

        private Message(NotificationPresentation frame, String mode) {
            messageKey = frame.messageKey;
            sentAt = frame.sentAt;
            boolean named = !"none".equals(mode);
            senderKey = named ? frame.senderKey : "";
            sender = named ? frame.sender : "";
            text = "full".equals(mode) ? frame.preview : "";
            attachment = "full".equals(mode) && frame.attachment;
        }
    }

    static final class Conversation {
        final String tag, account, roomKey, mode, title;
        final boolean group;
        final List<Message> messages;

        private Conversation(NotificationPresentation frame, String mode, List<Message> messages) {
            tag = tag(frame);
            account = frame.account;
            roomKey = frame.roomKey;
            this.mode = mode;
            title = "full".equals(mode) ? frame.title : "";
            group = "full".equals(mode) && frame.group;
            this.messages = Collections.unmodifiableList(new ArrayList<>(messages));
        }
    }

    static final class Change {
        final Conversation conversation;
        /** Cancel these OS rows before presenting the replacement; may include its same tag. */
        final List<String> evictedTags;
        /** Only RAM-window deduplication; NEVER use this value to grant an audible effect. */
        final boolean duplicate;

        private Change(Conversation conversation, List<String> evictedTags, boolean duplicate) {
            this.conversation = conversation;
            this.evictedTags = Collections.unmodifiableList(new ArrayList<>(evictedTags));
            this.duplicate = duplicate;
        }
    }

    // A deterministic tie-break for presentation only, never causal/receipt/business ordering.
    private static final Comparator<Message> ORDER = Comparator
            .comparingLong((Message message) -> message.sentAt)
            .thenComparing(message -> message.messageKey);

    /**
     * Null rejects unknown local modes or an invalid/legacy frame without changing RAM state.
     * An accepted change owns a current immutable snapshot, even for an out-of-order arrival.
     */
    static Change append(NotificationPresentation frame, String ceiling) {
        if (frame == null || !validMode(ceiling)) return null;
        String mode = projectedMode(frame, ceiling);
        synchronized (LOCK) {
            List<String> cancelled = new ArrayList<>();
            if (!frame.account.equals(activeAccount) || !mode.equals(activeMode)) {
                cancelled.addAll(ROOMS.keySet());
                ROOMS.clear();
                activeAccount = frame.account;
                activeMode = mode;
            }
            String tag = tag(frame);
            Conversation previous = ROOMS.remove(tag);
            if (previous != null) {
                for (Message message : previous.messages) {
                    if (message.messageKey.equals(frame.messageKey)) {
                        // A late duplicate cannot replace the original content or timestamp.
                        ROOMS.put(tag, previous);
                        return new Change(previous, cancelled, true);
                    }
                }
            }
            List<Message> messages = previous == null
                    ? new ArrayList<>() : new ArrayList<>(previous.messages);
            messages.add(new Message(frame, mode));
            messages.sort(ORDER);
            while (messages.size() > MAX_MESSAGES) messages.remove(0);
            Conversation current = new Conversation(frame, mode, messages);
            ROOMS.put(tag, current);
            if (ROOMS.size() > MAX_ROOMS) {
                String oldest = ROOMS.keySet().iterator().next();
                ROOMS.remove(oldest);
                cancelled.add(oldest);
            }
            return new Change(current, cancelled, false);
        }
    }

    /** Account/logout, privacy, or rights invalidation: metadata and allowed content all clear. */
    static List<String> reset() {
        synchronized (LOCK) {
            List<String> cancelled = Collections.unmodifiableList(new ArrayList<>(ROOMS.keySet()));
            ROOMS.clear();
            activeAccount = null;
            activeMode = null;
            return cancelled;
        }
    }

    /**
     * The current-owner lookup and short notification effect are atomic with append/reset.
     * The callback must not do disk/network work or acquire any earlier routing/channel lock.
     * A separate isCurrent check followed by notify would reopen the privacy race.
     */
    static boolean present(Conversation snapshot, Runnable presentation) {
        if (snapshot == null || presentation == null) return false;
        synchronized (LOCK) {
            if (ROOMS.get(snapshot.tag) != snapshot) return false;
            presentation.run();
            return true;
        }
    }

    private static boolean validMode(String mode) {
        return "none".equals(mode) || "sender".equals(mode) || "full".equals(mode);
    }

    private static String projectedMode(NotificationPresentation frame, String ceiling) {
        if ("none".equals(ceiling) || frame.senderKey == null) return "none";
        return "full".equals(ceiling) && frame.full ? "full" : "sender";
    }

    private static String tag(NotificationPresentation frame) {
        return frame.account + ":bchat-room:" + frame.roomKey;
    }

    private BChatNotificationConversations() { }
}
