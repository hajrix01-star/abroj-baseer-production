package com.baseer.freshchat;

import android.util.AtomicFile;
import java.io.*;

/** Explicit I/O injections around the real Store, not claims of physical disk failures. */
final class StoreFaults {
    static final class SilentFinish extends AtomicFile {
        SilentFinish(File file) { super(file); }
        @Override public void finishWrite(FileOutputStream stream) {
            try { stream.close(); } catch (IOException ignored) { }
            // Intentionally returns without committing the .new file.
        }
    }
    static final class ClosedBeforeSync extends AtomicFile {
        private final File base;
        ClosedBeforeSync(File file) { super(file); base = file; }
        @Override public FileOutputStream startWrite() throws IOException {
            FileOutputStream first = super.startWrite(); first.close();
            return new FileOutputStream(new File(base + ".new")) {
                @Override public void write(byte[] bytes) throws IOException { super.write(bytes); super.close(); }
            };
        }
    }
    private StoreFaults() { }
}
