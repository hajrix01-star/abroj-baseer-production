package com.baseer.freshchat.test;

import android.app.Activity;
import android.content.*;
import java.io.*;
import java.lang.ref.WeakReference;
import java.lang.reflect.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;

/** Test-only ownership/preservation guard. It never opens the preexisting ChatStore. */
final class UiFixtureGuard {
    private static final String[] PREFS={"bchat-local-settings-v1","share-preview","bchat-editor-recovery-v1"};
    private final Context context; private final Class<?> activityType,settingsType;
    private final Map<String,Object> statics=new LinkedHashMap<>();
    private final Map<String,Map<String,Object>> prefs=new LinkedHashMap<>();
    private final Map<String,Object> editors,orphans;
    final HashMap<String,String> originals;
    private final boolean normalExisted;
    UiFixtureGuard(Context context)throws Exception {
        this.context=context;activityType=context.getClassLoader().loadClass("com.baseer.freshchat.MainActivity");settingsType=context.getClassLoader().loadClass("com.baseer.freshchat.LocalSettings");
        Object observer=get(activityType,"activeActivity");Object current=observer instanceof WeakReference?((WeakReference<?>)observer).get():null;
        if(current instanceof Activity&&!((Activity)current).isDestroyed())throw new AssertionError("Force-stop the disposable target before this isolated suite; no existing Activity is replaced");
        drain();originals=hashFiles(context.getFilesDir());normalExisted=new File(context.getFilesDir(),"chat-state-v1.bin").exists();
        for(String key:new String[]{"processStore","editorStore","editorProcessEpoch","activeActivity","recoveryReceipts"})statics.put(key,get(activityType,key));
        statics.put("processDemoSession",get(settingsType,"processDemoSession"));
        editors=new LinkedHashMap<>(map("processEditors"));orphans=new LinkedHashMap<>(map("processOrphanEditors"));
        for(String name:PREFS)prefs.put(name,copyPrefs(context.getSharedPreferences(name,0)));
    }
    void install(Object store)throws Exception {
        drain();map("processEditors").clear();map("processOrphanEditors").clear();set(activityType,"processStore",store);set(activityType,"editorStore",store);set(activityType,"editorProcessEpoch",UUID.randomUUID().toString());
    }
    void drain()throws Exception {((ExecutorService)get(activityType,"STORE_IO")).submit(()->{}).get(30,TimeUnit.SECONDS);}
    void restore(boolean preferences)throws Exception {
        drain();
        if(preferences)for(Map.Entry<String,Map<String,Object>> entry:prefs.entrySet())restorePrefs(context.getSharedPreferences(entry.getKey(),0),entry.getValue());
        map("processEditors").clear();map("processEditors").putAll(editors);map("processOrphanEditors").clear();map("processOrphanEditors").putAll(orphans);
        for(Map.Entry<String,Object> entry:statics.entrySet())if(!entry.getKey().equals("processDemoSession"))set(activityType,entry.getKey(),entry.getValue());
        set(settingsType,"processDemoSession",statics.get("processDemoSession"));
    }
    void verifyOriginals()throws Exception {
        verifyHashes(context.getFilesDir(),originals);
        if(!normalExisted&&new File(context.getFilesDir(),"chat-state-v1.bin").exists())throw new AssertionError("Ordinary root created by fixture startup");
    }
    @SuppressWarnings("unchecked") private Map<String,Object> map(String key)throws Exception{return (Map<String,Object>)get(activityType,key);}
    static Object get(Class<?> type,String name)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);return f.get(null);}
    static void set(Class<?> type,String name,Object value)throws Exception{Field f=type.getDeclaredField(name);f.setAccessible(true);f.set(null,value);}
    static HashMap<String,Object> copyPrefs(SharedPreferences values){HashMap<String,Object> result=new HashMap<>();for(Map.Entry<String,?> entry:values.getAll().entrySet()){Object value=entry.getValue();if(value instanceof Set)value=new HashSet<>((Set<?>)value);result.put(entry.getKey(),value);}return result;}
    @SuppressWarnings("unchecked") static void restorePrefs(SharedPreferences values,Map<String,Object> old)throws IOException {
        SharedPreferences.Editor edit=values.edit().clear();for(Map.Entry<String,Object> entry:old.entrySet()){String k=entry.getKey();Object v=entry.getValue();if(v instanceof String)edit.putString(k,(String)v);else if(v instanceof Boolean)edit.putBoolean(k,(Boolean)v);else if(v instanceof Integer)edit.putInt(k,(Integer)v);else if(v instanceof Long)edit.putLong(k,(Long)v);else if(v instanceof Float)edit.putFloat(k,(Float)v);else if(v instanceof Set)edit.putStringSet(k,new HashSet<>((Set<String>)v));else throw new IOException("Unsupported preference type");}
        if(!edit.commit()||!values.getAll().equals(old))throw new IOException("Preference restoration mismatch");
    }
    static HashMap<String,String> hashFiles(File root)throws Exception{HashMap<String,String> result=new HashMap<>();hash(root,root,result);return result;}
    private static void hash(File root,File file,Map<String,String> output)throws Exception {
        if(java.nio.file.Files.isSymbolicLink(file.toPath()))throw new IOException("Unexpected symlink in disposable private files");
        File[] children=file.listFiles();if(children!=null){for(File child:children)hash(root,child,output);}else if(file.isFile()){
            MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream stream=new FileInputStream(file)){byte[] bytes=new byte[8192];int n;while((n=stream.read(bytes))!=-1)digest.update(bytes,0,n);}
            StringBuilder hex=new StringBuilder();for(byte value:digest.digest())hex.append(String.format(Locale.ROOT,"%02x",value&255));output.put(root.toPath().relativize(file.toPath()).toString(),hex.toString());
        }
    }
    static void verifyHashes(File root,Map<String,String> original)throws Exception {Map<String,String> current=hashFiles(root);for(Map.Entry<String,String> entry:original.entrySet())if(!entry.getValue().equals(current.get(entry.getKey())))throw new AssertionError("Preexisting private file changed or disappeared: "+entry.getKey());}
}
