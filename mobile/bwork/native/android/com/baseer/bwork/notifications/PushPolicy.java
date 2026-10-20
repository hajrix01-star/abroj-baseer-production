package com.baseer.bwork.notifications;
import java.util.ArrayList;
import java.util.List;
/** Bounded routing hints only; private message content is never rendered. */
public final class PushPolicy {
  private PushPolicy(){}
  public static boolean valid(String account,String kind,String event){
    if(account==null||!account.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")||!("chat".equals(kind)||"task".equals(kind))||event==null||!event.matches("[1-9][0-9]{0,9}"))return false;
    try{return Long.parseLong(event)<=2147483647L;}catch(NumberFormatException e){return false;}
  }
  public static String notificationUri(String account,String kind,String event){return valid(account,kind,event)?"bwork://notification/"+account+"/"+kind+"/"+event:null;}
  public static String body(boolean arabic,String kind){return "chat".equals(kind)?(arabic?"لديك رسالة جديدة":"You have a new message"):(arabic?"لديك تحديث في المهام":"You have a task update");}
  public static boolean bound(boolean enabled,String active,String scope,String account,String kind,String event){return enabled&&active!=null&&active.equals(account)&&scope!=null&&!scope.isEmpty()&&valid(account,kind,event);}
  public static List<String> nextSeen(List<String> old,String key){if(old.contains(key))return null;List<String> next=new ArrayList<>(old.subList(Math.max(0,old.size()-127),old.size()));next.add(key);return next;}
}
