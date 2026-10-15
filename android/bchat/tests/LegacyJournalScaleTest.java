import com.baseer.freshchat.ChatStore;
import java.io.*;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
/** Ordinary large valid history, testing first-migration splitting; no malformed input. */
public final class LegacyJournalScaleTest {
 public static void main(String[] args)throws Exception {
  File dir=Files.createTempDirectory("bchat-valid-large-migration-").toFile();
  try {
   ChatStore source=new ChatStore(new File(dir,"source.bin"));StringBuilder b=new StringBuilder();for(int i=0;i<19990;i++)b.append('x');String body=b.toString();
   for(int i=0;i<450;i++)source.sendDraftSnapshot("demo-nour","demo-nour-ops",body+String.format(Locale.ROOT,"%06d",i),Collections.<ChatStore.Attachment>emptyList(),null,UUID.randomUUID().toString());
   source.setDraft("demo-nour","demo-nour-ops","valid migration draft العربية",Collections.<ChatStore.Attachment>emptyList(),source.lastMessage("demo-nour","demo-nour-ops").id);
   File legacy=new File(dir,"legacy.bin");Field field=ChatStore.class.getDeclaredField("state");field.setAccessible(true);
   try(ObjectOutputStream out=new ObjectOutputStream(new FileOutputStream(legacy))){out.writeObject(field.get(source));}
   byte[] original=Files.readAllBytes(legacy.toPath());if(original.length>=32L*1024*1024)throw new AssertionError("Fixture must fit legacy cap");
   ChatStore migrated=new ChatStore(legacy);check(Arrays.equals(original,Files.readAllBytes(legacy.toPath())),"normal legacy open is read-only");
   migrated.markRead("demo-nour","demo-nour-ops");try(DataInputStream in=new DataInputStream(new FileInputStream(legacy))){check(in.readInt()==0x42434834,"first write publishes BCH4 root");}
   migrated=migrated.reopen();check(migrated.messageCount("demo-nour","demo-nour-ops")==710,"all messages survive first multi-segment migration");check(migrated.lastMessage("demo-nour","demo-nour-ops").text.equals(body+"000449"),"last complete large text survives");check(migrated.draft("demo-nour","demo-nour-ops").text.equals("valid migration draft العربية"),"draft survives migration");
   File archive=new File(dir,"legacy.bin.legacy-"+hex(MessageDigest.getInstance("SHA-256").digest(original)));check(archive.isFile()&&Arrays.equals(original,Files.readAllBytes(archive.toPath())),"exact legacy source bytes archived");
   System.out.println("PASS: 6 ordinary large-migration checks; legacy_bytes="+original.length+"; decoded_records_bytes_exceed_16MiB=true");
  }finally{remove(dir);}
 }
 static void check(boolean condition,String label){if(!condition)throw new AssertionError(label);System.out.println("PASS "+label);}
 static String hex(byte[] b){StringBuilder s=new StringBuilder();for(byte x:b)s.append(String.format(Locale.ROOT,"%02x",x&255));return s.toString();}
 static void remove(File f)throws IOException{if(f.isDirectory()){File[] files=f.listFiles();if(files!=null)for(File c:files)remove(c);}Files.deleteIfExists(f.toPath());}
}
