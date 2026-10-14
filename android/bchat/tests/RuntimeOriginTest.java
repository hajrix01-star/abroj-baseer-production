import com.baseer.freshchat.RuntimeOrigin;

public final class RuntimeOriginTest {
    public static void main(String[] args) {
        String phone = "https://desktop-cvc68i5.tail938958.ts.net:18444";
        check("https://localhost:18443".equals(RuntimeOrigin.forHardware("ranchu", phone)), "ranchu");
        check("https://localhost:18443".equals(RuntimeOrigin.forHardware("GOLDFISH", phone)), "goldfish");
        check(phone.equals(RuntimeOrigin.forHardware("qcom", phone)), "phone hardware");
        check(phone.equals(RuntimeOrigin.forHardware("", phone)), "unknown hardware");
        System.out.println("RuntimeOriginTest PASS");
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
