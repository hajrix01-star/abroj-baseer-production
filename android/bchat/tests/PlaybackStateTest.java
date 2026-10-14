import com.baseer.freshchat.PlaybackState;
import static com.baseer.freshchat.PlaybackState.Phase.*;

public final class PlaybackStateTest {
    private static int checks;
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); checks++; }
    public static void main(String[] args) {
        PlaybackState s = new PlaybackState(); check(s.phase() == IDLE, "idle initially");
        long a = s.select("a"); check(s.phase() == PREPARING && s.owns(a), "select prepares");
        check(!s.pause(a) && !s.seek(a, 100) && !s.complete(a), "prepare has no seek/pause/complete");
        check(!s.prepared(a, 0), "zero duration rejected");
        check(s.prepared(a, 10_000) && s.phase() == PLAYING, "ready starts");
        check(!s.prepared(a, 5_000) && s.duration() == 10_000, "duplicate ready ignored");
        s.progress(a, 2_000); check(s.position() == 2_000, "real progress");
        check(s.pause(a) && s.phase() == PAUSED, "pause");
        s.progress(a, 5_000); check(s.position() == 2_000, "paused progress ignored");
        check(s.seek(a, 7_000) && s.position() == 7_000 && s.phase() == PAUSED, "paused seeking stays paused");
        check(s.resume(a) && s.position() == 7_000, "resume retains seek");
        check(s.seek(a, -300) && s.position() == 0, "negative seek clamps");
        check(s.seek(a, Integer.MAX_VALUE) && s.position() == 10_000, "seek upper bound");
        s.speed(1.5f); check(s.speed() == 1.5f, "supported speed");
        boolean rejected = false; try { s.speed(Float.NaN); } catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected && s.speed() == 1.5f, "invalid speed rejected");
        check(s.complete(a) && s.phase() == COMPLETE && s.position() == 10_000, "completion");
        check(s.resume(a) && s.position() == 0, "replay from start");
        s.complete(a); check(s.seek(a, 4_000) && s.phase() == PAUSED, "seek completed clip");
        long b = s.select("b"); check(b != a && s.clip().equals("b") && s.speed() == 1f, "second clip replaces first");
        check(!s.prepared(a, 100) && !s.pause(a) && !s.complete(a) && !s.seek(a, 40), "stale callbacks fenced");
        s.progress(a, 99); check(s.position() == 0, "stale ticker ignored");
        s.stop(); check(s.phase() == IDLE && s.clip() == null && !s.owns(b), "navigation stop clears ownership");
        check(!s.prepared(b, 9_000), "prepare after deletion/cancel ignored");
        s.stop(); check(s.phase() == IDLE, "stop idempotent");
        for (int i = 0; i < 1000; i++) {
            long previous = s.select("old"), current = s.select("new");
            if (s.prepared(previous, 10) || !s.prepared(current, 100) || !s.pause(current) || !s.resume(current)) throw new AssertionError("repeat transition");
            s.stop(); if (s.complete(current)) throw new AssertionError("stale completion");
        }
        check(true, "1000 repeated switch/pause/resume/stop sequences");
        System.out.println("PASS " + checks + " playback state checks (plus 1000 repeated sequences; no Android audio runtime)");
    }
}
