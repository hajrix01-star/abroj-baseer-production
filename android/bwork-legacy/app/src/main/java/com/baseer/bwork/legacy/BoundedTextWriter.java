package com.baseer.bwork.legacy;
import java.io.IOException;
import java.io.Writer;
/** Clipboard preflight rejects over-limit output; it never silently truncates. */
final class BoundedTextWriter extends Writer {
    static final class LimitExceeded extends IOException { private static final long serialVersionUID=1L; LimitExceeded(){super("Conversation exceeds the clipboard size limit");} }
    private final int limit;private final StringBuilder text=new StringBuilder();
    BoundedTextWriter(int limit){if(limit<1)throw new IllegalArgumentException("Positive limit required");this.limit=limit;}
    @Override public void write(char[] value,int offset,int length)throws IOException{if(offset<0||length<0||offset>value.length-length)throw new IndexOutOfBoundsException();check(length);text.append(value,offset,length);}
    @Override public void write(String value,int offset,int length)throws IOException{if(offset<0||length<0||offset>value.length()-length)throw new IndexOutOfBoundsException();check(length);text.append(value,offset,offset+length);}
    @Override public void write(int value)throws IOException{check(1);text.append((char)value);}
    private void check(int count)throws IOException{if(Thread.currentThread().isInterrupted())throw new IOException("Transcript export canceled");if(count>limit-text.length())throw new LimitExceeded();}
    @Override public void flush(){} @Override public void close(){} @Override public String toString(){return text.toString();}
}
