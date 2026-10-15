package com.baseer.freshchat;

import android.content.SharedPreferences;
import java.io.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;

/** Valid model admission through the real UI class; this is a host test, not Android acceptance. */
public final class RecoveryAdmissionTest {
    static final String CO="demo-nour", CV=CO+"-ops";
    static int checks;
    static Class<?> activity;
    static Map<String,EditorState> editors;
    static Map<String,Object> orphans;
    static Method admit;
    static final Set<String> dismissed=new HashSet<>();
    static void require(boolean value,String name){if(!value)throw new AssertionError(name);checks++;System.out.println("PASS "+name);}
    static void reset(){editors.clear();orphans.clear();dismissed.clear();}
    static EditorState.Snapshot snapshot(String co,String cv,String share,String text,String reply,String token){return new EditorState.Snapshot(co,cv,share,text,Collections.emptyList(),reply,7,token,co,cv);}
    static void restore(ChatStore store,EditorState.Snapshot value,boolean readOnly)throws Exception{try{admit.invoke(null,store,value,readOnly);}catch(InvocationTargetException failure){throw new AssertionError("Valid editor admission failed",failure.getCause());}}
    public static void main(String[] args)throws Exception {
        activity=Class.forName("com.baseer.freshchat.MainActivity");
        Field editorField=activity.getDeclaredField("processEditors"),orphanField=activity.getDeclaredField("processOrphanEditors"),receipts=activity.getDeclaredField("recoveryReceipts");
        editorField.setAccessible(true);orphanField.setAccessible(true);receipts.setAccessible(true);
        editors=(Map<String,EditorState>)editorField.get(null);orphans=(Map<String,Object>)orphanField.get(null);
        SharedPreferences fake=(SharedPreferences)Proxy.newProxyInstance(RecoveryAdmissionTest.class.getClassLoader(),new Class<?>[]{SharedPreferences.class},(proxy,method,values)->{
            if(method.getName().equals("getBoolean"))return dismissed.contains((String)values[0]);
            throw new AssertionError("Host admission may only read dismissal receipts: "+method.getName());
        });receipts.set(null,fake);
        admit=activity.getDeclaredMethod("admitRecoveredEditor",ChatStore.class,EditorState.Snapshot.class,boolean.class);admit.setAccessible(true);
        Path directory=Files.createTempDirectory("bchat-valid-admission-");
        try {
            ChatStore store=new ChatStore(directory.resolve("state.bin").toFile());
            EditorState.Snapshot absent=snapshot(CO,"removed-normal-group",null,"saved orphan عربي",null,null);
            restore(store,absent,false);require(editors.isEmpty()&&orphans.size()==1,"missing normal group preserves read-only editor without breaking store startup");
            require(store.messageCount(CO,CV)>0,"ordinary history remains readable beside orphan");
            restore(store,absent,false);require(orphans.size()==1,"identical orphan snapshot deduplicates");
            String receipt=orphans.keySet().iterator().next();reset();dismissed.add(receipt);restore(store,absent,false);
            require(orphans.isEmpty(),"explicit dismissal receipt suppresses only exact saved snapshot");
            restore(store,snapshot(CO,"removed-normal-group",null,"saved orphan عربي",null,null),false);
            require(orphans.size()==1,"new editor with identical contents does not inherit old dismissal");
            reset();restore(store,snapshot(CO,CV,null,"quote draft","no-longer-present-normal-message",null),false);
            require(editors.isEmpty()&&orphans.size()==1,"missing quoted message preserves draft for review");
            reset();EditorState.Snapshot normal=snapshot(CO,CV,null,"new draft",null,null);restore(store,normal,false);
            EditorState restored=editors.values().iterator().next();require(orphans.isEmpty()&&restored.dirty()&&restored.snapshot().text.equals(normal.text),"valid editor is dirty until a real durable acknowledgement");
            restore(store,snapshot(CO,CV,null,"older bundle",null,null),false);require(restored.snapshot().text.equals(normal.text),"older bundle cannot overwrite process-owned editor");
            reset();restore(store,normal,true);require(editors.isEmpty()&&orphans.size()==1,"previous read-only review cannot silently become sendable");
            reset();String unknown=UUID.randomUUID().toString();restore(store,snapshot(null,null,unknown,"unresolved share",null,null),false);
            require(editors.isEmpty()&&orphans.size()==1,"unknown missing share preserved without automatic recipient");
            reset();ChatStore.PendingShare pending=store.stagePendingShare("original caption",Collections.emptyList());
            restore(store,snapshot(null,null,pending.id,"edited caption",null,null),false);
            require(editors.size()==1&&orphans.isEmpty()&&editors.values().iterator().next().snapshot().text.equals("edited caption"),"matching pending share recovers complete preview");
            reset();store.cancelPendingShare(pending.id);restore(new ChatStore(directory.resolve("state.bin").toFile()),snapshot(null,null,pending.id,"stale canceled caption",null,null),false);
            require(editors.isEmpty()&&orphans.isEmpty(),"durably canceled preview cannot resurrect after reopen");
            reset();pending=store.stagePendingShare("send caption",Collections.emptyList());String shareToken=UUID.randomUUID().toString();
            store.sendPendingShare(pending.id,CO,CV,null,null,shareToken);restore(store,snapshot(CO,CV,pending.id,"stale sent preview",null,shareToken),false);
            require(editors.isEmpty()&&orphans.isEmpty(),"durably sent preview cannot resurrect");
            reset();String draftToken=UUID.randomUUID().toString();store.sendDraftSnapshot(CO,CV,"draft sent",Collections.emptyList(),null,draftToken);
            restore(store,snapshot(CO,CV,null,"stale sent draft",null,draftToken),false);require(editors.isEmpty()&&orphans.isEmpty(),"authoritative committed UUID suppresses stale draft send");
            reset();restore(store,snapshot(CO,CV,null,"send not committed",null,UUID.randomUUID().toString()),false);
            restored=editors.values().iterator().next();require(restored.dirty()&&!restored.sending()&&restored.snapshot().text.equals("send not committed"),"authoritative absent UUID retains editor and permits explicit retry");
            reset();byte[] beforeAdmission=Files.readAllBytes(directory.resolve("state.bin"));for(int i=0;i<4;i++)restore(store,snapshot(CO,"missing-valid-group-"+i,null,"recovery "+i,null,null),false);
            require(orphans.size()==4&&editors.isEmpty(),"four independent valid recovery records retained");
            require(Arrays.equals(beforeAdmission,Files.readAllBytes(directory.resolve("state.bin"))),"admission never deletes or changes the store root");
            System.out.println("PASS: "+checks+" fresh recovery admission checks; Android runtime not exercised");
        } finally { reset();receipts.set(null,null);remove(directory.toFile()); }
    }
    static void remove(File file)throws IOException{File[] children=file.listFiles();if(children!=null)for(File child:children)remove(child);Files.deleteIfExists(file.toPath());}
}
