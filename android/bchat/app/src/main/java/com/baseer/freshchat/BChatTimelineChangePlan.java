package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Pure bounded O(n) plan. Future owner must publish canonical/projection/notifications atomically on MAIN. */
final class BChatTimelineChangePlan {
    enum Fallback { NONE, SCOPE_TRANSITION, REORDER }

    /**
     * Caller-supplied UI correspondence ONLY, after the existing authenticated ACK and durable retirement.
     * A receiptMessageId hint, same body, or matching media is never manufactured into this marker here.
     * Creating a marker does not authenticate anything or mutate the canonical/outbox source of truth.
     */
    static final class AckTransition {
        final BChatTimelineRows.Key local,server;
        AckTransition(BChatTimelineRows.Scope scope,long sqliteId,String uuid,long serverMessageId) {
            local=BChatTimelineRows.Key.local(scope,sqliteId,uuid);
            server=BChatTimelineRows.Key.server(scope,serverMessageId);
        }
    }
    static final class Plan {
        final Fallback fallback;
        final List<Integer> removeOldDescending,insertNewAscending,changeNewPositions;
        final List<AckTransition> acknowledged;
        private Plan(Fallback fallback,List<Integer> removed,List<Integer> inserted,List<Integer> changed,List<AckTransition> acknowledged) {
            this.fallback=fallback;removeOldDescending=freeze(removed);insertNewAscending=freeze(inserted);changeNewPositions=freeze(changed);
            this.acknowledged=Collections.unmodifiableList(new ArrayList<>(acknowledged));
        }
        boolean isNoop(){return fallback==Fallback.NONE&&removeOldDescending.isEmpty()&&insertNewAscending.isEmpty()&&changeNewPositions.isEmpty();}
    }
    static Plan between(BChatTimelineRows.Snapshot old,BChatTimelineRows.Snapshot next) {
        return between(old,next,Collections.emptyList());
    }
    static Plan between(BChatTimelineRows.Snapshot old,BChatTimelineRows.Snapshot next,List<AckTransition> transitions) {
        if(old==null||next==null||transitions==null||transitions.size()>BChatTimelineRows.MAX_LOCAL)
            throw new IllegalArgumentException("Snapshots and bounded explicit transitions required");
        Map<BChatTimelineRows.Key,Integer> before=positions(old),after=positions(next);
        List<AckTransition> accepted=validateTransitions(old,next,before,after,transitions);
        if(!old.scope.equals(next.scope))return fallback(Fallback.SCOPE_TRANSITION,accepted);
        requireStableLocalIdentity(old,next);
        int prior=-1;
        for(BChatTimelineRows.Row row:next.rows) {
            Integer position=before.get(row.key);
            if(position!=null){if(position<=prior)return fallback(Fallback.REORDER,accepted);prior=position;}
        }
        List<Integer> removed=new ArrayList<>(),inserted=new ArrayList<>(),changed=new ArrayList<>();
        for(int position=old.rows.size()-1;position>=0;--position)if(!after.containsKey(old.rows.get(position).key))removed.add(position);
        for(int position=0;position<next.rows.size();++position) {
            BChatTimelineRows.Row row=next.rows.get(position);Integer previous=before.get(row.key);
            if(previous==null)inserted.add(position);
            else if(!old.rows.get(previous).sameRender(row))changed.add(position);
        }
        return new Plan(Fallback.NONE,removed,inserted,changed,accepted);
    }
    private static Map<BChatTimelineRows.Key,Integer> positions(BChatTimelineRows.Snapshot snapshot) {
        Map<BChatTimelineRows.Key,Integer> result=new HashMap<>();
        for(int i=0;i<snapshot.rows.size();++i)if(result.put(snapshot.rows.get(i).key,i)!=null)
            throw new IllegalArgumentException("Duplicate timeline key");
        return result; // HashMap uses exact scoped Key.equals, never hash-only identity.
    }
    private static void requireStableLocalIdentity(BChatTimelineRows.Snapshot old,BChatTimelineRows.Snapshot next) {
        Map<Long,String> ids=new HashMap<>();Map<String,Long> uuids=new HashMap<>();
        for(BChatTimelineRows.Row row:old.rows)if(row.local!=null){ids.put(row.local.sqliteId,row.local.uuid);uuids.put(row.local.uuid,row.local.sqliteId);}
        for(BChatTimelineRows.Row row:next.rows)if(row.local!=null) {
            String uuid=ids.get(row.local.sqliteId);Long id=uuids.get(row.local.uuid);
            if(uuid!=null&&!uuid.equals(row.local.uuid)||id!=null&&id.longValue()!=row.local.sqliteId)
                throw new IllegalArgumentException("Local SQLite ID/UUID correspondence changed within one owner");
        }
    }
    private static List<AckTransition> validateTransitions(BChatTimelineRows.Snapshot old,BChatTimelineRows.Snapshot next,
            Map<BChatTimelineRows.Key,Integer> before,Map<BChatTimelineRows.Key,Integer> after,List<AckTransition> marks) {
        List<AckTransition> accepted=new ArrayList<>();Set<BChatTimelineRows.Key> locals=new HashSet<>(),servers=new HashSet<>();
        for(AckTransition mark:marks) {
            if(mark==null||!old.scope.equals(next.scope)||!old.scope.equals(mark.local.scope)
                    ||!next.scope.equals(mark.server.scope)||!before.containsKey(mark.local)||after.containsKey(mark.local)
                    ||!after.containsKey(mark.server)||!locals.add(mark.local)||!servers.add(mark.server))
                throw new IllegalArgumentException("ACK correspondence does not match exact old local/new canonical rows");
            accepted.add(mark);
        }
        return accepted;
    }
    private static Plan fallback(Fallback reason,List<AckTransition> accepted) {
        return new Plan(reason,Collections.emptyList(),Collections.emptyList(),Collections.emptyList(),accepted);
    }
    private static List<Integer> freeze(List<Integer> source){return Collections.unmodifiableList(new ArrayList<>(source));}
    private BChatTimelineChangePlan(){ }
}
