package com.baseer.bwork.legacy;

import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Ordinary synthetic provider behavior, no native codecs, malformed payloads or security probes. */
public final class MediaFoundationRecoveryTest {
    static int checks;
    static Path root;
    static final Uri URI=Uri.parse("content://bwork.synthetic.media/input");
    interface Action { void run() throws Exception; }
    static void check(boolean value,String label) { if(!value)throw new AssertionError(label);checks++;System.out.println("PASS "+label); }
    static IOException failure(Action action)throws Exception {try{action.run();throw new AssertionError("Expected IO failure");}catch(IOException expected){return expected;}}
    static final class Provider extends ContentResolver {
        final byte[] bytes; final long declared;
        String mime="application/octet-stream";
        boolean failRead,failWrite;
        int opens,closes;
        ByteArrayOutputStream output=new ByteArrayOutputStream();
        Provider(byte[] bytes,long declared){this.bytes=bytes;this.declared=declared;}
        public String getType(Uri uri){return mime;}
        public Cursor query(Uri uri,String[] columns,String selection,String[] args,String sort){return new Cursor(){
            public boolean moveToFirst(){return true;}
            public int getColumnIndex(String column){return OpenableColumns.DISPLAY_NAME.equals(column)?0:1;}
            public boolean isNull(int column){return column==1&&declared<0;}
            public String getString(int column){return "synthetic.bin";}
            public long getLong(int column){return declared;}
            public void close(){}
        };}
        public InputStream openInputStream(Uri uri){
            opens++;
            if(failRead)return new InputStream(){int count;public int read()throws IOException{if(count++==20)throw new IOException("Provider disconnected");return 1;}};
            return new ByteArrayInputStream(bytes){@Override public void close()throws IOException{closes++;if(closes>1)throw new IOException("Duplicate close");super.close();}};
        }
        public OutputStream openOutputStream(Uri uri,String mode){
            opens++;output=new ByteArrayOutputStream();
            if(!failWrite)return output;
            return new OutputStream(){public void write(int value)throws IOException{if(output.size()==20)throw new IOException("Destination full");output.write(value);}};
        }
    }
    static final class App extends Context {
        final Provider provider; App(Provider provider){this.provider=provider;}
        public ContentResolver getContentResolver(){return provider;}
        public File getFilesDir(){return root.toFile();}
    }
    static ChatStore.Attachment take(Provider provider)throws IOException{return AttachmentSupport.importUri(new App(provider),URI,null,AttachmentSupport.MAX_BATCH_BYTES);}
    static int files()throws IOException{Path directory=root.resolve("attachments");if(!Files.exists(directory))return 0;try(java.util.stream.Stream<Path> entries=Files.list(directory)){return (int)entries.count();}}
    public static void main(String[] args)throws Exception{
        root=Files.createTempDirectory("bwork-media-recovery-");
        try{
            byte[] bytes="Ordinary synthetic document content for original-byte copying.\n".getBytes("UTF-8");
            String hash=AttachmentSupport.hex(AttachmentSupport.newDigest().digest(bytes));
            for(long size:new long[]{bytes.length,-1}){
                Provider provider=new Provider(bytes,size);ChatStore.Attachment file=take(provider);
                check(file.size==bytes.length&&hash.equals(file.sha256),"Known/unknown-size import records byte count and digest "+size);
                check(Arrays.equals(bytes,Files.readAllBytes(Paths.get(file.path)))&&provider.closes==1,"Original copied unchanged; provider stream closed once "+size);
                AttachmentSupport.saveToUri(new App(provider),file,URI);
                check(Arrays.equals(bytes,provider.output.toByteArray()),"Export preserves exact bytes "+size);
            }
            for(long declared:new long[]{bytes.length-1,bytes.length+1}){
                Provider provider=new Provider(bytes,declared);int count=files();
                check("ATTACHMENT_IMPORT_CHANGED".equals(failure(()->take(provider)).getMessage())&&count==files(),"Stale size/clean early EOF rejects incomplete admission "+declared);
            }
            Provider empty=new Provider(new byte[0],0);ChatStore.Attachment zero=take(empty);
            check(zero.size==0&&zero.sha256.length()==64,"Intentional empty generic file remains supported");
            for(String mime:new String[]{"image/png","audio/mp4","video/mp4","application/pdf"}){
                Provider provider=new Provider(new byte[0],-1);provider.mime=mime;
                check("ATTACHMENT_IMPORT_EMPTY_MEDIA".equals(failure(()->take(provider)).getMessage()),"Empty media has clear admission diagnostic "+mime);
            }
            Provider disconnected=new Provider(bytes,bytes.length);disconnected.failRead=true;int count=files();
            failure(()->take(disconnected));check(count==files(),"Ordinary provider disconnect leaves no newly admitted file");
            Provider provider=new Provider(bytes,bytes.length);ChatStore.Attachment file=take(provider);
            provider.failWrite=true;
            check("ATTACHMENT_EXPORT_PARTIAL".equals(failure(()->AttachmentSupport.saveToUri(new App(provider),file,URI)).getMessage())&&provider.output.size()==20,"Full destination warns that partial output may remain");
            check(Arrays.equals(bytes,Files.readAllBytes(Paths.get(file.path))),"Failed export preserves the private original");
            ChatStore.Attachment fresh=new ChatStore.Attachment(file.id,file.path,file.name,file.mime,file.size);
            ChatStore.Attachment admitted=AttachmentSupport.withIntegrity(new App(provider),fresh);
            check(fresh.sha256==null&&hash.equals(admitted.sha256)&&admitted.id.equals(fresh.id),"New capture/recording admission helper adds digest without rewriting bytes or identity");
            check(AttachmentSupport.withIntegrity(new App(provider),admitted)==admitted,"Already verified metadata is retained");
            File state=root.resolve("ordinary-store.bin").toFile();ChatStore store=new ChatStore(state);
            String co=store.companies().get(0).id,cv=store.conversations(co).get(0).id;
            store.setDraft(co,cv,"synthetic",Collections.singletonList(file));store=new ChatStore(state);
            check(hash.equals(store.draft(co,cv).attachments.get(0).sha256),"Digest survives draft reload");
            ChatStore.Message sent=store.send(co,cv);store=new ChatStore(state);
            check(hash.equals(store.message(co,cv,sent.id).attachments.get(0).sha256),"Digest survives local send/restart");
            store.deleteMessageLocally(co,cv,sent.id);store=new ChatStore(state);store.undoLocalDeletion(co,cv,sent.id);store=new ChatStore(state);
            check(hash.equals(store.message(co,cv,sent.id).attachments.get(0).sha256)&&Arrays.equals(bytes,Files.readAllBytes(Paths.get(file.path))),"Durable undo preserves original bytes and digest");
            Thread.currentThread().interrupt();
            try{check(failure(()->AttachmentSupport.hashFile(new File(file.path),file.size))!=null&&Thread.currentThread().isInterrupted(),"Canceled admission hashing retains interruption");}finally{Thread.interrupted();}
            System.out.println("PASS "+checks+" ordinary recovered media checks; Android NOT executed");
        }finally{try(java.util.stream.Stream<Path> paths=Files.walk(root)){paths.sorted(Comparator.reverseOrder()).forEach(path->{try{Files.delete(path);}catch(IOException e){throw new RuntimeException(e);}});}}
    }
}
