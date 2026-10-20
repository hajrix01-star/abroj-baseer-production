import com.baseer.bwork.legacy.VoiceGestureState;
import com.baseer.bwork.legacy.VoiceGestureState.Action;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Pure contract/regression tests. No Android permission UI, microphone, or touch device is used. */
public final class VoiceGestureStateTest {
    private static int passed;

    private static void check(boolean condition, String title) {
        if (!condition) throw new AssertionError(title);
        passed++;
        System.out.println("PASS " + title);
    }

    private static VoiceGestureState start(boolean locked) {
        VoiceGestureState machine = new VoiceGestureState();
        if (!machine.onRecorderStarted(true, locked)) throw new AssertionError("fixture start");
        return machine;
    }

    private static boolean idle(VoiceGestureState machine) {
        return !machine.isActive() && !machine.isHolding() && !machine.isLocked()
                && machine.sessionId() == 0;
    }

    private static boolean terminal(Action action) {
        return action == Action.CANCEL_AND_DISCARD || action == Action.STOP_FOR_PREVIEW;
    }

    public static void main(String[] args) throws Exception {
        permissionAndStartContract();
        gestureThresholds();
        releaseAndExplicitControls();
        staleAndDuplicateEvents();
        exhaustiveTerminalSequences();
        concurrentTerminalEvents();
        check(Action.values().length == 4
                && Action.valueOf("NONE") == Action.NONE
                && Action.valueOf("LOCKED") == Action.LOCKED
                && Action.valueOf("CANCEL_AND_DISCARD") == Action.CANCEL_AND_DISCARD
                && Action.valueOf("STOP_FOR_PREVIEW") == Action.STOP_FOR_PREVIEW,
                "The full action vocabulary contains no SEND action");
        System.out.println("PASS: " + passed + " voice gesture tests (pure Java, no Android runtime execution)");
    }

    private static void permissionAndStartContract() {
        VoiceGestureState machine = new VoiceGestureState();
        check(idle(machine), "Fresh machine is idle with no session");
        check(!machine.onRecorderStarted(false, false) && idle(machine),
                "No microphone permission rejects a hold start");
        check(!machine.onRecorderStarted(false, true) && idle(machine),
                "No microphone permission rejects a tap/accessibility start");
        check(machine.onMove(200, -1) == Action.NONE
                && machine.onMove(0, -200) == Action.NONE
                && machine.onPointerUp() == Action.NONE
                && machine.onStop() == Action.NONE
                && machine.onLimitReached(1) == Action.NONE
                && machine.onCancel() == Action.NONE
                && machine.onError() == Action.NONE && idle(machine),
                "Move, release, stop, limit, cancel, and error never start recording or queue a start");
        machine.reset(); // Recorder.start() failure: never confirm a successful start.
        check(machine.onPointerUp() == Action.NONE && idle(machine),
                "Failed recorder startup/reset cannot create a preview from release");
        check(machine.onRecorderStarted(true, false) && machine.isActive()
                && machine.isHolding() && !machine.isLocked() && machine.sessionId() > 0,
                "Explicit successful recorder start with permission enters holding");
        long token = machine.sessionId();
        check(!machine.onRecorderStarted(true, true) && machine.isHolding()
                && machine.sessionId() == token,
                "Repeated start cannot replace or lock an active hold");
        check(!machine.onRecorderStarted(false, true) && machine.isHolding()
                && machine.sessionId() == token,
                "Rejected start leaves the existing active session unchanged");
        machine.reset();
        check(idle(machine) && machine.onRecorderStarted(true, true)
                && machine.isLocked() && machine.isActive() && !machine.isHolding()
                && machine.sessionId() > token,
                "A fresh explicit tap/accessibility start is locked with a new session token");
    }

