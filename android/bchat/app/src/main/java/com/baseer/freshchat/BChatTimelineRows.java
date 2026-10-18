package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/**
 * Presentation values only. Inputs come from existing validated canonical reads/durable outbox.
 * This is NOT a wire validator, an authorization proof, a receipt, or permission to retire an outbox row.
 * No JSON serialization, date formatting/parsing, bitmap, mutable Room, or platform reference is retained.
 */
final class BChatTimelineRows {
    static final int MAX_SERVER=500, MAX_LOCAL=20;
    static final long MAX_SERVER_ID=2147483647L, EMPTY_STABLE_ID=Long.MIN_VALUE;
    enum Kind { SERVER, LOCAL, EMPTY }
    enum Delivery { SENT, DELIVERED, READ }
    enum LocalState { QUEUED, SENDING, UNCERTAIN, REVIEW, RECEIPT }
    enum MediaKind { IMAGE, AUDIO, FILE }
    enum DocumentType { OTHER, INVOICE, PAYMENT_RECEIPT }

    static final class Scope {
        final String account;
        final long userId,roomId,membershipId,session,renderOwner;
        Scope(String account,long userId,long roomId,long membershipId,long session,long renderOwner) {
            this.account=text(account,1024,false);
            require(serverId(userId)&&serverId(roomId)&&serverId(membershipId)&&session>=0&&renderOwner>=0);
            this.userId=userId;this.roomId=roomId;this.membershipId=membershipId;
            this.session=session;this.renderOwner=renderOwner;
        }
        @Override public boolean equals(Object other) {
            if(!(other instanceof Scope))return false;Scope s=(Scope)other;
            return account.equals(s.account)&&userId==s.userId&&roomId==s.roomId
                &&membershipId==s.membershipId&&session==s.session&&renderOwner==s.renderOwner;
        }
        @Override public int hashCode(){
            int h=account.hashCode();h=31*h+Long.hashCode(userId);h=31*h+Long.hashCode(roomId);
            h=31*h+Long.hashCode(membershipId);h=31*h+Long.hashCode(session);return 31*h+Long.hashCode(renderOwner);
        }
    }

    /** Accepted display capabilities are invalidation inputs, never action authorization. */
    static final class Rights {
        final long revision;
        final boolean chatView,chatSend,mediaView,mediaDownload,deliverySupported,receiptsAvailable;
        Rights(long revision,boolean chatView,boolean chatSend,boolean mediaView,boolean mediaDownload,
                boolean deliverySupported,boolean receiptsAvailable) {
            require(revision>=0);this.revision=revision;this.chatView=chatView;this.chatSend=chatSend;
            this.mediaView=mediaView;this.mediaDownload=mediaDownload;
            this.deliverySupported=deliverySupported;this.receiptsAvailable=receiptsAvailable;
        }
        boolean same(Rights r) {
            return r!=null&&revision==r.revision&&chatView==r.chatView&&chatSend==r.chatSend
                &&mediaView==r.mediaView&&mediaDownload==r.mediaDownload
                &&deliverySupported==r.deliverySupported&&receiptsAvailable==r.receiptsAvailable;
        }
    }

    static final class Context {
        final String locale,theme,timeZone,dayKey;
        final float bodySp,fontScale,density;
        final int widthPx;
        final boolean rtl,offline,hour24;
        final Rights rights;
        Context(String locale,String theme,float bodySp,float fontScale,float density,int widthPx,
                boolean rtl,boolean offline,Rights rights,String timeZone,String dayKey,boolean hour24) {
            this.locale=text(locale,128,false);this.theme=text(theme,128,false);
            this.timeZone=text(timeZone,128,false);this.dayKey=text(dayKey,64,false);
            require(Float.isFinite(bodySp)&&bodySp>0&&Float.isFinite(fontScale)&&fontScale>0
                &&Float.isFinite(density)&&density>0&&widthPx>0&&rights!=null);
            this.bodySp=bodySp;this.fontScale=fontScale;this.density=density;this.widthPx=widthPx;
            this.rtl=rtl;this.offline=offline;this.rights=rights;this.hour24=hour24;
        }
        boolean same(Context c) {
            return c!=null&&locale.equals(c.locale)&&theme.equals(c.theme)&&timeZone.equals(c.timeZone)
                &&dayKey.equals(c.dayKey)&&Float.compare(bodySp,c.bodySp)==0&&Float.compare(fontScale,c.fontScale)==0
                &&Float.compare(density,c.density)==0&&widthPx==c.widthPx&&rtl==c.rtl&&offline==c.offline
                &&hour24==c.hour24&&rights.same(c.rights);
        }
    }

