package com.baseer.bwork.legacy.test;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.util.HashMap;
import java.util.Map;

/** In-process only; not declared/exported in any manifest. Holds synthetic fixtures only. */
public final class ImageFixtureProvider extends ContentProvider {
    private static final class Entry {
        final File file; final String mime;
        Entry(File file, String mime) { this.file = file; this.mime = mime; }
    }
    private final Map<String, Entry> entries = new HashMap<>();
    public Uri register(File file, String mime) {
        String key = java.util.UUID.randomUUID().toString(); entries.put(key, new Entry(file, mime));
        return Uri.parse("content://bwork.synthetic.images/" + key);
    }
    private Entry entry(Uri uri) {
        Entry found = entries.get(uri.getLastPathSegment());
        if (found == null) throw new IllegalArgumentException("Unknown synthetic fixture");
        return found;
    }
    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { return entry(uri).mime; }
    @Override public Cursor query(Uri uri, String[] columns, String selection, String[] args, String sort) {
        Entry found = entry(uri);
        String[] names = columns == null ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : columns;
        MatrixCursor result = new MatrixCursor(names); Object[] values = new Object[names.length];
        for (int i = 0; i < names.length; i++) values[i] = OpenableColumns.SIZE.equals(names[i]) ? found.file.length() : "synthetic-image";
        result.addRow(values); return result;
    }
    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        return ParcelFileDescriptor.open(entry(uri).file, ParcelFileDescriptor.parseMode(mode));
    }
    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String selection, String[] args) { throw new UnsupportedOperationException(); }
}
