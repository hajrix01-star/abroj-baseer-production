import com.baseer.freshchat.ChatStore;
import com.baseer.freshchat.NotificationDemoPolicy;
import java.nio.file.*;
import java.io.*;
import java.util.*;

/** Pure policy checks only. Does not exercise Android permission dialogs, sound, or delivery. */
public final class NotificationDemoPolicyTest {
    static int passed;
    static void check(boolean ok, String title) { if (!ok) throw new AssertionError(title); passed++; System.out.println("PASS " + title); }
    interface Action { void run(); }
    static boolean rejects(Action a) { try { a.run(); return false; } catch (IllegalArgumentException e) { return true; } }
    public static void main(String[] args) throws Exception {
        Path dir = Files.createTempDirectory("baseer-notification-policy-");
        try {
            ChatStore store = new ChatStore(dir.resolve("state.bin").toFile());
            NotificationDemoPolicy.Target immediate = NotificationDemoPolicy.target(store, "demo-nour", "demo-nour-ops", 0);
            check(immediate.delayMillis == 0 && immediate.companyId.equals("demo-nour") && immediate.conversationId.equals("demo-nour-ops"), "Immediate test preserves explicit destination");
            NotificationDemoPolicy.Target delayed = NotificationDemoPolicy.target(store, "demo-madar", "demo-madar-sara", 10000);
            check(delayed.delayMillis == 10000 && delayed.companyId.equals("demo-madar") && delayed.conversationId.equals("demo-madar-sara"), "Delayed test remains bound to its original company/chat");
            check(rejects(() -> NotificationDemoPolicy.target(store, "demo-nour", "demo-madar-ops", 0))
                    && rejects(() -> NotificationDemoPolicy.target(store, null, null, 0)), "Cross-company and missing targets are rejected");
            boolean bounded = true;
            for (int delay : new int[]{-1, 1, 9999, 10001, 60000, Integer.MAX_VALUE}) {
                bounded &= rejects(() -> NotificationDemoPolicy.target(store, "demo-nour", "demo-nour-ops", delay));
            }
            check(bounded, "Only immediate or ten-second tests are permitted");
            check(!NotificationDemoPolicy.needsRuntimePermission(26, false)
                    && !NotificationDemoPolicy.needsRuntimePermission(32, false)
                    && NotificationDemoPolicy.needsRuntimePermission(33, false)
                    && NotificationDemoPolicy.needsRuntimePermission(35, false)
                    && !NotificationDemoPolicy.needsRuntimePermission(35, true), "Notification permission policy respects Android API and grant");
            int count = store.messageCount("demo-nour", "demo-nour-ops");
            store.setDraft("demo-nour", "demo-nour-ops", "Keep my draft", Collections.emptyList());
            ChatStore.PendingShare share = store.stagePendingShare("Keep pending share", Collections.emptyList());
            NotificationDemoPolicy.target(store, "demo-nour", "demo-nour-ops", 10000);
            check(count == store.messageCount("demo-nour", "demo-nour-ops")
                    && store.draft("demo-nour", "demo-nour-ops").text.equals("Keep my draft")
                    && share.id.equals(store.pendingShare().id), "Preparing a test does not mutate messages, drafts, or shares");
            System.out.println("PASS: " + passed + " notification policy tests (no Android runtime execution)");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(dir)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> { try { Files.delete(path); } catch (IOException e) { throw new RuntimeException(e); } });
            }
        }
    }
}
