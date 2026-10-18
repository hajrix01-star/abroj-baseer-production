package com.baseer.freshchat;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;
import java.util.concurrent.*;
/** Controllable synthetic SAF provider; no user files or network. */
public final class DraftTestMediaProvider extends ContentProvider{
    static File source;static volatile boolean mainIo;
    static CountDownLatch opened=new CountDownLatch(1),release=new CountDownLatch(1);
    @Override public boolean onCreate(){return true;}
    @Override public String getType(Uri ignored){return "image/jpeg";}
    @Override public Cursor query(Uri uri,String[] projection,String selection,String[] args,String sort){
        mainIo|=Looper.myLooper()==Looper.getMainLooper();
        MatrixCursor c=new MatrixCursor(new String[]{OpenableColumns.DISPLAY_NAME,OpenableColumns.SIZE});
        c.addRow(new Object[]{"synthetic.jpg",source.length()});return c;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri,String mode)throws FileNotFoundException{
        mainIo|=Looper.myLooper()==Looper.getMainLooper();opened.countDown();
        try{if(!release.await(5,TimeUnit.SECONDS))throw new FileNotFoundException("Synthetic provider timeout");}
        catch(InterruptedException error){Thread.currentThread().interrupt();throw new FileNotFoundException("Interrupted");}
        return ParcelFileDescriptor.open(source,ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Uri insert(Uri u,ContentValues v){throw new UnsupportedOperationException();}
    @Override public int update(Uri u,ContentValues v,String s,String[] a){throw new UnsupportedOperationException();}
    @Override public int delete(Uri u,String s,String[] a){throw new UnsupportedOperationException();}
}
