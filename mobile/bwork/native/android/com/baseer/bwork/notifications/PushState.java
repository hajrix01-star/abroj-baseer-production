package com.baseer.bwork.notifications;
import android.content.Context;
import android.content.SharedPreferences;
import android.app.NotificationManager;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import org.json.JSONArray;

/** Routing metadata only. No credentials, message content, arbitrary URLs or server authority. */
public final class PushState {
  static volatile boolean foreground=false;
  private static boolean blocked=false;
  private static SharedPreferences prefs(Context c){return c.getSharedPreferences("bwork-push-v1",Context.MODE_PRIVATE);}
  static boolean uuid(String s){return s!=null&&s.matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");}
  static String hash(String s){try {byte[] b=MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));StringBuilder v=new StringBuilder();for(byte p:b)v.append(String.format(java.util.Locale.ROOT,"%02x",p&255));return v.toString();}catch(Exception e){throw new IllegalStateException("push_unavailable");}}
  static synchronized long epoch(Context c){return prefs(c).getLong("epoch",0);}
  static synchronized String installation(Context c){String id=prefs(c).getString("installation",null);if(uuid(id))return id;id=UUID.randomUUID().toString();return prefs(c).edit().putString("installation",id).commit()?id:null;}
  static synchronized String existingInstallation(Context c){return prefs(c).getString("installation","");}
  static synchronized boolean enabled(Context c){return !blocked&&prefs(c).getBoolean("enabled",false);}
  static synchronized boolean enable(Context c){blocked=false;return prefs(c).edit().putBoolean("enabled",true).commit();}
  static synchronized String scope(Context c){return blocked?"":prefs(c).getString("scope","");}
  static synchronized String account(Context c){return blocked?"":prefs(c).getString("account","");}
  static synchronized boolean clear(Context c){blocked=true;SharedPreferences p=prefs(c);boolean ok=p.edit().putLong("epoch",epoch(c)+1).putBoolean("enabled",false).remove("scope").remove("account").remove("tokenHash").remove("seen").commit();NotificationManager m=c.getSystemService(NotificationManager.class);if(m!=null)m.cancelAll();return ok;}
  static synchronized boolean token(Context c,String token){if(token==null||!token.matches("[!-~]{32,4096}"))return false;SharedPreferences p=prefs(c);String h=hash(token);return h.equals(p.getString("tokenHash",""))||p.edit().putString("tokenHash",h).putLong("epoch",epoch(c)+1).remove("scope").remove("account").commit();}
  static boolean finishEnable(Context c,long expected){return PushCallbacks.commit(PushState.class,expected,()->epoch(c),()->true,()->{if(!enable(c))return false;PushBackend.enable();return true;});}
  static boolean finishToken(Context c,long expected,String value){return PushCallbacks.commit(PushState.class,expected,()->epoch(c),()->enabled(c),()->token(c,value));}
  static synchronized boolean bind(Context c,String scope,String install,String token,String account,long epoch){SharedPreferences p=prefs(c);if(!enabled(c)||scope==null||scope.length()>16384||!uuid(account)||!uuid(install)||!install.equals(p.getString("installation",""))||epoch!=epoch(c)||!hash(token).equals(p.getString("tokenHash","")))return false;return p.edit().putString("scope",scope).putString("account",account).commit();}
  static synchronized boolean accept(Context c,String account,String kind,String event){
    if(!PushPolicy.bound(enabled(c),account(c),scope(c),account,kind,event))return false;
    try {JSONArray old=new JSONArray(prefs(c).getString("seen","[]"));java.util.List<String> seen=new java.util.ArrayList<>();for(int i=0;i<old.length();i++)seen.add(old.getString(i));java.util.List<String> next=PushPolicy.nextSeen(seen,kind+":"+event);return next!=null&&prefs(c).edit().putString("seen",new JSONArray(next).toString()).commit();}catch(Exception e){return false;}
  }
  static synchronized void language(Context c,String v){if("ar".equals(v)||"en".equals(v))prefs(c).edit().putString("language",v).apply();}
  static boolean arabic(Context c){return "ar".equals(prefs(c).getString("language","ar"));}
}
