package com.baseer.freshchat;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.UUID;

/** A process-owned editor, independent of Views and the last durable store revision. */
final class EditorState {
    static final class Snapshot implements Serializable {
        private static final long serialVersionUID = 1L;
        final String company, conversation, shareId, text, replyId, sendToken, sendCompany, sendConversation, editorId;
        final ArrayList<ChatStore.Attachment> files;
        final long revision;
        Snapshot(String company, String conversation, String shareId, String text, List<ChatStore.Attachment> files,
                 String replyId, long revision, String sendToken, String sendCompany, String sendConversation) {
            this(company, conversation, shareId, text, files, replyId, revision, sendToken, sendCompany, sendConversation, UUID.randomUUID().toString());
        }
        Snapshot(String company, String conversation, String shareId, String text, List<ChatStore.Attachment> files,
                 String replyId, long revision, String sendToken, String sendCompany, String sendConversation, String editorId) {
            this.company=company; this.conversation=conversation; this.shareId=shareId; this.text=text;
            this.files=new ArrayList<>(files); this.replyId=replyId; this.revision=revision;
            this.sendToken=sendToken; this.sendCompany=sendCompany; this.sendConversation=sendConversation; this.editorId=editorId;
        }
    }
    private final String company, conversation, shareId;
    private String editorId=UUID.randomUUID().toString(), text, replyId, sendToken, sendCompany, sendConversation;
    private ArrayList<ChatStore.Attachment> files;
    private long revision=1, committedRevision=1;
    private Exception failure;
    private boolean retired;
    EditorState(String company,String conversation,String shareId,String text,List<ChatStore.Attachment> files,String replyId) {
        this.company=company;this.conversation=conversation;this.shareId=shareId;this.text=text;
        this.files=new ArrayList<>(files);this.replyId=replyId;
    }
    static EditorState recover(Snapshot saved) {
        EditorState state=new EditorState(saved.company,saved.conversation,saved.shareId,saved.text,saved.files,saved.replyId);
        if(saved.editorId!=null)state.editorId=saved.editorId;
        state.committedRevision=0; // Android saved state is not a durable-storage acknowledgement.
        state.sendToken=saved.sendToken;state.sendCompany=saved.sendCompany;state.sendConversation=saved.sendConversation;
        return state;
    }
    /** Candidate restoration seam: retain incoming membership and durable matching checksums. */
    static EditorState recover(Snapshot saved,List<ChatStore.Attachment> durableFiles) {
        EditorState state=recover(saved);
        state.files=IntegrityAttachments.preserve(durableFiles,state.files);
        return state;
    }
    synchronized Snapshot snapshot(){return new Snapshot(company,conversation,shareId,text,files,replyId,revision,sendToken,sendCompany,sendConversation,editorId);}
    synchronized boolean update(String value,List<ChatStore.Attachment> attachments,String reply) {
        if(retired || sendToken!=null)return false;
        ArrayList<ChatStore.Attachment> merged=IntegrityAttachments.preserve(files,attachments);
        if(text.equals(value) && Objects.equals(replyId,reply) && sameFiles(files,merged))return false;
        text=value;files=merged;replyId=reply;revision++;failure=null;return true;
    }
    synchronized boolean dirty(){return !retired && committedRevision<revision;}
    synchronized boolean sending(){return !retired && sendToken!=null;}
    synchronized boolean retired(){return retired;}
    synchronized Exception failure(){return failure;}
    synchronized boolean needsWrite(Snapshot value){return !retired && owns(value) && value.revision<=revision && value.revision>committedRevision;}
    synchronized void committed(Snapshot value){if(retired || !owns(value) || value.revision>revision)return;committedRevision=Math.max(committedRevision,value.revision);if(committedRevision>=revision)failure=null;}
    synchronized void failed(Snapshot value,Exception error){if(!retired && owns(value) && value.revision==revision && value.revision>committedRevision)failure=error;}
    synchronized void requireSave(){if(!retired){revision++;failure=null;}}
    synchronized Snapshot beginSend(String token,String co,String cv){
        if(retired)throw new IllegalStateException("Editor is no longer active");
        if(token==null || co==null || cv==null)throw new IllegalArgumentException("A send requires a token and destination");
        if(sendToken==null && shareId==null && (!Objects.equals(company,co)||!Objects.equals(conversation,cv)))throw new IllegalArgumentException("Draft destination does not match its editor");
        if(sendToken==null){sendToken=token;sendCompany=co;sendConversation=cv;}return snapshot();
    }
    synchronized void commitUncertain(Snapshot value, Exception error) {
        if (!retired && owns(value) && Objects.equals(sendToken, value.sendToken)) failure = error;
        // Keep the original token locked until a fresh store confirms its actual commit status.
    }
    synchronized void sendFailed(Snapshot value,Exception error){if(retired || sendToken==null || !owns(value) || !Objects.equals(sendToken,value.sendToken))return;sendToken=null;sendCompany=null;sendConversation=null;failure=error;revision++;}
    synchronized void sent(Snapshot value){if(retired || sendToken==null || !owns(value) || !Objects.equals(sendToken,value.sendToken))return;text="";files.clear();replyId=null;sendToken=null;sendCompany=null;sendConversation=null;revision++;committedRevision=revision;failure=null;if(shareId!=null)retired=true;}
    synchronized void cancelRecoveredSend(){sendToken=null;sendCompany=null;sendConversation=null;}
    synchronized void retire(){retired=true;sendToken=null;failure=null;}
    private boolean owns(Snapshot value){return value!=null && Objects.equals(editorId,value.editorId) && Objects.equals(company,value.company) && Objects.equals(conversation,value.conversation) && Objects.equals(shareId,value.shareId);}
    private static boolean sameFiles(List<ChatStore.Attachment> first,List<ChatStore.Attachment> second){return IntegrityAttachments.same(first,second);}
}
