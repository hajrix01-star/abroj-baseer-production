package sa.abroj.baseersms.v2;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
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
    static boolean enabled(Context context) { return prefs(context).getBoolean("enabled", false); }
    static void setEnabled(Context context, boolean value) { prefs(context).edit().putBoolean("enabled", value).apply(); }
    static void savePairing(Context context, String url, String code, String secret) { put(context, "url", url); put(context, "code", code); put(context, "secret", secret); setEnabled(context, true); }
    static void clear(Context context) { prefs(context).edit().clear().apply(); }
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