    private static void gestureThresholds() {
        check(VoiceGestureState.CANCEL_DISTANCE_DP == 72f
                && VoiceGestureState.LOCK_DISTANCE_DP == 80f, "Gesture thresholds are 72 dp and 80 dp");
        for (int sign : new int[]{-1, 1}) {
            VoiceGestureState machine = start(false);
            check(machine.onMove(sign * 71.99f, 0) == Action.NONE && machine.isHolding(),
                    "Horizontal cancellation does not fire below threshold, direction " + sign);
            check(machine.onMove(sign * 72f, 0) == Action.CANCEL_AND_DISCARD && idle(machine),
                    "Horizontal cancellation fires at inclusive threshold, direction " + sign);
        }
        VoiceGestureState machine = start(false);
        check(machine.onMove(0, -79.99f) == Action.NONE && machine.isHolding(),
                "Upward lock does not fire below threshold");
        long token = machine.sessionId();
        check(machine.onMove(0, -80f) == Action.LOCKED && machine.isLocked()
                && machine.sessionId() == token, "Upward lock fires at inclusive threshold and retains session");
        check(machine.onMove(-200, 0) == Action.NONE
                && machine.onMove(200, 0) == Action.NONE
                && machine.onMove(0, -200) == Action.NONE && machine.isLocked(),
                "Locked pointer movements neither cancel nor repeat the lock action");
        machine = start(false);
        check(machine.onMove(0, 200) == Action.NONE && machine.isHolding(),
                "Downward motion never locks");
        check(machine.onMove(72, 100) == Action.NONE && machine.isHolding(),
                "Vertically dominant downward motion does not accidentally cancel sideways");
        check(machine.onMove(90, -100) == Action.LOCKED && machine.isLocked(),
                "Upward dominant diagonal locks even when both thresholds are crossed");
        machine = start(false);
        check(machine.onMove(-100, -90) == Action.CANCEL_AND_DISCARD && idle(machine),
                "Horizontal dominant diagonal cancels even when both thresholds are crossed");
        machine = start(false);
        check(machine.onMove(100, -100) == Action.NONE
                && machine.onMove(-100, -100) == Action.NONE
                && machine.onMove(100, 100) == Action.NONE && machine.isHolding(),
                "Equal diagonal axes have no dominance and do not lock or cancel");
        check(machine.onMove(50, 0) == Action.NONE
                && machine.onMove(50, 0) == Action.NONE && machine.isHolding(),
                "Moves use displacement from pointer down, not accumulated deltas");
        check(machine.onMove(Float.NaN, -200) == Action.NONE
                && machine.onMove(200, Float.NaN) == Action.NONE
                && machine.onMove(Float.POSITIVE_INFINITY, 0) == Action.NONE
                && machine.onMove(0, Float.NEGATIVE_INFINITY) == Action.NONE && machine.isHolding(),
                "Invalid coordinates cannot change recording state");
    }

    private static void releaseAndExplicitControls() {
        VoiceGestureState machine = start(false);
        check(machine.onPointerUp() == Action.STOP_FOR_PREVIEW && idle(machine),
                "Hold release stops exactly for preview, never for send");
        machine = start(true);
        check(machine.onPointerUp() == Action.NONE && machine.isLocked(),
                "Releasing a locked recording keeps it active");
        for (boolean locked : new boolean[]{false, true}) {
            machine = start(locked);
            check(machine.onStop() == Action.STOP_FOR_PREVIEW && idle(machine),
                    "Explicit stop returns preview from locked=" + locked);
            machine = start(locked);
            check(machine.onCancel() == Action.CANCEL_AND_DISCARD && idle(machine),
                    "ACTION_CANCEL/background/interruption discard from locked=" + locked);
            machine = start(locked);
            check(machine.onError() == Action.CANCEL_AND_DISCARD && idle(machine),
                    "Recorder error discards from locked=" + locked);
            machine = start(locked);
            long token = machine.sessionId();
            check(machine.onLimitReached(token) == Action.STOP_FOR_PREVIEW && idle(machine),
                    "Maximum duration creates one preview from locked=" + locked);
        }
    }

