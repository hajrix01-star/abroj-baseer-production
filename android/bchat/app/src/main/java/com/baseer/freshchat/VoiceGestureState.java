package com.baseer.freshchat;

/**
 * Pure state for one foreground-only voice capture. This class never starts a recorder,
 * requests permission, stores an attachment, or sends a message.
 *
 * <p>The UI must check microphone permission, start the recorder successfully, then call
 * {@link #onRecorderStarted(boolean, boolean)}. A permission callback must not resurrect
 * an old pointer gesture: require a new explicit press/tap after granting permission.
 * Call {@link #onCancel()} for ACTION_CANCEL, interruptions, backgrounding, and navigation,
 * including when locked. Calls are synchronized so only one terminal action wins per
 * recording; apply returned actions exactly once on the UI thread.</p>
 *
 * <p>Coordinates passed to {@link #onMove(float, float)} are displacement from the original
 * pointer down in dp, with negative y pointing upward. Equal diagonal movement has no
 * dominant axis and does nothing. A locked recording ignores subsequent pointer movement
 * and release, but still honors explicit stop, cancellation, errors, and duration limits.</p>
 */
public final class VoiceGestureState {
    public static final float CANCEL_DISTANCE_DP = 72f;
    public static final float LOCK_DISTANCE_DP = 80f;

    public enum Action {
        NONE,
        LOCKED,
        CANCEL_AND_DISCARD,
        STOP_FOR_PREVIEW
    }

    private enum State { IDLE, HOLDING, LOCKED }

    private State state = State.IDLE;
    private long lastSessionId;
    private long activeSessionId;

    /**
     * Confirms a recorder that has already started successfully. This is the only method
     * that enters an active state. False permission or an already-active session rejects
     * the call without altering the existing state. A tap/accessibility start uses
     * startLocked=true; a fresh press-and-hold uses false.
     *
     * <p>If recorder startup throws/fails, do not call this method; clean up the recorder
     * and call {@link #reset()}. The caller must also clean up a recorder whose start
     * confirmation is rejected.</p>
     */
    public synchronized boolean onRecorderStarted(boolean permissionGranted, boolean startLocked) {
        if (!permissionGranted || state != State.IDLE) return false;
        // Refuse an impossible-in-practice wraparound instead of reusing a stale timer token.
        if (lastSessionId == Long.MAX_VALUE) return false;
        activeSessionId = ++lastSessionId;
        state = startLocked ? State.LOCKED : State.HOLDING;
        return true;
    }

    public synchronized boolean isHolding() { return state == State.HOLDING; }
    public synchronized boolean isLocked() { return state == State.LOCKED; }
    public synchronized boolean isActive() { return state != State.IDLE; }

    /** Capture this positive token after successful start for that recording's limit callback. */
    public synchronized long sessionId() { return activeSessionId; }

    public synchronized Action onMove(float dxDp, float dyDp) {
        if (state != State.HOLDING || !finite(dxDp) || !finite(dyDp)) return Action.NONE;
        float horizontal = Math.abs(dxDp);
        float vertical = Math.abs(dyDp);
        if (horizontal >= CANCEL_DISTANCE_DP && horizontal > vertical) {
            return finish(Action.CANCEL_AND_DISCARD);
        }
        if (-dyDp >= LOCK_DISTANCE_DP && vertical > horizontal) {
            state = State.LOCKED;
            return Action.LOCKED;
        }
        return Action.NONE;
    }

    /** Releasing an ordinary hold previews the recording; releasing a lock does nothing. */
    public synchronized Action onPointerUp() {
        return state == State.HOLDING ? finish(Action.STOP_FOR_PREVIEW) : Action.NONE;
    }

    /** Cancels even when locked. Bind foreground loss and ACTION_CANCEL to this method. */
    public synchronized Action onCancel() {
        return state == State.IDLE ? Action.NONE : finish(Action.CANCEL_AND_DISCARD);
    }

    /** Explicit stop always goes to preview; sending is a separate, user-confirmed UI action. */
    public synchronized Action onStop() {
        return state == State.IDLE ? Action.NONE : finish(Action.STOP_FOR_PREVIEW);
    }

    public synchronized Action onError() {
        return state == State.IDLE ? Action.NONE : finish(Action.CANCEL_AND_DISCARD);
    }

    /** Old, duplicate, and zero-token timer callbacks cannot stop a later recording. */
    public synchronized Action onLimitReached(long sessionId) {
        if (state == State.IDLE || sessionId == 0 || sessionId != activeSessionId) {
            return Action.NONE;
        }
        return finish(Action.STOP_FOR_PREVIEW);
    }

    /**
     * Clears state after startup failure or recorder cleanup without emitting an action.
     * This does not release hardware; an active recorder must first be canceled by its owner.
     * Session numbering is deliberately retained so late callbacks remain invalid.
     */
    public synchronized void reset() {
        state = State.IDLE;
        activeSessionId = 0;
    }

    private Action finish(Action action) {
        state = State.IDLE;
        activeSessionId = 0;
        return action;
    }

    private static boolean finite(float value) {
        return !Float.isNaN(value) && !Float.isInfinite(value);
    }
}
