package com.baseer.bwork.legacy;

import android.content.Context;

import com.google.firebase.messaging.FirebaseMessaging;

/** Optional SDK bridge, compiled only with the owner-supplied Firebase project. */
public final class BWorkFirebaseTokenSource {
    private BWorkFirebaseTokenSource() { }

    public static void refresh(Context context) {
        Context app = context.getApplicationContext();
        FirebaseMessaging.getInstance().getToken().addOnSuccessListener(
                token -> BWorkPushState.token(app, token));
    }
}
