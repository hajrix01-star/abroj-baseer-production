package com.baseer.freshchat;

import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import static com.baseer.freshchat.BChatTimelineRows.*;

/** Actual pure production components. No Android/JSON/canonical-auth/SQLite/rendering substitute is claimed. */
public final class TimelineRowsTest {
    private static int checks;
    private static void check(boolean ok,String label){++checks;if(!ok)throw new AssertionError(label);}
    private static void rejected(Runnable action,String label){
        try{action.run();}catch(IllegalArgumentException|UnsupportedOperationException expected){++checks;return;}
        throw new AssertionError("Expected rejection: "+label);
    }
    private static Scope scope(){return new Scope("account-key",7,1,1001,2,3);}
    private static Rights rights(){return new Rights(1,true,true,true,true,true,true);}
    private static Context context(){return new Context("ar","light",16,1,1,320,true,false,rights(),"Asia/Riyadh","2026-291",true);}
    private static String uuid(int value){return String.format(java.util.Locale.ROOT,"00000000-0000-4000-8000-%012d",value);}
    private static Media media(){return new Media(30,MediaKind.IMAGE,"image/jpeg","photo.jpg",String.join("",Collections.nCopies(64,"a")),DocumentType.OTHER,true,4096);}
    private static Server server(long id){return new Server(id,2,"Peer","body "+id,"2026-10-18 08:00:00",null,null,Delivery.SENT,null);}
    private static Local local(int id){return new Local(id,uuid(id),"local "+id,LocalState.QUEUED,0,0,0);}
    private static Snapshot snapshot(List<Server> servers,List<Local> locals){return project(scope(),context(),servers,locals);}
    private static Snapshot one(Server server){return snapshot(Collections.singletonList(server),Collections.emptyList());}
    private static BChatTimelineChangePlan.Plan plan(Snapshot old,Snapshot next){return BChatTimelineChangePlan.between(old,next);}
    private static void applied(Snapshot old,Snapshot next,BChatTimelineChangePlan.Plan plan){
        if(plan.fallback!=BChatTimelineChangePlan.Fallback.NONE)return;
        List<Key> keys=new ArrayList<>();for(Row row:old.rows)keys.add(row.key);
        int previous=Integer.MAX_VALUE;for(int position:plan.removeOldDescending){check(position<previous,"remove descending");keys.remove(position);previous=position;}
        previous=-1;for(int position:plan.insertNewAscending){check(position>previous,"insert ascending");keys.add(position,next.rows.get(position).key);previous=position;}
        check(keys.size()==next.rows.size(),"count after apply matches next snapshot");
        for(int index=0;index<keys.size();++index)check(keys.get(index).equals(next.rows.get(index).key),"exact key at every resulting position");
        previous=-1;for(int position:plan.changeNewPositions){check(position>previous&&position<keys.size(),"change new ascending positions");previous=position;}
    }
    private static Server serverWith(Server s,int index,Object replacement){
        Object[] a={s.id,s.authorId,s.authorName,s.body,s.createdAt,s.reply,s.media,s.delivery,s.readAt};a[index]=replacement;
        return new Server((Long)a[0],(Long)a[1],(String)a[2],(String)a[3],(String)a[4],(Reply)a[5],(Media)a[6],(Delivery)a[7],(String)a[8]);
    }
    private static Media mediaWith(Media m,int index,Object replacement){
        Object[] a={m.id,m.kind,m.mime,m.name,m.sha256,m.documentType,m.thumbnailAvailable,m.size};a[index]=replacement;
        return new Media((Long)a[0],(MediaKind)a[1],(String)a[2],(String)a[3],(String)a[4],(DocumentType)a[5],(Boolean)a[6],(Integer)a[7]);
    }
    private static Local localWith(Local l,int index,Object replacement){
        Object[] a={l.sqliteId,l.uuid,l.body,l.state,l.replyToMessageId,l.reviewCode,l.receiptMessageId};a[index]=replacement;
        return new Local((Long)a[0],(String)a[1],(String)a[2],(LocalState)a[3],(Long)a[4],(Integer)a[5],(Long)a[6]);
    }
    private static Context contextWith(Context c,int index,Object replacement){
        Object[] a={c.locale,c.theme,c.bodySp,c.fontScale,c.density,c.widthPx,c.rtl,c.offline,c.rights,c.timeZone,c.dayKey,c.hour24};a[index]=replacement;
        return new Context((String)a[0],(String)a[1],(Float)a[2],(Float)a[3],(Float)a[4],(Integer)a[5],(Boolean)a[6],(Boolean)a[7],(Rights)a[8],(String)a[9],(String)a[10],(Boolean)a[11]);
    }
    private static Rights rightsWith(Rights r,int index,Object replacement){
        Object[] a={r.revision,r.chatView,r.chatSend,r.mediaView,r.mediaDownload,r.deliverySupported,r.receiptsAvailable};a[index]=replacement;
        return new Rights((Long)a[0],(Boolean)a[1],(Boolean)a[2],(Boolean)a[3],(Boolean)a[4],(Boolean)a[5],(Boolean)a[6]);
    }
    private static void unchangedAndNeighbors(){
        List<Server> list=new ArrayList<>();for(int i=1;i<=500;++i)list.add(server(i));
        Snapshot first=snapshot(list,Collections.emptyList()),same=snapshot(new ArrayList<>(list),Collections.emptyList());
        BChatTimelineChangePlan.Plan noChange=plan(first,same);check(noChange.isNoop(),"500 unchanged: no notification plan");applied(first,same,noChange);
        check(first.rows.get(0).neighbor.previous==null,"first row owns date boundary");
        for(int i=1;i<500;++i)check(first.rows.get(i).neighbor.previous.id==i,"server prefix has exact predecessor");
        List<Server> text=new ArrayList<>(list);text.set(250,serverWith(text.get(250),3,"changed"));
        check(plan(first,snapshot(text,Collections.emptyList())).changeNewPositions.equals(Collections.singletonList(250)),"body change does not rebind next sender header");
        for(int field:new int[]{1,4}){
            List<Server> changed=new ArrayList<>(list);changed.set(250,serverWith(changed.get(250),field,field==1?Long.valueOf(3):"2026-10-18 08:05:01"));
            check(plan(first,snapshot(changed,Collections.emptyList())).changeNewPositions.equals(Arrays.asList(250,251)),"author/time including5min boundary invalidates current+next grouping");
        }
        List<Server> previous=new ArrayList<>();for(int i=31;i<=530;++i)previous.add(server(i));
        List<Server> prepended=new ArrayList<>();for(int i=1;i<=500;++i)prepended.add(server(i));
        Snapshot before=snapshot(previous,Collections.emptyList()),after=snapshot(prepended,Collections.emptyList());
        BChatTimelineChangePlan.Plan prepend=plan(before,after);check(prepend.removeOldDescending.size()==30&&prepend.insertNewAscending.size()==30,"prepend+trim bounded30/30");
        check(prepend.changeNewPositions.equals(Collections.singletonList(30)),"previous first row header changes after prepend");applied(before,after,prepend);
        BChatTimelineChangePlan.Plan forward=plan(after,before);check(forward.changeNewPositions.equals(Collections.singletonList(0)),"new first header changes after forward trim");applied(after,before,forward);
    }
    private static void allKnownFields(){
        Server base=new Server(10,2,"Peer","body","2026-10-18 08:00:00",Reply.available(1,"Quoted","quote",null),media(),Delivery.SENT,null);
        Object[] values={11L,3L,"Other","edit","2026-10-19 00:00:00",Reply.unavailable(),mediaWith(media(),3,"another.jpg"),Delivery.DELIVERED,"2026-10-18 09:00:00"};
        for(int field=0;field<values.length;++field){Snapshot old=one(base),next=one(serverWith(base,field,values[field]));check(!plan(old,next).isNoop(),"server field delta "+field);applied(old,next,plan(old,next));}
        check(!plan(one(base),one(serverWith(base,8,""))).isNoop(),"empty readAt is not absent readAt");
        check(!plan(one(serverWith(base,7,null)),one(base)).isNoop(),"absent delivery not invented sent");
        check("Aa".hashCode()=="BB".hashCode()&&!plan(one(serverWith(base,3,"Aa")),one(serverWith(base,3,"BB"))).isNoop(),"colliding body hash cannot hide actual content change");
        Media media=media();Object[] mediaValues={31L,MediaKind.FILE,"image/png","different.jpg",String.join("",Collections.nCopies(64,"b")),DocumentType.INVOICE,false,8192};
        for(int field=0;field<mediaValues.length;++field)check(!plan(one(base),one(serverWith(base,6,mediaWith(media,field,mediaValues[field])))).isNoop(),"media exact field "+field);
        Reply[] replies={null,Reply.unavailable(),Reply.available(2,"Quoted","quote",null),Reply.available(1,"Other","quote",null),Reply.available(1,"Quoted","changed",null),Reply.available(1,"Quoted","quote",MediaKind.AUDIO)};
        for(Reply reply:replies)check(!plan(one(base),one(serverWith(base,5,reply))).isNoop(),"reply known field/unavailable/optional kind");
        Context c=context();Object[] contextValues={"en","dark",18f,2f,2f,640,false,true,new Rights(2,true,true,true,true,true,true),"UTC","2026-292",false};
        for(int field=0;field<contextValues.length;++field){Snapshot old=one(base),next=project(scope(),contextWith(c,field,contextValues[field]),Arrays.asList(base),Collections.emptyList());check(plan(old,next).changeNewPositions.equals(Arrays.asList(0)),"context exact field "+field);}
        for(int field=0;field<7;++field){Rights r=rightsWith(rights(),field,field==0?Long.valueOf(2):Boolean.FALSE);Snapshot next=project(scope(),contextWith(c,8,r),Arrays.asList(base),Collections.emptyList());check(plan(one(base),next).changeNewPositions.equals(Arrays.asList(0)),"rights exact field "+field);}
        Local l=local(1);Object[] localValues={2L,uuid(2),"edited",LocalState.REVIEW,1L,2,10L};
        for(int field=2;field<localValues.length;++field){Snapshot old=snapshot(Collections.emptyList(),Arrays.asList(l)),next=snapshot(Collections.emptyList(),Arrays.asList(localWith(l,field,localValues[field])));check(plan(old,next).changeNewPositions.equals(Arrays.asList(0)),"local known field "+field);}
        for(LocalState state:LocalState.values()){
            Snapshot old=snapshot(Collections.emptyList(),Arrays.asList(local(1))),next=snapshot(Collections.emptyList(),Arrays.asList(localWith(l,3,state)));
            check(plan(old,next).isNoop()==(state==LocalState.QUEUED),"every existing local state exact");
        }
    }
    private static void localAndTransitions(){
        Snapshot empty=snapshot(Collections.emptyList(),Collections.emptyList());
        check(empty.rows.size()==1&&empty.rows.get(0).key.stableId()==Long.MIN_VALUE,"unique empty placeholder stableID");
        Snapshot local=snapshot(Collections.emptyList(),Arrays.asList(local(1))),canonical=one(server(1));
        BChatTimelineChangePlan.Plan insert=plan(empty,local);check(insert.removeOldDescending.equals(Arrays.asList(0))&&insert.insertNewAscending.equals(Arrays.asList(0)),"empty replaced by one local, not two rows");applied(empty,local,insert);
        applied(local,empty,plan(local,empty));applied(empty,canonical,plan(empty,canonical));applied(canonical,empty,plan(canonical,empty));
        check(local.rows.get(0).key.stableId()==-1&&canonical.rows.get(0).key.stableId()==1,"server/local signed stableIDs not UUID hash");
        Local source=local(1);Server sameBody=serverWith(server(1),3,source.body);Snapshot next=one(sameBody);
        BChatTimelineChangePlan.Plan generic=plan(local,next);check(generic.acknowledged.isEmpty(),"same body does not imply ACK/UUID correspondence");applied(local,next,generic);
        BChatTimelineChangePlan.AckTransition marker=new BChatTimelineChangePlan.AckTransition(scope(),1,uuid(1),1);
        List<BChatTimelineChangePlan.AckTransition> marks=new ArrayList<>(Arrays.asList(marker));
        BChatTimelineChangePlan.Plan explicit=BChatTimelineChangePlan.between(local,next,marks);marks.clear();
        check(explicit.acknowledged.size()==1&&explicit.acknowledged.get(0)==marker,"only explicit matching ACK marker retained immutably");applied(local,next,explicit);
        Local hint=localWith(localWith(source,3,LocalState.RECEIPT),6,1L);
        check(plan(snapshot(Arrays.asList(sameBody),Arrays.asList(hint)),next).acknowledged.isEmpty(),"receipt-state/positive messageId hint is not ACK proof");
        Snapshot both=snapshot(Arrays.asList(sameBody),Arrays.asList(source));check(both.rows.size()==2,"projection never deduplicates pending storage by body/media");
        rejected(()->BChatTimelineChangePlan.between(local,both,Arrays.asList(marker)),"ACK cannot retain old pending row");
        rejected(()->BChatTimelineChangePlan.between(local,empty,Arrays.asList(marker)),"ACK canonical target absent");
        rejected(()->BChatTimelineChangePlan.between(local,next,Arrays.asList(new BChatTimelineChangePlan.AckTransition(scope(),1,uuid(2),1))),"wrong UUID ACK");
        rejected(()->BChatTimelineChangePlan.between(local,next,Arrays.asList(marker,marker)),"duplicate ACK mark");
        Snapshot differentScope=project(new Scope("account-key",7,1,1002,2,3),context(),Arrays.asList(sameBody),Collections.emptyList());
        rejected(()->BChatTimelineChangePlan.between(local,differentScope,Arrays.asList(marker)),"ACK cannot cross recipient epoch/scope");
        rejected(()->BChatTimelineChangePlan.between(local,next,Collections.nCopies(21,marker)),"ACK marker list bounded20");
        rejected(()->plan(local,snapshot(Collections.emptyList(),Arrays.asList(localWith(source,1,uuid(2))))),"SQLite id cannot acquire another UUID");
        rejected(()->plan(local,snapshot(Collections.emptyList(),Arrays.asList(localWith(source,0,2L)))),"UUID cannot acquire another SQLite id");
        Snapshot old=snapshot(Arrays.asList(server(1)),Arrays.asList(local(1),local(2))),reordered=snapshot(Arrays.asList(server(1)),Arrays.asList(local(2),local(1)));
        check(plan(old,reordered).fallback==BChatTimelineChangePlan.Fallback.REORDER,"reorder explicit safe full-reset fallback");
    }
    private static void scopesAndImmutability()throws Exception{
        Scope base=scope();Scope[] different={new Scope("other",7,1,1001,2,3),new Scope("account-key",8,1,1001,2,3),new Scope("account-key",7,2,1001,2,3),
            new Scope("account-key",7,1,1002,2,3),new Scope("account-key",7,1,1001,3,3),new Scope("account-key",7,1,1001,2,4)};
        Snapshot original=one(server(1));for(Scope other:different){Snapshot next=project(other,context(),Arrays.asList(server(1)),Collections.emptyList());
            BChatTimelineChangePlan.Plan p=plan(original,next);check(p.fallback==BChatTimelineChangePlan.Fallback.SCOPE_TRANSITION&&p.removeOldDescending.isEmpty()&&p.insertNewAscending.isEmpty(),"scope transition has no granular old-owner operations");
            check(!original.rows.get(0).key.equals(next.rows.get(0).key),"scope identity never borrows same numerical ID");}
        List<Server> servers=new ArrayList<>(Arrays.asList(server(1)));List<Local> locals=new ArrayList<>(Arrays.asList(local(1)));
        Snapshot copied=snapshot(servers,locals);servers.clear();locals.clear();check(copied.rows.size()==2&&copied.serverCount==1&&copied.localCount==1,"mutable input list cannot alter snapshot");
        rejected(()->copied.rows.clear(),"snapshot list immutable");
        BChatTimelineChangePlan.Plan change=plan(snapshot(Collections.emptyList(),Collections.emptyList()),copied);
        rejected(()->change.removeOldDescending.clear(),"remove list immutable");rejected(()->change.insertNewAscending.clear(),"insert list immutable");
        rejected(()->change.changeNewPositions.add(0),"change list immutable");rejected(()->change.acknowledged.clear(),"ACK list immutable");
        for(Class<?> type:BChatTimelineRows.class.getDeclaredClasses())for(Field field:type.getDeclaredFields())if(!Modifier.isStatic(field.getModifiers()))
            check(Modifier.isFinal(field.getModifiers()),"all presentation value fields final: "+type.getSimpleName()+"."+field.getName());
        for(Class<?> type:BChatTimelineChangePlan.class.getDeclaredClasses())for(Field field:type.getDeclaredFields())if(!Modifier.isStatic(field.getModifiers()))
            check(Modifier.isFinal(field.getModifiers()),"all plan fields final");
        Local upper=new Local(1,uuid(1).toUpperCase(java.util.Locale.ROOT)," exact body ",LocalState.QUEUED,0,0,0);
        check(upper.uuid.equals(uuid(1))&&upper.body.equals(" exact body "),"UUID canonicalized but body bytes not normalized");
        check(!new Scope("Aa",7,1,1001,2,3).equals(new Scope("BB",7,1,1001,2,3)),"String hash collision not identity equality");
    }
    private static void invalidInputs(){
        rejected(()->new Scope("",7,1,1,0,0),"empty account");rejected(()->new Scope("a",0,1,1,0,0),"zero user");
        rejected(()->new Scope("a",7,0,1,0,0),"zero room");rejected(()->new Scope("a",7,1,0,0,0),"zero membership");
        rejected(()->new Scope("a",7,1,1,-1,0),"negative session");rejected(()->new Scope("a",7,1,1,0,-1),"negative owner");
        rejected(()->server(0),"zero server ID");rejected(()->server(2147483648L),"server ID overflow");
        rejected(()->new Server(1,2,"Peer","x","date",Reply.available(1,"p","x",null),null,null,null),"reply parent must precede server message");
        rejected(()->new Server(1,2,"Peer","","date",null,null,null,null),"empty server must have attachment");
        rejected(()->new Local(0,uuid(1),"x",LocalState.QUEUED,0,0,0),"zero SQLite ID");
        rejected(()->new Local(Long.MIN_VALUE,uuid(1),"x",LocalState.QUEUED,0,0,0),"SQLite cannot collide with EMPTY");
        rejected(()->new Local(1,"1-1-1-1-1","x",LocalState.QUEUED,0,0,0),"abbreviated UUID");
        rejected(()->new Local(1,"00000000-0000-1000-8000-000000000001","x",LocalState.QUEUED,0,0,0),"nonv4 UUID");
        rejected(()->new Local(1,"00000000-0000-4000-0000-000000000001","x",LocalState.QUEUED,0,0,0),"UUID nonRFCvariant");
        rejected(()->new Local(1,uuid(1)," ",LocalState.QUEUED,0,0,0),"empty local body");
        rejected(()->new Local(1,uuid(1),"x",null,0,0,0),"unknown local state");
        rejected(()->snapshot(Arrays.asList(server(1),server(1)),Collections.emptyList()),"duplicate server id");
        rejected(()->snapshot(Arrays.asList(server(2),server(1)),Collections.emptyList()),"canonical server order not sorted by presentation");
        rejected(()->snapshot(Collections.emptyList(),Arrays.asList(local(1),localWith(local(2),0,1L))),"duplicate local SQLite id");
        rejected(()->snapshot(Collections.emptyList(),Arrays.asList(local(1),localWith(local(2),1,uuid(1)))),"duplicate local UUID");
        rejected(()->snapshot(Arrays.asList((Server)null),Collections.emptyList()),"null server");
        rejected(()->snapshot(Collections.emptyList(),Arrays.asList((Local)null)),"null local");
        List<Server> servers=new ArrayList<>();for(int i=1;i<=501;++i)servers.add(server(i));rejected(()->snapshot(servers,Collections.emptyList()),"server cap501 refused");
        List<Local> locals=new ArrayList<>();for(int i=1;i<=21;++i)locals.add(local(i));rejected(()->snapshot(Collections.emptyList(),locals),"local cap21 refused");
        Snapshot bound=snapshot(servers.subList(0,500),locals.subList(0,20));check(bound.rows.size()==520,"existing500+20 caps admitted without changing limits");
        rejected(()->contextWith(context(),2,Float.NaN),"NaN body size");rejected(()->contextWith(context(),3,Float.POSITIVE_INFINITY),"infinite scale");
        rejected(()->contextWith(context(),5,0),"nonpositive width");rejected(()->contextWith(context(),9,""),"missing timezone");
        rejected(()->BChatTimelineChangePlan.between(null,one(server(1))),"missing old snapshot");
    }
    public static void main(String[] args)throws Exception {
        unchangedAndNeighbors();allKnownFields();localAndTransitions();scopesAndImmutability();invalidInputs();
        System.out.println("PASS "+checks+" pure timeline row/plan checks; no Activity, Android, JSON, auth, SQLite, or performance acceptance");
    }
}
