package android.os;
import java.util.concurrent.ConcurrentLinkedQueue;
/** Existing deterministic Handler adapter plus explicit throw/false queue-rejection fixtures.
 * Not Android Looper/Handler execution. No rejected work is silently executed. */
public class Handler {
    private static final ConcurrentLinkedQueue<Runnable> tasks = new ConcurrentLinkedQueue<>();
    public static volatile boolean rejectNext;
    public static volatile boolean falseNext;
    /** Target a declared later post boundary after newly added earlier hints. */
    public static volatile int rejectAfterPosts = -1;
    public Handler(Looper ignored) { }
    public boolean post(Runnable work) {
        if (rejectAfterPosts == 0) {
            rejectAfterPosts = -1;
            throw new java.util.concurrent.RejectedExecutionException("Explicit fixture later MAIN rejection");
        }
        if (rejectAfterPosts > 0) --rejectAfterPosts;
        if (rejectNext) { rejectNext = false; throw new java.util.concurrent.RejectedExecutionException("Explicit fixture MAIN rejection"); }
        if (falseNext) { falseNext = false; return false; }
        tasks.add(work); return true;
    }
    public static void drain() { Runnable work; while ((work = tasks.poll()) != null) work.run(); }
}
