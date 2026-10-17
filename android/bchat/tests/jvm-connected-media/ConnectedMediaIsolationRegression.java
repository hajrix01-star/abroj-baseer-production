package com.baseer.freshchat.sync;

import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import java.io.*;
import java.nio.file.*;
import java.util.*;

/** Uses only the original public API so the same behavioral test compiles before C01. */
public final class ConnectedMediaIsolationRegression {
    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("bchat-isolation-before-");
        try {
            Context context = new Context() {
                public File getFilesDir() { return root.toFile(); }
                public ContentResolver getContentResolver() { return null; }
            };
            ContentResolver provider = new ContentResolver() {
                public String getType(Uri uri) { return "image/jpeg"; }
                public Cursor query(Uri u, String[] c, String s, String[] a, String sort) { return null; }
                public InputStream openInputStream(Uri u) { return new ByteArrayInputStream(new byte[]{1,2,3}); }
                public OutputStream openOutputStream(Uri u, String m) { throw new UnsupportedOperationException(); }
            };
            AccountScope account = new AccountScope("https://bchat.example", "qa", 7);
            BChatConnectedMediaStore store = new BChatConnectedMediaStore(context);
            BChatConnectedMediaStore.Entry a = store.stage(provider, account, 1, 2, 101, Uri.parse("content://fixture/1"), "", 0);
            BChatConnectedMediaStore.Entry b = store.stage(provider, account, 2, 2, 102, Uri.parse("content://fixture/2"), "", 0);
            Path damaged = root.resolve("bchat-v2-media").resolve(account.key).resolve(a.uploadUuid + ".json");
            Files.write(damaged, new byte[]{'!'});
            if (store.pending(account, 2, 102) == null || !store.pending(account, 2, 102).clientUuid.equals(b.clientUuid))
                throw new AssertionError("Corrupt room A poisoned healthy room B");
            System.out.println("PASS unchanged public API: corrupt A leaves healthy B pending usable");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
}
