package com.baseer.freshchat;
import java.io.*;
public final class BoundedTextWriterTest {
    public static void main(String[] args)throws Exception{
        BoundedTextWriter writer=new BoundedTextWriter(6);writer.append("ع🙂a");writer.write("bc");if(!writer.toString().equals("ع🙂abc"))throw new AssertionError("Unicode boundary");
        try{writer.append("x");throw new AssertionError("Overflow accepted");}catch(BoundedTextWriter.LimitExceeded expected){}
        if(!writer.toString().equals("ع🙂abc"))throw new AssertionError("Partial append");
        BoundedTextWriter large=new BoundedTextWriter(128*1024);for(int i=0;i<128;i++)large.write(new char[1024]);try{large.write(1);throw new AssertionError("Budget exceeded");}catch(BoundedTextWriter.LimitExceeded expected){}
        Thread.currentThread().interrupt();try{new BoundedTextWriter(3).write('x');throw new AssertionError("Cancellation ignored");}catch(IOException expected){}finally{Thread.interrupted();}
        System.out.println("PASS: Unicode/exact boundary, atomic overflow, 128Ki budget and cancellation");
    }
}
