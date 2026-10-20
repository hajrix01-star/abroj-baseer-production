package com.baseer.bwork.feedback;

/** Platform-free policy/resource owner, exercised by JVM tests. */
public final class FeedbackController {
    public interface Player { boolean start(String kind, int milliseconds); void release(); }
    public interface Factory { Player create(); }
    private final Factory factory;
    private Player player;
    private int revision;
    public FeedbackController(Factory factory) { this.factory = factory; }
    public synchronized int revision() { return revision; }
    public synchronized boolean play(String kind, boolean resumed, boolean normal, int volume, boolean dndAll) {
        stop();
        if (!("send".equals(kind) || "receive".equals(kind)) || !resumed || !normal || volume <= 0 || !dndAll) return false;
        try {
            player = factory.create();
            if (!player.start(kind, "send".equals(kind) ? 70 : 120)) { stop(); return false; }
            return true;
        } catch (RuntimeException failure) { stop(); return false; }
    }
    public synchronized void stopIfRevision(int expected) { if (expected == revision) stop(); }
    public synchronized void stop() {
        revision++;
        Player old = player; player = null;
        if (old != null) try { old.release(); } catch (RuntimeException ignored) { /* Already released. */ }
    }
}