    /** Exactly the eight current MediaRecord fields; full MIME/size policy remains at the canonical boundary. */
    static final class Media {
        final long id;
        final MediaKind kind;
        final String mime,name,sha256;
        final DocumentType documentType;
        final boolean thumbnailAvailable;
        final int size;
        Media(long id,MediaKind kind,String mime,String name,String sha256,DocumentType documentType,
                boolean thumbnailAvailable,int size) {
            require(serverId(id)&&kind!=null&&documentType!=null&&size>0
                &&sha256!=null&&sha256.matches("[0-9a-f]{64}"));
            this.id=id;this.kind=kind;this.mime=text(mime,128,false);this.name=text(name,160,false);
            this.sha256=sha256;this.documentType=documentType;this.thumbnailAvailable=thumbnailAvailable;this.size=size;
        }
        boolean same(Media m) {
            return m!=null&&id==m.id&&kind==m.kind&&mime.equals(m.mime)&&name.equals(m.name)&&sha256.equals(m.sha256)
                &&documentType==m.documentType&&thumbnailAvailable==m.thumbnailAvailable&&size==m.size;
        }
    }

    static final class Reply {
        final boolean unavailable;
        final long id;
        final String authorName,body;
        final MediaKind mediaKind; // null preserves the known optional null/absent preview.
        private Reply(boolean unavailable,long id,String authorName,String body,MediaKind mediaKind) {
            this.unavailable=unavailable;this.id=id;this.authorName=authorName;this.body=body;this.mediaKind=mediaKind;
        }
        static Reply unavailable(){return new Reply(true,0,"","",null);}
        static Reply available(long id,String authorName,String body,MediaKind mediaKind) {
            require(serverId(id));return new Reply(false,id,text(authorName,160,false),text(body,160,true),mediaKind);
        }
        boolean same(Reply r) {
            return r!=null&&unavailable==r.unavailable&&id==r.id&&authorName.equals(r.authorName)
                &&body.equals(r.body)&&mediaKind==r.mediaKind;
        }
    }

    static final class Server {
        final long id,authorId;
        final String authorName,body,createdAt,readAt;
        final Reply reply;
        final Media media;
        final Delivery delivery; // null means absent; do not invent sender receipts.
        Server(long id,long authorId,String authorName,String body,String createdAt,Reply reply,Media media,
                Delivery delivery,String readAt) {
            require(serverId(id)&&serverId(authorId)&&(reply==null||reply.unavailable||reply.id<id));
            this.id=id;this.authorId=authorId;this.authorName=text(authorName,160,false);
            this.body=text(body,16384,true);require(!body.isEmpty()||media!=null);
            this.createdAt=text(createdAt,64,false);this.reply=reply;this.media=media;this.delivery=delivery;
            this.readAt=readAt==null?null:text(readAt,64,true);
        }
        boolean same(Server s) {
            return s!=null&&id==s.id&&authorId==s.authorId&&authorName.equals(s.authorName)&&body.equals(s.body)
                &&createdAt.equals(s.createdAt)&&Objects.equals(readAt,s.readAt)&&delivery==s.delivery
                &&sameReply(reply,s.reply)&&sameMedia(media,s.media);
        }
    }

    static final class Local {
        final long sqliteId,replyToMessageId,receiptMessageId;
        final String uuid,body;
        final LocalState state;
        final int reviewCode;
        Local(long sqliteId,String uuid,String body,LocalState state,long replyToMessageId,int reviewCode,long receiptMessageId) {
            require(sqliteId>0&&state!=null&&reviewCode>=0&&optionalId(replyToMessageId)&&optionalId(receiptMessageId));
            this.sqliteId=sqliteId;this.uuid=uuid(uuid);this.body=text(body,16384,false);this.state=state;
            this.replyToMessageId=replyToMessageId;this.reviewCode=reviewCode;this.receiptMessageId=receiptMessageId;
        }
        boolean same(Local l) {
            return l!=null&&sqliteId==l.sqliteId&&uuid.equals(l.uuid)&&body.equals(l.body)&&state==l.state
                &&replyToMessageId==l.replyToMessageId&&reviewCode==l.reviewCode&&receiptMessageId==l.receiptMessageId;
        }
    }

    static final class Key {
        final Scope scope;
        final Kind kind;
        final long id;
        final String uuid;
        private Key(Scope scope,Kind kind,long id,String uuid) {this.scope=scope;this.kind=kind;this.id=id;this.uuid=uuid;}
        static Key server(Scope s,long id){require(s!=null&&serverId(id));return new Key(s,Kind.SERVER,id,null);}
        static Key local(Scope s,long id,String uuid){require(s!=null&&id>0);return new Key(s,Kind.LOCAL,id,uuid(uuid));}
        static Key empty(Scope s){require(s!=null);return new Key(s,Kind.EMPTY,0,null);}
        long stableId(){return kind==Kind.SERVER?id:kind==Kind.LOCAL?-id:EMPTY_STABLE_ID;}
        @Override public boolean equals(Object other) {
            if(!(other instanceof Key))return false;Key k=(Key)other;
            return scope.equals(k.scope)&&kind==k.kind&&id==k.id&&Objects.equals(uuid,k.uuid);
        }
        @Override public int hashCode(){return 31*(31*(31*scope.hashCode()+kind.hashCode())+Long.hashCode(id))+Objects.hashCode(uuid);}
    }

