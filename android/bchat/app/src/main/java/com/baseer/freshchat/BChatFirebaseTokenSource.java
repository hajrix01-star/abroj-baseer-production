package com.baseer.freshchat;

import android.content.Context;

import com.google.firebase.messaging.FirebaseMessaging;

/** Optional SDK bridge, compiled only with the owner-supplied Firebase project. */
public final class BChatFirebaseTokenSource {
    private BChatFirebaseTokenSource() { }

    public static void refresh(Context context) {
        Context app = context.getApplicationContext();
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(
                token -> BChatPushState.token(app, token));
    }
}
