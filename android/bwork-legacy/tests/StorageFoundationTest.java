import com.baseer.bwork.legacy.ChatStore;
import java.io.*;
import java.nio.file.*;
import java.util.*;
/** Valid owned fixtures. No malformed-input/resource-bound probes. */
public final class StorageFoundationTest {
 static int checks; static final String CO="demo-nour",CV="demo-nour-ops";static final List<ChatStore.Attachment> NONE=Collections.emptyList();
 static void check(boolean v,String label){if(!v)throw new AssertionError(label);checks++;System.out.println("PASS "+label);}
 public static void main(String[]args)throws Exception {
  File dir=Files.createTempDirectory("bwork-foundation-recovery-").toFile();
  try {normal(dir);if(args.length>0&&args[0].equals("--scale"))scale(new File(dir,"scale"));System.out.println("PASS: "+checks+" reconstructed storage checks");}finally{remove(dir);}
 }
 static void normal(File dir)throws Exception {
  File root=new File(dir,"state.bin");ChatStore s=new ChatStore(root);int count=s.messageCount(CO,CV);
  check(s.unreadCount(CO,CV)==3,"initial unread");s.markRead(CO,CV);s=new ChatStore(root);check(s.unreadCount(CO,CV)==0,"read marker durable");check(s.unreadCount("demo-madar","demo-madar-ops")==3,"read markers isolated");
  String reply=s.lastMessage(CO,CV).id;String txt="العربية 😀 e\u0301 \uD800";File files=new File(dir,"attachments");files.mkdir();File f=new File(files,"original.txt");byte[] bytes="original\nأصل".getBytes("UTF-8");Files.write(f.toPath(),bytes);
  ChatStore.Attachment a=new ChatStore.Attachment(UUID.randomUUID().toString(),f.getAbsolutePath(),"original.txt","text/plain",bytes.length,hash(bytes));
  s.setDraft(CO,CV,txt,Arrays.asList(a),reply);s=new ChatStore(root);check(s.draft(CO,CV).text.equals(txt),"all Java text code units preserved");check(s.draft(CO,CV).replyToMessageId.equals(reply),"atomic reply persisted");check(s.draft(CO,CV).attachments.get(0).sha256.equals(hash(bytes)),"attachment digest persisted");
  byte[] before=Files.readAllBytes(root.toPath());s.setDraft(CO,CV,txt,Arrays.asList(a),reply);check(Arrays.equals(before,Files.readAllBytes(root.toPath())),"identical full editor skips commit");
  String token=UUID.randomUUID().toString();ChatStore.Message m=s.sendDraftSnapshot(CO,CV,txt,Arrays.asList(a),reply,token);check(s.messageCount(CO,CV)==count+1&&s.draft(CO,CV).text.isEmpty(),"atomic snapshot send");s.setDraft(CO,CV,"new",NONE,null);
  s=new ChatStore(root);check(s.findMessageByClientId(CO,CV,token).id.equals(m.id),"committed token found after reopen");s.sendDraftSnapshot(CO,CV,"stale",NONE,null,token);check(s.draft(CO,CV).text.equals("new"),"idempotent send preserves newer draft");
  s.deleteMessageLocally(CO,CV,m.id);s=new ChatStore(root);check(s.attachmentPaths().contains(a.path),"undo owns original reference");s.undoLocalDeletion(CO,CV,m.id);check(s.message(CO,CV,m.id).text.equals(txt),"native-codec delete undo preserves exact text");check(Arrays.equals(Files.readAllBytes(f.toPath()),bytes),"original bytes unchanged");
  ChatStore.PendingShare p=s.stagePendingShare("caption",Arrays.asList(a));s.updatePendingSharePreview(p.id,"",NONE);s=new ChatStore(root);check(s.pendingShare().previewEdited&&s.pendingShare().text.isEmpty()&&s.pendingShare().attachments.isEmpty(),"empty reviewed share is durable");
  s.cancelPendingShare(p.id);s=new ChatStore(root);check(s.isPendingShareResolved(p.id)&&s.pendingShare()==null,"canceled share terminal marker survives");check(s.draft(CO,CV).text.equals("new"),"share edits preserve private draft");
  p=s.stagePendingShare("reviewed",Arrays.asList(a));String share=p.id;ChatStore.Message sent=s.sendPendingShare(share,CO,CV,null,null,UUID.randomUUID().toString());s=new ChatStore(root);check(s.isPendingShareResolved(share)&&s.message(CO,CV,sent.id).sourceShareId.equals(share),"sent share terminal marker durable");
  List<String> expected=new ArrayList<String>(),actual=new ArrayList<String>();for(ChatStore.Message x:s.searchMessages(CO,CV,"التصميم"))expected.add(x.id);String cursor=null;do{ChatStore.SearchPage page=s.searchMessagePage(CO,CV,"التصميم",cursor,7);for(ChatStore.Message x:page.messages)actual.add(x.id);cursor=page.hasMore?page.nextAfterId:null;}while(cursor!=null);check(expected.equals(actual),"bounded search traverses all matches");
  ChatStore.SearchPage last=s.searchMessagePageBefore(CO,CV,"التصميم",null,7);check(last.messages.get(0).id.equals(expected.get(expected.size()-last.messages.size())),"backward search window chronological");check(s.searchMessagePage(CO,CV,"",null,5).messages.isEmpty(),"empty query avoids all-history result allocation");
  StringWriter out=new StringWriter();s.writeConversationTranscript(CO,CV,out);check(out.toString().equals(s.conversationTranscript(CO,CV)),"streamed transcript equivalent to original public export");
  ChatStore.StorageStats stats=s.storageStats();check(stats.journalBytes>0&&stats.attachmentBytes==bytes.length&&stats.totalPrivateBytes==stats.metadataBytes+stats.attachmentBytes,"storage reporting actual file lengths");
  check(ChatStore.inspectRecovery(root).available,"prior save is explicitly inspectable");String old=s.draft(CO,CV).text;s.setDraft(CO,CV,"latest",NONE,null);ChatStore.restoreLastGood(root);s=s.reopen();check(s.draft(CO,CV).text.equals(old),"explicit last-good restore selects prior save");check(Arrays.equals(Files.readAllBytes(f.toPath()),bytes),"recovery preserves originals");
 }
 static void scale(File dir)throws Exception {
  dir.mkdir();ChatStore s=new ChatStore(new File(dir,"state.bin"));StringBuilder b=new StringBuilder();for(int i=0;i<19990;i++)b.append('س');String body=b.toString();
  for(int i=0;i<900;i++)s.sendDraftSnapshot(CO,CV,body+String.format(Locale.ROOT,"%06d",i),NONE,null,UUID.randomUUID().toString());
  ChatStore.StorageStats stats=s.storageStats();check(stats.journalBytes>32L*1024*1024,"ordinary journal exceeds former32MiB ceiling: "+stats.journalBytes);
  String id=s.lastMessage(CO,CV).id;s.setDraft(CO,CV,"still writable",NONE,id);s.deleteMessageLocally(CO,CV,id);s=s.reopen();check(s.draft(CO,CV).text.equals("still writable")&&s.message(CO,CV,id).deleted,"draft/delete/reopen beyond former cap");s.undoLocalDeletion(CO,CV,id);check(s.message(CO,CV,id).text.startsWith(body),"undo beyond former cap retains full text");
 }
 static String hash(byte[]b)throws Exception {StringBuilder s=new StringBuilder();for(byte x:java.security.MessageDigest.getInstance("SHA-256").digest(b))s.append(String.format(Locale.ROOT,"%02x",x&255));return s.toString();}
 static void remove(File f)throws IOException{if(f.isDirectory()){File[]c=f.listFiles();if(c!=null)for(File x:c)remove(x);}Files.deleteIfExists(f.toPath());}
}