    /**
     * Structural dependency, not preformatted UI. Existing visible-row date/5-minute grouping code remains owner.
     * A changed previous author/stamp, or becoming first after trim, must rebind the current header/bubble.
     */
    static final class NeighborKey {
        final Key previous;
        final long previousAuthor,currentAuthor;
        final String previousStamp,currentStamp;
        NeighborKey(Scope scope,Server prior,Server current) {
            previous=prior==null?null:Key.server(scope,prior.id);previousAuthor=prior==null?0:prior.authorId;
            previousStamp=prior==null?null:prior.createdAt;currentAuthor=current.authorId;currentStamp=current.createdAt;
        }
        boolean same(NeighborKey n) {
            return n!=null&&Objects.equals(previous,n.previous)&&previousAuthor==n.previousAuthor&&currentAuthor==n.currentAuthor
                &&Objects.equals(previousStamp,n.previousStamp)&&currentStamp.equals(n.currentStamp);
        }
    }

    static final class Row {
        final Key key;
        final Server server;
        final Local local;
        final NeighborKey neighbor;
        final Context context;
        private Row(Key key,Server server,Local local,NeighborKey neighbor,Context context) {
            this.key=key;this.server=server;this.local=local;this.neighbor=neighbor;this.context=context;
        }
        /** Exact render-key equality, including action data and dependencies. Hashes never stand in for equality. */
        boolean sameRender(Row r) {
            return r!=null&&key.equals(r.key)&&context.same(r.context)
                &&(server==null?r.server==null:server.same(r.server))
                &&(local==null?r.local==null:local.same(r.local))
                &&(neighbor==null?r.neighbor==null:neighbor.same(r.neighbor));
        }
    }

    static final class Snapshot {
        final Scope scope;
        final Context context;
        final List<Row> rows;
        final int serverCount,localCount;
        private Snapshot(Scope scope,Context context,List<Row> rows,int servers,int locals) {
            this.scope=scope;this.context=context;this.rows=Collections.unmodifiableList(new ArrayList<>(rows));
            serverCount=servers;localCount=locals;
        }
    }

    static Snapshot project(Scope scope,Context context,List<Server> servers,List<Local> locals) {
        require(scope!=null&&context!=null&&servers!=null&&locals!=null&&servers.size()<=MAX_SERVER&&locals.size()<=MAX_LOCAL);
        List<Row> rows=new ArrayList<>(Math.max(1,servers.size()+locals.size()));long previousId=0;Server prior=null;
        for(Server server:servers) {
            require(server!=null&&server.id>previousId);previousId=server.id;
            rows.add(new Row(Key.server(scope,server.id),server,null,new NeighborKey(scope,prior,server),context));prior=server;
        }
        Set<Long> ids=new HashSet<>();Set<String> uuids=new HashSet<>();
        for(Local local:locals) {
            require(local!=null&&ids.add(local.sqliteId)&&uuids.add(local.uuid));
            rows.add(new Row(Key.local(scope,local.sqliteId,local.uuid),null,local,null,context));
        }
        if(rows.isEmpty())rows.add(new Row(Key.empty(scope),null,null,null,context));
        return new Snapshot(scope,context,rows,servers.size(),locals.size());
    }

    static boolean serverId(long id){return id>0&&id<=MAX_SERVER_ID;}
    private static boolean optionalId(long id){return id==0||serverId(id);}
    private static boolean sameReply(Reply a,Reply b){return a==null?b==null:a.same(b);}
    private static boolean sameMedia(Media a,Media b){return a==null?b==null:a.same(b);}
    private static String uuid(String value) {
        require(value!=null&&value.length()==36);UUID parsed;
        try{parsed=UUID.fromString(value);}catch(IllegalArgumentException invalid){throw new IllegalArgumentException("Invalid timeline UUID");}
        require(parsed.version()==4&&parsed.variant()==2&&parsed.toString().equals(value.toLowerCase(Locale.ROOT)));
        return parsed.toString();
    }
    private static String text(String value,int maximum,boolean empty) {
        require(value!=null&&value.length()<=maximum&&(empty||!value.trim().isEmpty())&&value.indexOf('\0')<0);
        return value; // Preserve accepted body/name/stamp bytes; no normalization or business calculations.
    }
    private static void require(boolean ok){if(!ok)throw new IllegalArgumentException("Invalid timeline presentation input");}
    private BChatTimelineRows(){ }
}
