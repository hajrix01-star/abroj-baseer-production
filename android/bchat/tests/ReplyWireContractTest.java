import com.baseer.freshchat.ReplyWireContract;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

public final class ReplyWireContractTest {
    private static Set<String> fields(String... names) {
        return new HashSet<>(Arrays.asList(names));
    }

    private static void rejected(Runnable action) {
        try { action.run(); }
        catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Invalid reply accepted");
    }

    public static void main(String[] args) {
        Set<String> legacy = fields("id", "author_name", "text");
        Set<String> extended = fields("id", "author_name", "text", "media_kind");
        ReplyWireContract.requireAvailable(legacy, 10, 9, "Author", "", null);
        ReplyWireContract.requireAvailable(extended, 10, 9, "Author", "Image", "image");
        ReplyWireContract.requireAvailable(extended, 10, 9, "Author", "Text", null);
        ReplyWireContract.requireUnavailable(fields("unavailable"), true);
        rejected(() -> ReplyWireContract.requireAvailable(fields("id", "text"), 10, 9,
                "Author", "Text", null));
        rejected(() -> ReplyWireContract.requireAvailable(fields("id", "author_name", "text", "unknown"),
                10, 9, "Author", "Text", null));
        rejected(() -> ReplyWireContract.requireAvailable(extended, 10, 9,
                "Author", "Text", "video"));
        rejected(() -> ReplyWireContract.requireAvailable(legacy, 10, 10,
                "Author", "Text", null));
        rejected(() -> ReplyWireContract.requireUnavailable(fields("unavailable"), false));
        System.out.println("PASS ReplyWireContractTest");
    }
}
