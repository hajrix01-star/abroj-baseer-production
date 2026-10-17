package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;

/** Presentation-only immutable projection. Never an entitlement or a retained mutable Room. */
final class BChatRoomRow {
    static final int MAX_ROOMS = 100;
    static final class Key {
        final String account;
        final long room, membership;
        Key(String account, long room, long membership) {
            if (account == null || account.isEmpty() || room <= 0 || membership <= 0)
                throw new IllegalArgumentException("Invalid room row identity");
            this.account=account; this.room=room; this.membership=membership;
        }
        @Override public boolean equals(Object other) {
            if (!(other instanceof Key)) return false;
            Key key=(Key)other;
            return room==key.room && membership==key.membership && account.equals(key.account);
        }
        @Override public int hashCode() { return Objects.hash(account,room,membership); }
    }
    final Key key;
    final long company;
    final String name, preview, time, companyName, taskLabel, renderKey;
    final int unread, avatarVersion;
    final boolean group, task;
    BChatRoomRow(Key key, long company, String name, String preview, String time,
            String companyName, String taskLabel, int unread, int avatarVersion,
            boolean group, boolean task, String renderKey) {
        if (key==null || company<=0 || name==null || preview==null || time==null
                || companyName==null || taskLabel==null || renderKey==null || unread<0 || avatarVersion<0)
            throw new IllegalArgumentException("Invalid room row");
        this.key=key; this.company=company; this.name=name; this.preview=preview; this.time=time;
        this.companyName=companyName; this.taskLabel=taskLabel; this.unread=unread;
        this.avatarVersion=avatarVersion; this.group=group; this.task=task; this.renderKey=renderKey;
    }
    boolean sameContent(BChatRoomRow row) {
        return key.equals(row.key) && company==row.company && unread==row.unread
            && avatarVersion==row.avatarVersion && group==row.group && task==row.task
            && name.equals(row.name) && preview.equals(row.preview) && time.equals(row.time)
            && companyName.equals(row.companyName) && taskLabel.equals(row.taskLabel) && renderKey.equals(row.renderKey);
    }
    static List<BChatRoomRow> filter(List<BChatRoomRow> source, String input) {
        if (source==null || source.size()>MAX_ROOMS) throw new IllegalArgumentException("Room row capacity");
        String query=input==null?"":input.trim().toLowerCase(Locale.ROOT);
        List<BChatRoomRow> result=new ArrayList<>(); Set<Key> keys=new HashSet<>();
        for (BChatRoomRow row:source) {
            if(row==null || !keys.add(row.key)) throw new IllegalArgumentException("Duplicate room row");
            // Preserve the existing order and exact name/company substring semantics.
            if(query.isEmpty() || row.name.toLowerCase(Locale.ROOT).contains(query)
                    || row.companyName.toLowerCase(Locale.ROOT).contains(query)) result.add(row);
        }
        return Collections.unmodifiableList(result);
    }
}
