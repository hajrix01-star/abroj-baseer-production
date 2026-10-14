import com.baseer.freshchat.sync.AccountScope;
import com.baseer.freshchat.sync.OutboxPolicy;
import static com.baseer.freshchat.sync.OutboxPolicy.State.*;

public final class OutboxPolicyTest {
    private static int assertions;
    private static void check(boolean value) { assertions++; if (!value) throw new AssertionError(assertions); }
    private static void rejects(Runnable action) {
        assertions++;
        try { action.run(); throw new AssertionError("Expected rejection " + assertions); }
        catch (IllegalArgumentException expected) { }
    }
    private static String repeat(String text, int count) {
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < count; i++) result.append(text);
        return result.toString();
    }
    public static void main(String[] ignored) {
        String uuid = "550e8400-e29b-41d4-a716-446655440000";
        check(OutboxPolicy.requireUuid(uuid).equals(uuid));
        check(OutboxPolicy.requireUuid(uuid.toUpperCase()).equals(uuid));
        rejects(() -> OutboxPolicy.requireUuid("1-1-1-1-1"));
        rejects(() -> OutboxPolicy.requireUuid("550e8400-e29b-11d4-a716-446655440000"));
        rejects(() -> OutboxPolicy.requireUuid("550e8400-e29b-41d4-0716-446655440000"));
        rejects(() -> OutboxPolicy.requireUuid(null));
        check(OutboxPolicy.eligible(QUEUED,0,50,0,50));
        check(!OutboxPolicy.eligible(RETRY,1,51,0,50));
        check(OutboxPolicy.eligible(IN_FLIGHT,1,0,50,50));
        check(!OutboxPolicy.eligible(IN_FLIGHT,1,0,51,50));
        check(!OutboxPolicy.eligible(IN_FLIGHT,8,0,1,50));
        for (OutboxPolicy.State state : new OutboxPolicy.State[]{SENT,FAILED,AUTH_REQUIRED}) {
            check(!OutboxPolicy.eligible(state,1,0,0,50));
        }
        check(OutboxPolicy.afterFailure(OutboxPolicy.Failure.TRANSIENT,1)==RETRY);
        check(OutboxPolicy.afterFailure(OutboxPolicy.Failure.TRANSIENT,8)==FAILED);
        check(OutboxPolicy.afterFailure(OutboxPolicy.Failure.AUTHENTICATION,8)==AUTH_REQUIRED);
        check(OutboxPolicy.afterFailure(OutboxPolicy.Failure.PERMANENT,1)==FAILED);
        rejects(() -> OutboxPolicy.afterFailure(OutboxPolicy.Failure.TRANSIENT,0));
        check(OutboxPolicy.backoffMillis(1)==5000);
        check(OutboxPolicy.backoffMillis(2)==10000);
        check(OutboxPolicy.backoffMillis(Integer.MAX_VALUE)==900000);
        rejects(() -> OutboxPolicy.backoffMillis(0));
        OutboxPolicy.requireAcknowledgement(uuid,uuid,42,"sent"); assertions++;
        rejects(() -> OutboxPolicy.requireAcknowledgement(uuid,"650e8400-e29b-41d4-a716-446655440000",42,"sent"));
        rejects(() -> OutboxPolicy.requireAcknowledgement(uuid,uuid,0,"sent"));
        rejects(() -> OutboxPolicy.requireAcknowledgement(uuid,uuid,42,"delivered"));
        rejects(() -> OutboxPolicy.requireAcknowledgement(uuid,uuid,42,"read"));
        AccountScope a = new AccountScope("https://baseer.example","qa",7);
        check(a.key.equals(new AccountScope("https://BASEER.example:443/","qa",7).key));
        check(!a.key.equals(new AccountScope("https://baseer.example","qa",8).key));
        check(!a.key.equals(new AccountScope("https://baseer.example","other",7).key));
        check(!a.key.equals(new AccountScope("https://other.example","qa",7).key));
        check(a.key.length()==64);
        rejects(() -> new AccountScope("http://baseer.example","qa",7));
        rejects(() -> new AccountScope("https://name:password@baseer.example","qa",7));
        rejects(() -> new AccountScope("https://baseer.example/path","qa",7));
        rejects(() -> new AccountScope("https://baseer.example?token=secret","qa",7));
        rejects(() -> new AccountScope("https://baseer.example#fragment","qa",7));
        rejects(() -> new AccountScope("https://baseer.example","qa\n7",7));
        rejects(() -> new AccountScope("https://baseer.example","qa",0));
        check(OutboxPolicy.requireRecordId(2147483647L) == 2147483647L);
        rejects(() -> OutboxPolicy.requireRecordId(2147483648L));
        rejects(() -> OutboxPolicy.requireRecordId(0));
        rejects(() -> new AccountScope("https://baseer.example", "qa", 2147483648L));
        OutboxPolicy.requireText(repeat("a", 16384)); assertions++;
        rejects(() -> OutboxPolicy.requireText(repeat("a", 16385)));
        OutboxPolicy.requireText(repeat("ع", 8192)); assertions++;
        rejects(() -> OutboxPolicy.requireText(repeat("ع", 8193)));
        OutboxPolicy.requireText(repeat("😀", 4096)); assertions++;
        rejects(() -> OutboxPolicy.requireText(repeat("😀", 4097)));
        rejects(() -> OutboxPolicy.requireText("a\u0000b"));
        rejects(() -> OutboxPolicy.requireText("\ud800"));
        rejects(() -> OutboxPolicy.requireText("\udfff"));
        rejects(() -> OutboxPolicy.requireText(" \n\t\u00a0\u0085"));
        rejects(() -> OutboxPolicy.requireText(""));
        OutboxPolicy.requireText("  ع😀  "); assertions++;
        OutboxPolicy.requirePayload(repeat("x", 65536)); assertions++;
        rejects(() -> OutboxPolicy.requirePayload(repeat("x", 65537)));
        System.out.println("PASS: " + assertions + " outbox/account policy assertions");
    }
}
