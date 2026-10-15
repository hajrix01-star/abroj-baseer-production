package com.baseer.freshchat.sync;

import java.util.Locale;
import java.util.UUID;

/** Pure policy for the durable outbox. A push notification is never a receipt. */
public final class OutboxPolicy {
    public static final int MAX_ATTEMPTS = 8;
    public static final long LEASE_MILLIS = 60_000L;
    public static final long MAX_BACKOFF_MILLIS = 15 * 60_000L;
    public static final int MAX_TEXT_BYTES = 16_384;
    public static final int MAX_PAYLOAD_BYTES = 65_536;
    public static final long MAX_RECORD_ID = 2_147_483_647L;
    public static final int MAX_ATTACHMENTS = 10;

    private OutboxPolicy() { }

    public enum State { QUEUED, IN_FLIGHT, RETRY, AUTH_REQUIRED, FAILED, SENT }
    public enum Failure { TRANSIENT, AUTHENTICATION, PERMANENT }

    /** Retry count increases when claimed, not when the process happens to restart. */
    public static State afterFailure(Failure failure, int attempts) {
        if (attempts < 1) throw new IllegalArgumentException("A failure needs a claimed attempt");
        if (failure == null) throw new IllegalArgumentException("Failure classification is required");
        if (failure == Failure.AUTHENTICATION) return State.AUTH_REQUIRED;
        if (failure == Failure.PERMANENT || attempts >= MAX_ATTEMPTS) return State.FAILED;
        return State.RETRY;
    }

    public static long backoffMillis(int attempts) {
        if (attempts < 1) throw new IllegalArgumentException("Attempts must be positive");
        int exponent = Math.min(attempts - 1, 16);
        return Math.min(5_000L * (1L << exponent), MAX_BACKOFF_MILLIS);
    }

    public static boolean eligible(State state, int attempts, long nextAttemptAt,
                                   long leaseUntil, long now) {
        if (state == null || attempts < 0 || attempts >= MAX_ATTEMPTS || now < 0) return false;
        if (state == State.QUEUED || state == State.RETRY) return nextAttemptAt <= now;
        return state == State.IN_FLIGHT && leaseUntil <= now;
    }

    public static long requireRecordId(long value) {
        if (value <= 0 || value > MAX_RECORD_ID) throw new IllegalArgumentException("Invalid Odoo record ID");
        return value;
    }

    public static void requireText(String text) {
        if (text == null || text.indexOf('\0') >= 0) throw new IllegalArgumentException("Valid text is required");
        boolean content = false;
        for (int i = 0; i < text.length();) {
            int cp = text.codePointAt(i); i += Character.charCount(cp);
            boolean space = (cp >= 9 && cp <= 13) || (cp >= 28 && cp <= 32) || cp == 0x85 ||
                    cp == 0xa0 || cp == 0x1680 || (cp >= 0x2000 && cp <= 0x200a) ||
                    cp == 0x2028 || cp == 0x2029 || cp == 0x202f || cp == 0x205f || cp == 0x3000;
            if (!space) content = true;
        }
        if (!content) throw new IllegalArgumentException("Message must contain text");
        requireUtf8Bound(text, MAX_TEXT_BYTES);
    }

    public static void requirePayload(String payload) { requireUtf8Bound(payload, MAX_PAYLOAD_BYTES); }

    private static void requireUtf8Bound(String value, int maximum) {
        if (value == null) throw new IllegalArgumentException("Value required");
        try {
            int bytes = java.nio.charset.StandardCharsets.UTF_8.newEncoder()
                    .onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT)
                    .encode(java.nio.CharBuffer.wrap(value)).remaining();
            if (bytes > maximum) throw new IllegalArgumentException("UTF-8 payload exceeds the API limit");
        } catch (java.nio.charset.CharacterCodingException invalid) {
            throw new IllegalArgumentException("Unpaired surrogate is not valid UTF-8");
        }
    }

    public static String requireUuid(String value) {
        if (value == null) throw new IllegalArgumentException("Client UUID is required");
        String canonical;
        try {
            UUID uuid = UUID.fromString(value);
            if (uuid.version() != 4 || uuid.variant() != 2) throw new IllegalArgumentException();
            canonical = uuid.toString();
        }
        catch (IllegalArgumentException error) { throw new IllegalArgumentException("Invalid client UUID"); }
        if (!canonical.equals(value.toLowerCase(Locale.ROOT)) || value.length() != 36) {
            throw new IllegalArgumentException("Use a full canonical client UUID");
        }
        return canonical;
    }

    public static void requireAcknowledgement(String queuedUuid, String returnedUuid, long messageId,
                                               String returnedState) {
        if (!requireUuid(queuedUuid).equals(requireUuid(returnedUuid))) {
            throw new IllegalArgumentException("Acknowledgement belongs to a different request");
        }
        requireRecordId(messageId);
        if (!"sent".equals(returnedState)) {
            throw new IllegalArgumentException("Only a canonical persisted-message acknowledgement is sent");
        }
    }
}
