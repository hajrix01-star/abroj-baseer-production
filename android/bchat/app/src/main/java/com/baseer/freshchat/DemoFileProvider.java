// Original Baseer offline demo. No network transport or real recipient data.
package com.baseer.freshchat;

import android.content.*;
import android.database.*;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/**
 * Narrow camera-output provider. It exposes only direct files in private attachments.
 */
public final class DemoFileProvider extends ContentProvider {

    public boolean onCreate() {
        return true;
    }

    private File file(Uri uri) throws FileNotFoundException {
        try {
            File root = new File(getContext().getFilesDir(), "attachments").getCanonicalFile();
            String name = uri.getLastPathSegment();
            if (name == null || !name.matches("[A-Za-z0-9._-]+")) throw new FileNotFoundException("Invalid attachment");
            File f = new File(root, name).getCanonicalFile();
            if (!root.equals(f.getParentFile())) throw new FileNotFoundException("Invalid path");
            return f;
        } catch (IOException e) {
            throw new FileNotFoundException(e.getMessage());
        }
    }

    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(file(uri), ParcelFileDescriptor.parseMode(mode));
    }

    public String getType(Uri uri) {
        String name = uri == null ? null : uri.getLastPathSegment();
        if (name != null && name.endsWith(".m4a")) return "audio/mp4";
        return "image/jpeg";
    }

    public Cursor query(Uri u, String[] p, String s, String[] a, String o) {
        try {
            File f = file(u);
            String[] cols = p == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : p;
            MatrixCursor c = new MatrixCursor(cols);
            Object[] v = new Object[cols.length];
            for (int i = 0; i < cols.length; i++) v[i] = OpenableColumns.DISPLAY_NAME.equals(cols[i]) ? f.getName() : OpenableColumns.SIZE.equals(cols[i]) ? f.length() : null;
            c.addRow(v);
            return c;
        } catch (IOException e) {
            return null;
        }
    }

    public Uri insert(Uri u, ContentValues v) {
        throw new UnsupportedOperationException();
    }

    public int update(Uri u, ContentValues v, String s, String[] a) {
        return 0;
    }

    public int delete(Uri u, String s, String[] a) {
        return 0;
    }
}