    private static void staleAndDuplicateEvents() {
        VoiceGestureState machine = start(false);
        long first = machine.sessionId();
        check(machine.onMove(-72, 0) == Action.CANCEL_AND_DISCARD
                && machine.onPointerUp() == Action.NONE
                && machine.onCancel() == Action.NONE
                && machine.onLimitReached(first) == Action.NONE
                && machine.onStop() == Action.NONE && idle(machine),
                "Slide cancel followed by release/cancel/limit cannot create a preview");
        machine.onRecorderStarted(true, false);
        long second = machine.sessionId();
        check(second > first && machine.onLimitReached(first) == Action.NONE
                && machine.onLimitReached(0) == Action.NONE
                && machine.onLimitReached(-1) == Action.NONE
                && machine.onLimitReached(second + 1) == Action.NONE && machine.isHolding(),
                "Old, zero, negative, and unknown duration tokens cannot stop a later capture");
        check(machine.onLimitReached(second) == Action.STOP_FOR_PREVIEW
                && machine.onLimitReached(second) == Action.NONE
                && machine.onPointerUp() == Action.NONE
                && machine.onCancel() == Action.NONE && idle(machine),
                "Limit then duplicate limit/release/cancel emits only one terminal action");
        machine.onRecorderStarted(true, false);
        long third = machine.sessionId();
        check(machine.onPointerUp() == Action.STOP_FOR_PREVIEW
                && machine.onPointerUp() == Action.NONE
                && machine.onLimitReached(third) == Action.NONE
                && machine.onError() == Action.NONE && idle(machine),
                "Release followed by release/limit/error cannot emit a second terminal action");
        machine.onRecorderStarted(true, true);
        long fourth = machine.sessionId();
        machine.reset();
        machine.onRecorderStarted(true, false);
        check(machine.sessionId() > fourth && machine.onLimitReached(fourth) == Action.NONE
                && machine.isHolding(), "Reset invalidates old duration callback across a restart");
        check(machine.onCancel() == Action.CANCEL_AND_DISCARD
                && machine.onMove(0, -100) == Action.NONE
                && machine.onPointerUp() == Action.NONE && idle(machine),
                "Cancellation is absorbing until another explicit recorder start");
    }

    private static Action event(VoiceGestureState machine, long token, int event) {
        switch (event) {
            case 0: return machine.onPointerUp();
            case 1: return machine.onCancel();
            case 2: return machine.onStop();
            case 3: return machine.onError();
            case 4: return machine.onLimitReached(token);
            case 5: return machine.onMove(-100, 0);
            case 6: return machine.onMove(0, -100);
            default: throw new AssertionError("Unknown test event");
        }
    }

    private static void exhaustiveTerminalSequences() {
        int sequences = 1;
        for (int i = 0; i < 5; i++) sequences *= 7;
        for (boolean locked : new boolean[]{false, true}) {
            for (int encoded = 0; encoded < sequences; encoded++) {
                VoiceGestureState machine = start(locked);
                long token = machine.sessionId();
                int cursor = encoded, terminalCount = 0;
                boolean ended = false;
                for (int i = 0; i < 5; i++) {
                    Action action = event(machine, token, cursor % 7);
                    cursor /= 7;
                    if (ended && action != Action.NONE) throw new AssertionError("Post-terminal action");
                    if (terminal(action)) { terminalCount++; ended = true; }
                    if (terminalCount > 1 || (ended && !idle(machine))) {
                        throw new AssertionError("Terminal race regression: " + encoded);
                    }
                }
            }
        }
        check(true, "All 33,614 five-event sequences emit at most one terminal action and never restart");
    }

    private static void concurrentTerminalEvents() throws Exception {
        for (int iteration = 0; iteration < 100; iteration++) {
            final VoiceGestureState machine = start(iteration % 2 == 0);
            final long token = machine.sessionId();
            final CountDownLatch gate = new CountDownLatch(1);
            final AtomicInteger terminals = new AtomicInteger();
            final AtomicReference<Throwable> failure = new AtomicReference<>();
            Thread[] threads = new Thread[5];
            for (int i = 0; i < threads.length; i++) {
                final int type = i;
                threads[i] = new Thread(() -> {
                    try {
                        gate.await();
                        if (terminal(event(machine, token, type))) terminals.incrementAndGet();
                    } catch (Throwable error) {
                        failure.compareAndSet(null, error);
                    }
                });
                threads[i].start();
            }
            gate.countDown();
            for (Thread thread : threads) thread.join();
            if (failure.get() != null) throw new AssertionError(failure.get());
            if (terminals.get() != 1 || !idle(machine)) {
                throw new AssertionError("Concurrent terminal callbacks double-finished a recording");
            }
        }
        check(true, "100 concurrent release/cancel/stop/error/limit races emit exactly one terminal action");
    }
}
