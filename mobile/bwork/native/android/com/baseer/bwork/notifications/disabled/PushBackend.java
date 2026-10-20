package com.baseer.bwork.notifications;
/** Deliberately no Firebase dependency, initializer, service, token or permission request. */
public final class PushBackend {
  public interface TokenCallback {void token(String token);void failed();}
  public static boolean configured(){return false;}
  public static void enable(){} public static void suspend(){} public static void disable(){}
  public static void token(TokenCallback callback){callback.failed();}
}
