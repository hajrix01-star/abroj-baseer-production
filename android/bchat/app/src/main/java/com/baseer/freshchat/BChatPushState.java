package com.baseer.freshchat;

import android.content.Context;
import android.content.SharedPreferences;

import com.baseer.freshchat.sync.AccountScope;

import java.util.UUID;

/** Local push identity only. It never grants access to a BChat event or stores a session. */
public final class BChatPushState {
    public static final String EXTRA_EVENT_ID = "com.baseer.bchat.PUSH_EVENT_ID";
    public static final String EXTRA_ACCOUNT_KEY = "com.baseer.bchat.PUSH_ACCOUNT_KEY";
    public static final String EXTRA_KIND = "com.baseer.bchat.PUSH_KIND";
    private static final String PREFS = "bchat-push-v1";
    private static final String SCOPE = "verified-account-scope";
    private static final String ACCOUNT = "registered-account-key";
    private static final String TOKEN = "fcm-token";
    private static final String REGISTERED_TOKEN = "registered-fcm-token";
    private static final String INSTALLATION = "installation-id";

    private BChatPushState() { }

    private static SharedPreferences prefs(Context context) {
        return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    public static void verifiedAccount(Context context, AccountScope account) {
        if (account == null) throw new IllegalArgumentException("Verified account is required");
        prefs(context).edit().putString(SCOPE, account.key)
                .remove(ACCOUNT).remove(REGISTERED_TOKEN).apply();
    }

    public static void clearAccount(Context context) {
        prefs(context).edit().remove(SCOPE).remove(ACCOUNT).remove(REGISTERED_TOKEN).apply();
    }

    public static String installationId(Context context) {
        SharedPreferences state = prefs(context);
        String existing = state.getString(INSTALLATION, null);
        if (existing != null && validUuid(existing)) return existing;
        String created = UUID.randomUUID().toString();
        return state.edit().putString(INSTALLATION, created).commit() ? created : null;
    }

    public static boolean needsRegistration(Context context, AccountScope account) {
        SharedPreferences state = prefs(context);
        String token = state.getString(TOKEN, null);
        return account != null && account.key.equals(state.getString(SCOPE, null))
                && token != null && (state.getString(ACCOUNT, null) == null
                || !token.equals(state.getString(REGISTERED_TOKEN, null)));
    }

    public static boolean registered(Context context, AccountScope account, String token,
                                     String installationId, String serverAccountKey) {
        SharedPreferences state = prefs(context);
        if (account == null || token == null || !validUuid(installationId)
                || !validUuid(serverAccountKey) || !account.key.equals(state.getString(SCOPE, null))
                || !token.equals(state.getString(TOKEN, null))
                || !installationId.equals(state.getString(INSTALLATION, null))) return false;
        return state.edit().putString(ACCOUNT, serverAccountKey)
                .putString(REGISTERED_TOKEN, token).commit();
    }

    private static boolean validUuid(String value) {
        return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    }

    public static void observe(Context context, SharedPreferences.OnSharedPreferenceChangeListener listener) {
        prefs(context).registerOnSharedPreferenceChangeListener(listener);
    }

    public static void stopObserving(Context context, SharedPreferences.OnSharedPreferenceChangeListener listener) {
        prefs(context).unregisterOnSharedPreferenceChangeListener(listener);
    }

    public static String accountKey(Context context) {
        return prefs(context).getString(ACCOUNT, null);
    }

    public static boolean matches(Context context, String key) {
        String saved = accountKey(context);
        return validUuid(key) && key.equals(saved) && prefs(context).getString(SCOPE, null) != null;
    }

    /** Only a local routing hint; server authorization is mandatory before showing a target. */
    public static String scopeForKey(Context context, String key) {
        return matches(context, key) ? prefs(context).getString(SCOPE, null) : null;
    }

    public static void token(Context context, String token) {
        if (token == null || token.length() < 32 || token.length() > 4096) return;
        for (int i = 0; i < token.length(); i++) {
            char value = token.charAt(i);
            if (value < '!' || value > '~') return;
        }
        SharedPreferences state = prefs(context);
        if (token.equals(state.getString(TOKEN, null))) return;
        state.edit().putString(TOKEN, token)
                .remove(ACCOUNT).remove(REGISTERED_TOKEN).apply();
    }

    /** Registration still requires the authenticated same-origin BChat endpoint. */
    public static String pendingToken(Context context) {
        return prefs(context).getString(TOKEN, null);
    }

    public static void clearToken(Context context) {
        prefs(context).edit().remove(TOKEN).apply();
    }
}
