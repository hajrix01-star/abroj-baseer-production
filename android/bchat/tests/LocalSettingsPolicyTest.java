import com.baseer.freshchat.LocalSettingsPolicy;
import java.util.HashSet;
public final class LocalSettingsPolicyTest {
    private static int checks;
    private static void check(boolean ok, String message) { if (!ok) throw new AssertionError(message); checks++; }
    public static void main(String[] args) {
        check(!LocalSettingsPolicy.muteKey("a:b", "c").equals(LocalSettingsPolicy.muteKey("a", "b:c")), "scope is collision safe");
        check(!LocalSettingsPolicy.muteKey("one", "shared").equals(LocalSettingsPolicy.muteKey("two", "shared")), "company mute isolation");
        check(!LocalSettingsPolicy.muteKey("one", "first").equals(LocalSettingsPolicy.muteKey("one", "second")), "chat mute isolation");
        HashSet<String> channels = new HashSet<>();
        for (String category : new String[]{"conversations", "purchases", "tasks"})
            for (boolean sound : new boolean[]{false, true}) for (boolean vibrate : new boolean[]{false, true}) for (boolean hidden : new boolean[]{false, true})
                check(channels.add(LocalSettingsPolicy.channel(category, sound, vibrate, hidden)), "finite channels isolate Android immutable settings");
        boolean rejected = false; try { LocalSettingsPolicy.channel("unknown", true, true, true); } catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected, "unknown category rejected");
        rejected = false; try { LocalSettingsPolicy.muteKey(null, "chat"); } catch (IllegalArgumentException expected) { rejected = true; }
        check(rejected, "missing scope rejected");
        System.out.println("PASS " + checks + " local settings policy checks (no Android preference runtime)");
    }
}
