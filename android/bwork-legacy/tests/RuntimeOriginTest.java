import com.baseer.bwork.legacy.RuntimeOrigin;

public final class RuntimeOriginTest {
    public static void main(String[] args) {
        String qa = "https://baseer-live-qa.tail938958.ts.net";
        check(qa.equals(RuntimeOrigin.forHardware("ranchu", qa)), "QA emulator");
        check(qa.equals(RuntimeOrigin.forHardware("GOLDFISH", qa)), "QA emulator variant");
        check(qa.equals(RuntimeOrigin.forHardware("qcom", qa)), "QA phone");
        check(qa.equals(RuntimeOrigin.forHardware("", qa)), "QA unknown hardware");
        String localDebug = "https://localhost:18443";
        check(localDebug.equals(RuntimeOrigin.forHardware("ranchu", localDebug)), "explicit local debug");
        System.out.println("RuntimeOriginTest PASS");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
