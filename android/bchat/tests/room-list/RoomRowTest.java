package com.baseer.freshchat;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

public final class RoomRowTest {
    private static int checks;
    private static void check(boolean pass,String label) {++checks;if(!pass)throw new AssertionError(label);}
    private static BChatRoomRow row(String account,long id,long member,String name,String company,int unread,String render) {
        return new BChatRoomRow(new BChatRoomRow.Key(account,id,member),1,name,"preview","time",company,"tasks",unread,1,true,true,render);
    }
    public static void main(String[] args) {
        List<BChatRoomRow> rows=Arrays.asList(row("a",20,40,"  فريق ARZ","مطعم",0,"light"),
            row("a",2,50,"Room Beta","Branch",100,"light"),row("a",7,80,"Room alpha","",1,"light"));
        check(BChatRoomRow.filter(rows,"").equals(rows),"server order, not numeric/sort order");
        check(BChatRoomRow.filter(rows," ROOM ").equals(rows.subList(1,3)),"trim/ROOT-case name substring");
        check(BChatRoomRow.filter(rows,"مطعم").equals(rows.subList(0,1)),"Arabic company substring");
        check(BChatRoomRow.filter(rows,"bRaNcH").equals(rows.subList(1,2)),"company case-insensitive");
        check(BChatRoomRow.filter(rows,"no match").isEmpty(),"empty matches distinct from empty source");
        check(BChatRoomRow.filter(Collections.emptyList(),"").isEmpty(),"no rooms");
        try{BChatRoomRow.filter(rows,"").clear();throw new AssertionError();}catch(UnsupportedOperationException expected){++checks;}
        List<BChatRoomRow> hundred=new ArrayList<>();for(int i=1;i<=100;++i)hundred.add(row("a",i,i+100,"room"+i,"",i,"light"));
        check(BChatRoomRow.filter(hundred,"").size()==100,"exact100 boundary");
        hundred.add(row("a",101,201,"extra","",0,"light"));
        try{BChatRoomRow.filter(hundred,"");throw new AssertionError();}catch(IllegalArgumentException expected){++checks;}
        try{BChatRoomRow.filter(Arrays.asList(rows.get(0),rows.get(0)),"");throw new AssertionError();}catch(IllegalArgumentException expected){++checks;}
        BChatRoomRow original=rows.get(0);
        check(original.sameContent(row("a",20,40,"  فريق ARZ","مطعم",0,"light")),"equal immutable projection");
        check(!original.key.equals(row("b",20,40,original.name,"مطعم",0,"light").key),"account identity");
        check(!original.key.equals(row("a",20,41,original.name,"مطعم",0,"light").key),"rejoin identity");
        check(!original.sameContent(row("a",20,40,original.name,"مطعم",1,"light")),"unread is content");
        check(!original.sameContent(row("a",20,40,original.name,"مطعم",0,"dark")),"render context is content");
        check(!original.sameContent(row("a",20,40,"new name","مطعم",0,"light")),"rename is content");
        check(!original.sameContent(row("a",20,40,original.name,"other company",0,"light")),"company label is content");
        System.out.println("PASS "+checks+" actual immutable room projection checks; no Android/auth/network claim");
    }
}
