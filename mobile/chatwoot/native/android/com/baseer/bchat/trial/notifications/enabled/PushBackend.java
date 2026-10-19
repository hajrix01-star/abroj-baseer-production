package com.baseer.bchat.trial.notifications;
import com.google.firebase.messaging.FirebaseMessaging;
/** Only compiled by the explicitly configured build variant. No token before user opt-in. */
public final class PushBackend {
  public interface TokenCallback {void token(String token);void failed();}
  public static boolean configured(){return true;}
  public static void enable(){FirebaseMessaging.getInstance().setAutoInitEnabled(true);}
  public static void suspend(){FirebaseMessaging.getInstance().setAutoInitEnabled(false);}
  public static void disable(){suspend();FirebaseMessaging.getInstance().deleteToken();}
  public static void token(TokenCallback callback){FirebaseMessaging.getInstance().getToken().addOnSuccessListener(callback::token).addOnFailureListener(error->callback.failed());}
}
