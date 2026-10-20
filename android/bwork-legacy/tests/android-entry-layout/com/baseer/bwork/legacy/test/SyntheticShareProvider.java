package com.baseer.bwork.legacy.test;

import android.content.*;
import android.database.*;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.*;

/** Non-exported, temporary read grants only. Serves exclusively this test package's generated PNG. */
public final class SyntheticShareProvider extends ContentProvider {
    static File file(Context context, String token) {
        if (token == null || !token.matches("[a-f0-9-]{36}\\.png")) throw new IllegalArgumentException("Synthetic fixture token required");
        return new File(context.getFilesDir(), "entry-boundary-" + token);
    }
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { file(getContext(), uri.getLastPathSegment()); return "image/png"; }
    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
        File file = file(getContext(), uri.getLastPathSegment());
        String[] columns = projection == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        MatrixCursor result = new MatrixCursor(columns); Object[] row = new Object[columns.length];
        for (int i = 0; i < columns.length; i++) row[i] = OpenableColumns.DISPLAY_NAME.equals(columns[i]) ? "synthetic-external.png"
                : OpenableColumns.SIZE.equals(columns[i]) ? file.length() : null;
        result.addRow(row); return result;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("Read-only synthetic provider");
        return ParcelFileDescriptor.open(file(getContext(), uri.getLastPathSegment()), ParcelFileDescriptor.MODE_READ_ONLY);
    }
    @Override public Uri insert(Uri u, ContentValues v) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri u, ContentValues v, String s, String[] a) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri u, String s, String[] a) { throw new UnsupportedOperationException(); }
}
