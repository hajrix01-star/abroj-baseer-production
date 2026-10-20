package com.baseer.bwork.notifications;
import java.util.function.BooleanSupplier;
import java.util.function.LongSupplier;
import java.util.function.LongConsumer;
/** The caller's epoch check and native side effects share the revocation lock. */
public final class PushCallbacks {
  private PushCallbacks(){}
  public static boolean begin(Object lock,LongSupplier current,BooleanSupplier eligible,LongConsumer start){
    synchronized(lock){long expected=current.getAsLong();if(!eligible.getAsBoolean())return false;start.accept(expected);return true;}
  }
  public static boolean commit(Object lock,long expected,LongSupplier current,BooleanSupplier eligible,BooleanSupplier mutation){
    synchronized(lock){if(expected!=current.getAsLong()||!eligible.getAsBoolean())return false;return mutation.getAsBoolean();}
  }
}
