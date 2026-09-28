package sa.abroj.baseersms.v2;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import androidx.work.WorkManager;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Device credentials never live as plaintext preferences. */
final class SecureSettings {
    private static final String PREFS = "baseer_sms_v2";
    private static final String KEY_ALIAS = "baseer_sms_v2_settings";
    private SecureSettings() { }

    static boolean isPaired(Context context) { return !get(context, "url").isEmpty() && !get(context, "code").isEmpty() && !get(context, "secret").isEmpty(); }
    static String url(Context context) { return get(context, "url"); }
    static String code(Context context) { return get(context, "code"); }
    static String secret(Context context) { return get(context, "secret"); }
    static String installationId(Context context) { String value=get(context, "installation_id"); if(!value.isEmpty()) return value; value=UUID.randomUUID().toString(); put(context,"installation_id",value); return value; }
    static boolean enabled(Context context) { return prefs(context).getBoolean("enabled", false); }
    static void setEnabled(Context context, boolean value) { prefs(context).edit().putBoolean("enabled", value).apply(); }
    static void savePairing(Context context, String url, String code, String secret, String[] senders) { put(context, "url", url); put(context, "code", code); put(context, "secret", secret); saveAllowedSenders(context, senders); setEnabled(context, true); }
    static void saveAllowedSenders(Context context, String[] senders) { put(context, "senders", String.join("\n", senders)); }
    static boolean isAllowedSender(Context context, String sender) { if(sender==null||sender.isEmpty()) return false; String values=get(context,"senders"); if(values.isEmpty()) return false; for(String allowed:values.split("\\n",-1)) if(sender.equals(allowed)) return true; return false; }
    static void clear(Context context) { prefs(context).edit().clear().apply(); }
    /** Stops only the old v1 dispatchers after this same-package v2 update.
     * The v1 database is intentionally left untouched; the owner selected a
     * fresh v2 pairing and queue rather than a silent migration. */
    static void retireLegacyV1Dispatchers(Context context) {
        if (prefs(context).getBoolean("legacy_v1_dispatchers_retired", false)) return;
        WorkManager manager = WorkManager.getInstance(context);
        manager.cancelUniqueWork("baseer-bank-sms-sync");
        manager.cancelUniqueWork("baseer-bank-sms-periodic");
        manager.cancelUniqueWork("baseer-bank-sms-history");
        prefs(context).edit().putBoolean("legacy_v1_dispatchers_retired", true).apply();
    }
    static String encryptLocal(String value) throws Exception { return encrypt(value); }
    static String decryptLocal(String value) throws Exception { return decrypt(value); }

    private static SharedPreferences prefs(Context context) { return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE); }
    private static void put(Context context, String name, String value) {
        try { prefs(context).edit().putString(name, encrypt(value)).apply(); }
        catch (Exception error) { throw new IllegalStateException("Could not secure pairing data", error); }
    }
    private static String get(Context context, String name) {
        String value = prefs(context).getString(name, "");
        if (value.isEmpty()) return "";
        try { return decrypt(value); } catch (Exception error) { return ""; }
    }
    private static SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        SecretKey existing = (SecretKey) store.getKey(KEY_ALIAS, null); if (existing != null) return existing;
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
        return generator.generateKey();
    }
    private static String encrypt(String value) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        return Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + "." + Base64.encodeToString(cipher.doFinal(value.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
    }
    private static String decrypt(String value) throws Exception {
        String[] parts = value.split("\\.", 2); if (parts.length != 2) throw new IllegalArgumentException("invalid secure value");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
}
