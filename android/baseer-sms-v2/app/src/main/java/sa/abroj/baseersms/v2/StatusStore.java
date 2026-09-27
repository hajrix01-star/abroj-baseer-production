package sa.abroj.baseersms.v2;
import android.content.Context; import android.content.SharedPreferences;
final class StatusStore {
    private static final String PREFS="baseer_sms_v2_status"; private StatusStore() { }
    static void heartbeat(Context c, long at) { prefs(c).edit().putLong("heartbeat_at", at).putString("error", "").apply(); }
    static void acknowledged(Context c, long at) { prefs(c).edit().putLong("last_ack_at", at).putString("error", "").apply(); }
    static void error(Context c, String value) { prefs(c).edit().putString("error", value).apply(); }
    static long heartbeatAt(Context c) { return prefs(c).getLong("heartbeat_at",0); } static long lastAckAt(Context c) { return prefs(c).getLong("last_ack_at",0); } static String error(Context c) { return prefs(c).getString("error",""); }
    private static SharedPreferences prefs(Context c) { return c.getSharedPreferences(PREFS,Context.MODE_PRIVATE); }
}
