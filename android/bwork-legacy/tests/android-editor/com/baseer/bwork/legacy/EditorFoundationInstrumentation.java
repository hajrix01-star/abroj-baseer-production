package com.baseer.bwork.legacy;

import android.app.*;
import android.content.*;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;

/** Explicit disposable emulator only. Valid local fixtures and ordinary file-I/O failure. */
public final class EditorFoundationInstrumentation extends Instrumentation {
    static final String CO="demo-nour", CV=CO+"-ops";
    static final String[] PREFS={com.baseer.bwork.legacy.compat.LegacyIdentity.SETTINGS,com.baseer.bwork.legacy.compat.LegacyIdentity.EDITOR_RECOVERY,"share-preview"};
    final ArrayList<String> results=new ArrayList<>();
    final Map<String,Map<String,?>> oldPrefs=new LinkedHashMap<>();
    final Map<String,Object> oldStatics=new LinkedHashMap<>();
    Map<String,EditorState> oldEditors; Map<String,Object> oldOrphans;
    Map<String,String> originalFiles;
    Activity activity; ChatStore store; File fixture,root,held; ChatStore.Attachment first,second;
    boolean disposable,prepared; String mode="all";
    @Override public void onCreate(Bundle args){super.onCreate(args);disposable=args!=null&&"true".equals(args.getString("disposable"));if(args!=null)mode=args.getString("mode","all");start();}
    @Override public void onStart(){
        Bundle output=new Bundle();boolean pass=false;
        try{
            if(!disposable)throw new AssertionError("Pass -e disposable true on the authorized disposable emulator only");
            if(!Arrays.asList("all","editor","capacity","orphan").contains(mode))throw new AssertionError("Unknown mode");
            prepare();launch();
            if(mode.equals("all")||mode.equals("editor")){editorFlow();previewFailureFlow();}
            if(mode.equals("all")||mode.equals("orphan"))orphanFlow();
            if(mode.equals("all")||mode.equals("capacity"))capacityFlow();
            pass=true;
        }catch(Throwable problem){output.putString("failure",android.util.Log.getStackTraceString(problem));}
        finally{try{restore();}catch(Throwable problem){pass=false;output.putString("restore_failure",android.util.Log.getStackTraceString(problem));}}
        output.putString("stream","\n"+(pass?"PASS ":"FAILED after ")+results.size()+" reconstructed editor checks; mode="+mode+"\n"+String.join("\n",results)+"\n"+output.getString("failure","")+output.getString("restore_failure",""));
        finish(pass?Activity.RESULT_OK:Activity.RESULT_CANCELED,output);
    }
    void check(boolean value,String message){if(!value)throw new AssertionError(message);results.add("PASS "+message);}
    static Field field(Class<?> type,String name){try{Field f=type.getDeclaredField(name);f.setAccessible(true);return f;}catch(Exception error){throw new AssertionError(error);}}
    static Object get(Object target,String name){try{return field(target instanceof Class?(Class<?>)target:target.getClass(),name).get(target instanceof Class?null:target);}catch(Exception error){throw new AssertionError(error);}}
    static void set(Object target,String name,Object value){try{field(target instanceof Class?(Class<?>)target:target.getClass(),name).set(target instanceof Class?null:target,value);}catch(Exception error){throw new AssertionError(error);}}
    static Object call(Object target,String name,Class<?>[] types,Object... values){try{Method method=(target instanceof Class?(Class<?>)target:target.getClass()).getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(target instanceof Class?null:target,values);}catch(InvocationTargetException error){throw new AssertionError(error.getCause());}catch(Exception error){throw new AssertionError(error);}}
    void invoke(String name){call(activity,name,new Class<?>[0]);}
    void ui(Runnable work){final Throwable[] error={null};runOnMainSync(()->{try{work.run();}catch(Throwable value){error[0]=value;}});if(error[0]!=null)throw new AssertionError(error[0]);}
    void await(String label,BooleanSupplier predicate){long end=SystemClock.uptimeMillis()+20000;while(SystemClock.uptimeMillis()<end){final boolean[] value={false};ui(()->value[0]=predicate.getAsBoolean());if(value[0])return;SystemClock.sleep(40);}throw new AssertionError("Timed out: "+label);}
    void drain()throws Exception{ExecutorService executor=(ExecutorService)get(MainActivity.class,"STORE_IO");executor.submit(()->{}).get(20,TimeUnit.SECONDS);ui(()->{});executor.submit(()->{}).get(20,TimeUnit.SECONDS);ui(()->{});}
    Map<String,EditorState> editors(){return (Map<String,EditorState>)get(MainActivity.class,"processEditors");}
    Map<String,Object> orphans(){return (Map<String,Object>)get(MainActivity.class,"processOrphanEditors");}
    String screen(){return (String)get(activity,"screen");}
    EditText composer(){return (EditText)get(activity,"composer");}
    EditorState draft(){return (EditorState)get(activity,"draftEditor");}
    View tagged(String tag){return activity.getWindow().getDecorView().findViewWithTag(tag);}
    View find(View root,java.util.function.Predicate<View> predicate){if(predicate.test(root))return root;if(root instanceof ViewGroup){ViewGroup group=(ViewGroup)root;for(int i=0;i<group.getChildCount();i++){View found=find(group.getChildAt(i),predicate);if(found!=null)return found;}}return null;}
    String label(String name){return activity.getString(activity.getResources().getIdentifier(name,"string",activity.getPackageName()));}
    void clickDescription(String value){ui(()->{View view=find(activity.getWindow().getDecorView(),candidate->value.contentEquals(candidate.getContentDescription()==null?"":candidate.getContentDescription()));if(view==null)throw new AssertionError("Missing description "+value);view.performClick();});}
    void clickTag(String value){ui(()->{View view=tagged(value);if(view==null)throw new AssertionError("Missing tag "+value);view.performClick();});}
    void prepare()throws Exception{
        Context context=getTargetContext();originalFiles=hashTree(context.getFilesDir());
        for(String name:PREFS)oldPrefs.put(name,new LinkedHashMap<>(context.getSharedPreferences(name,0).getAll()));
        for(String name:new String[]{"processStore","editorStore","editorProcessEpoch","activeActivity","recoveryReceipts"})oldStatics.put(name,get(MainActivity.class,name));
        oldStatics.put("processDemoSession",get(LocalSettings.class,"processDemoSession"));
        oldEditors=new LinkedHashMap<>(editors());oldOrphans=new LinkedHashMap<>(orphans());prepared=true;
        fixture=new File(context.getFilesDir(),"reconstructed-editor-fixture-"+UUID.randomUUID());if(!fixture.mkdir())throw new IOException("Fixture directory unavailable");
        root=new File(fixture,"state.bin");store=new ChatStore(root);first=attachment("first.txt");second=attachment("second.txt");
        store.setDraft(CO,CV,"durable before",Arrays.asList(first,second),store.lastMessage(CO,CV).id);
        SharedPreferences.Editor preferences=context.getSharedPreferences(PREFS[0],0).edit();
        if(!preferences.putBoolean("demo-entry-active",true).putBoolean("remember-demo-entry",true).putString("interface-language","en").commit())throw new IOException("Fixture preference setup failed");
        ui(()->{editors().clear();orphans().clear();set(MainActivity.class,"processStore",store);set(MainActivity.class,"editorStore",store);set(MainActivity.class,"editorProcessEpoch",UUID.randomUUID().toString());set(LocalSettings.class,"processDemoSession",true);});
        check(true,"isolated valid store installed before Activity startup; ordinary root untouched");
    }
    ChatStore.Attachment attachment(String name)throws Exception{File file=new File(fixture,name);try(FileOutputStream stream=new FileOutputStream(file)){stream.write(("fixture "+name).getBytes("UTF-8"));stream.getFD().sync();}return new ChatStore.Attachment(file.getCanonicalPath(),name,"text/plain",file.length());}
    void launch(){activity=startActivitySync(new Intent(Intent.ACTION_MAIN).setComponent(new ComponentName(getTargetContext(),MainActivity.class)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));await("initialized isolated store",()->!Boolean.TRUE.equals(get(activity,"initializing"))&&get(activity,"store")==store);check(screen().equals("list"),"startup reaches ordinary list using isolated store");}
    void openChat(){ui(()->call(activity,"showChat",new Class<?>[]{String.class,String.class},CO,CV));await("chat and bounded history",()->screen().equals("chat")&&!Boolean.TRUE.equals(get(activity,"historyLoading"))&&composer()!=null);}
    void blockRoot()throws Exception{drain();held=new File(fixture,"held-root");Files.move(root.toPath(),held.toPath());if(!root.mkdir())throw new IOException("Cannot install ordinary root-path I/O fixture");check(true,"ordinary disposable write failure enabled after pending writes drained");}
    void unblockRoot()throws Exception{if(held!=null){drain();if(!root.delete())throw new IOException("Cannot remove empty root-path fixture");Files.move(held.toPath(),root.toPath());held=null;}}
    void failureSettled(){await("failed save retains model",()->draft()!=null&&draft().failure()!=null&&!Boolean.TRUE.equals(get(activity,"navigationSaving")));}
    void recreateActivity(){Activity previous=activity;ActivityMonitor monitor=addMonitor(MainActivity.class.getName(),null,false);ui(previous::recreate);Activity next=monitor.waitForActivityWithTimeout(20000);removeMonitor(monitor);if(next==null||next==previous)throw new AssertionError("Activity recreation did not replace instance");activity=next;await("recreated store and editor",()->!Boolean.TRUE.equals(get(activity,"initializing"))&&get(activity,"store")==store&&!Boolean.TRUE.equals(get(activity,"historyLoading")));}
    void editorFlow()throws Exception{
        openChat();drain();check(composer().getText().toString().equals("durable before"),"durable fixture draft displayed");
        check(draft().snapshot().files.size()==2&&draft().snapshot().replyId!=null,"durable attachments and reply displayed");
        blockRoot();ui(()->{composer().setText("unsaved عربي editor latest");composer().setSelection(7);});
        clickTag("bwork-draft-remove-"+first.id);clickDescription(label("ui_165"));
        ui(()->invoke("showList"));failureSettled();
        check(screen().equals("chat")&&composer().getText().toString().equals("unsaved عربي editor latest"),"failed save gates chat navigation and keeps exact text");
        check(draft().snapshot().files.size()==1&&draft().snapshot().files.get(0).id.equals(second.id)&&draft().snapshot().replyId==null,"failed save preserves attachment exclusion and cleared reply");
        ui(()->invoke("showSettings"));failureSettled();check(screen().equals("chat"),"failed draft gates settings navigation");
        ui(()->invoke("exitDemo"));failureSettled();check(screen().equals("chat")&&getTargetContext().getSharedPreferences(PREFS[0],0).getBoolean("demo-entry-active",false),"failed draft gates logout without changing entry state");
        ui(()->call(activity,"applyLanguage",new Class<?>[]{String.class},"ar"));failureSettled();check(getTargetContext().getSharedPreferences(PREFS[0],0).getString("interface-language","").equals("en"),"failed draft gates language preference and recreation");
        ui(()->composer().setSelection(7));recreateActivity();
        check(screen().equals("chat")&&composer().getText().toString().equals("unsaved عربي editor latest")&&composer().getSelectionStart()==7,"actual recreation keeps unsaved text and cursor");
        check(draft().snapshot().files.size()==1&&draft().snapshot().replyId==null,"actual recreation keeps excluded file and cleared quote");
        unblockRoot();ui(()->invoke("showList"));await("durable navigation retry",()->screen().equals("list"));drain();
        ChatStore reopened=new ChatStore(root);ChatStore.Draft persisted=reopened.draft(CO,CV);
        check(persisted.text.equals("unsaved عربي editor latest")&&persisted.attachments.size()==1&&persisted.replyToMessageId==null,"retry durably saves one atomic intended editor before navigation");
        openChat();drain();int before=store.messageCount(CO,CV);ui(()->{composer().setText("exactly once local send");invoke("sendDraft");invoke("sendDraft");});
        await("local send completion",()->!Boolean.TRUE.equals(get(activity,"sending"))&&!draft().sending()&&composer().getText().length()==0);drain();
        check(store.messageCount(CO,CV)==before+1,"repeated Send admits exactly one local message");
        check(new ChatStore(root).messageCount(CO,CV)==before+1,"sent message is present after store reopen");
        ui(()->invoke("showList"));await("list after send",()->screen().equals("list"));
    }
    void previewFailureFlow()throws Exception{
        ChatStore.PendingShare pending=store.stagePendingShare("durable share caption",Arrays.asList(first,second));showPreview(pending);drain();
        blockRoot();ui(()->((EditText)get(activity,"previewCaption")).setText("unsaved preview عربي"));clickTag("bwork-preview-remove-"+first.id);
        ui(()->call(activity,"showPicker",new Class<?>[]{boolean.class},true));
        await("failed preview navigation",()->((EditorState)get(activity,"previewEditor")).failure()!=null&&!Boolean.TRUE.equals(get(activity,"navigationSaving")));
        check(screen().equals("preview")&&((EditText)get(activity,"previewCaption")).getText().toString().equals("unsaved preview عربي"),"failed preview save gates recipient navigation and preserves caption");
        check(((EditorState)get(activity,"previewEditor")).snapshot().files.size()==1&&store.pendingShare().attachments.size()==2,"failed preview preserves editor exclusion while durable share stays unchanged");
        recreateActivity();check(screen().equals("preview")&&((EditText)get(activity,"previewCaption")).getText().toString().equals("unsaved preview عربي")&&((ArrayList<?>)get(activity,"previewFiles")).size()==1,"actual recreation preserves unsaved preview caption and file exclusion");
        unblockRoot();ui(()->call(activity,"showPicker",new Class<?>[]{boolean.class},true));await("preview save then recipient navigation",()->screen().equals("picker"));drain();
        ChatStore.PendingShare saved=new ChatStore(root).pendingShare();check(saved.previewEdited&&saved.text.equals("unsaved preview عربي")&&saved.attachments.size()==1&&saved.attachments.get(0).id.equals(second.id),"preview retry is durably atomic after store reopen");
        showPreview(store.pendingShare());int before=store.messageCount(CO,CV);ui(()->{invoke("sendShare");invoke("sendShare");});
        await("share explicit local send",()->store.pendingShare()==null&&screen().equals("chat")&&!Boolean.TRUE.equals(get(activity,"sending")));drain();
        check(store.messageCount(CO,CV)==before+1&&new ChatStore(root).isPendingShareResolved(pending.id),"repeated explicit share Send produces one message and durable terminal receipt");
        ui(()->invoke("showList"));await("list after preview",()->screen().equals("list"));
    }
    void admit(EditorState.Snapshot value){call(MainActivity.class,"admitRecoveredEditor",new Class<?>[]{ChatStore.class,EditorState.Snapshot.class,boolean.class},store,value,false);}
    EditorState.Snapshot orphan(int number){return new EditorState.Snapshot(CO,"missing-normal-group-"+number,null,"preserved orphan "+number+" عربي",Collections.singletonList(second),null,1,null,null,null);}
    void orphanFlow()throws Exception{
        drain();ui(()->{editors().clear();orphans().clear();admit(orphan(0));invoke("showList");});
        check(orphans().size()==1,"valid missing destination is retained read-only");clickTag("bwork-orphan-recovery-banner");await("orphan review",()->screen().equals("recovery"));
        check(((TextView)tagged("bwork-orphan-recovery-text")).getText().toString().equals("preserved orphan 0 عربي"),"recovery surface displays exact saved text");
        check(find(activity.getWindow().getDecorView(),view->view instanceof EditText)==null,"orphan review exposes no editable composer or automatic retarget");
        Bundle saved=new Bundle();ui(()->call(activity,"onSaveInstanceState",new Class<?>[]{Bundle.class},saved));
        check(((ArrayList<?>)saved.getSerializable("orphanRecovery")).size()==1,"read-only recovery survives saved state");
        recreateActivity();check(screen().equals("recovery")&&orphans().size()==1,"actual recreation retains read-only recovery");
        check(new File(second.path).isFile(),"recovery never deletes the original attachment");
        ui(()->{orphans().clear();invoke("showList");});
    }
    void showPreview(ChatStore.PendingShare pending){ui(()->{set(activity,"previewShareId",pending.id);set(activity,"previewCompany",CO);set(activity,"previewConversation",CV);set(activity,"previewText",null);set(activity,"previewEditor",null);invoke("showSharePreview");});await("explicit selected preview",()->screen().equals("preview")&&get(activity,"previewCaption")!=null);}
    void capacityFlow()throws Exception{
        drain();store.setDraft(CO,CV,"capacity durable",Arrays.asList(first,second),null);
        ui(()->{editors().clear();orphans().clear();for(int i=0;i<4;i++)admit(orphan(i));invoke("showList");});
        ChatStore.PendingShare pending=store.stagePendingShare("original share caption",Arrays.asList(first,second));showPreview(pending);
        EditText caption=(EditText)get(activity,"previewCaption");check(!caption.isEnabled()&&!tagged("bwork-share-send").isEnabled(),"four orphans disable new clean preview caption and send");
        check(!tagged("bwork-preview-remove-"+first.id).isEnabled(),"four orphans disable preview attachment removal");
        final EditText cleanCaption=caption;
        ui(()->{cleanCaption.setText("rejected fifth editor");tagged("bwork-preview-remove-"+first.id).performClick();invoke("sendShare");});drain();
        EditorState preview=(EditorState)get(activity,"previewEditor");check(!preview.dirty()&&!preview.sending()&&store.pendingShare().attachments.size()==2,"preview method guards reject fifth dirty or sending snapshot");
        Bundle saved=new Bundle();ui(()->call(activity,"onSaveInstanceState",new Class<?>[]{Bundle.class},saved));
        check(((ArrayList<?>)saved.getSerializable("orphanRecovery")).size()+((ArrayList<?>)saved.getSerializable("editorRecovery")).size()==4,"saved-state recovery remains bounded at four editors");
        ui(()->invoke("showList"));openChat();
        check(!composer().isEnabled(),"four orphans disable clean normal draft composer");
        View removal=tagged("bwork-draft-remove-"+first.id);if(removal==null)removal=tagged("bwork-draft-remove-"+second.id);
        check(removal!=null,"normal draft removal fixture remains visible in the view tree");
        View remove=removal;check(!remove.isEnabled(),"four orphans disable normal draft attachment removal");ui(remove::performClick);
        ui(()->composer().setText("rejected normal draft overflow"));check(!draft().dirty(),"normal draft method guard cannot create fifth recovery record");
        ui(()->invoke("showList"));
        SharedPreferences legacy=getTargetContext().getSharedPreferences("share-preview",0);
        if(!legacy.edit().putString("id",pending.id).putString("text","legacy edited caption عربي").putStringSet("attachments",new HashSet<>(Collections.singletonList(second.id))).commit())throw new IOException("Legacy fixture preference write failed");
        showPreview(pending);caption=(EditText)get(activity,"previewCaption");
        check(Boolean.TRUE.equals(get(activity,"previewMigrationBlocked"))&&!caption.isEnabled()&&caption.getText().toString().equals("legacy edited caption عربي"),"full capacity shows exact legacy caption read-only");
        check(((ArrayList<?>)get(activity,"previewFiles")).size()==1&&!store.pendingShare().previewEdited&&store.pendingShare().attachments.size()==2,"legacy excluded file remains excluded visually without premature migration");
        recreateActivity();check(((EditText)get(activity,"previewCaption")).getText().toString().equals("legacy edited caption عربي")&&((ArrayList<?>)get(activity,"previewFiles")).size()==1,"legacy caption and exclusion survive actual recreation at capacity");
        ui(()->{orphans().remove(orphans().keySet().iterator().next());invoke("showSharePreview");});
        await("legacy preview durable migration after slot available",()->store.pendingShare()!=null&&store.pendingShare().previewEdited);drain();
        ChatStore.PendingShare persisted=new ChatStore(root).pendingShare();check(persisted.text.equals("legacy edited caption عربي")&&persisted.attachments.size()==1&&persisted.attachments.get(0).id.equals(second.id),"available slot atomically migrates legacy caption and exact file selection");
        check(((EditText)get(activity,"previewCaption")).isEnabled()&&tagged("bwork-share-send").isEnabled(),"preview editing resumes after capacity becomes available");
        ui(()->{orphans().clear();invoke("showList");});drain();
    }
    void restore()throws Exception{
        if(!prepared)return;
        if(held!=null)unblockRoot();
        if(activity!=null){ui(activity::finish);await("fixture Activity destroyed",()->activity.isDestroyed());}drain();
        for(String name:PREFS){SharedPreferences preferences=getTargetContext().getSharedPreferences(name,0);SharedPreferences.Editor edit=preferences.edit().clear();for(Map.Entry<String,?> entry:oldPrefs.get(name).entrySet()){Object value=entry.getValue();String key=entry.getKey();if(value instanceof String)edit.putString(key,(String)value);else if(value instanceof Boolean)edit.putBoolean(key,(Boolean)value);else if(value instanceof Integer)edit.putInt(key,(Integer)value);else if(value instanceof Long)edit.putLong(key,(Long)value);else if(value instanceof Float)edit.putFloat(key,(Float)value);else if(value instanceof Set)edit.putStringSet(key,new HashSet<>((Set<String>)value));else throw new AssertionError("Unexpected preference type");}if(!edit.commit())throw new IOException("Cannot restore "+name);if(!preferences.getAll().equals(oldPrefs.get(name)))throw new AssertionError("Preference restoration mismatch "+name);}
        ui(()->{editors().clear();editors().putAll(oldEditors);orphans().clear();orphans().putAll(oldOrphans);for(Map.Entry<String,Object> entry:oldStatics.entrySet())if(!entry.getKey().equals("processDemoSession"))set(MainActivity.class,entry.getKey(),entry.getValue());set(LocalSettings.class,"processDemoSession",oldStatics.get("processDemoSession"));});
        Map<String,String> after=hashTree(getTargetContext().getFilesDir());for(Map.Entry<String,String> entry:originalFiles.entrySet())if(!entry.getValue().equals(after.get(entry.getKey())))throw new AssertionError("Preexisting file changed: "+entry.getKey());
        check(true,"all preexisting private files retain exact SHA-256 and all touched preferences restored");
        if(fixture!=null)deleteFixture(fixture);check(true,"only this run's disposable fixture removed");
    }
    static Map<String,String> hashTree(File root)throws Exception{Map<String,String> result=new TreeMap<>();hashFiles(root,root,result);return result;}
    static void hashFiles(File root,File file,Map<String,String> output)throws Exception{File[] children=file.listFiles();if(children!=null){for(File child:children)hashFiles(root,child,output);}else if(file.isFile()){MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream stream=new FileInputStream(file)){byte[] buffer=new byte[8192];int count;while((count=stream.read(buffer))!=-1)digest.update(buffer,0,count);}StringBuilder hash=new StringBuilder();for(byte value:digest.digest())hash.append(String.format(Locale.ROOT,"%02x",value&255));output.put(root.toPath().relativize(file.toPath()).toString(),hash.toString());}}
    void deleteFixture(File file)throws IOException{if(!file.getCanonicalPath().startsWith(fixture.getCanonicalPath()+File.separator)&&!file.getCanonicalPath().equals(fixture.getCanonicalPath()))throw new IOException("Outside disposable fixture");File[] children=file.listFiles();if(children!=null)for(File child:children)deleteFixture(child);Files.deleteIfExists(file.toPath());}
}
