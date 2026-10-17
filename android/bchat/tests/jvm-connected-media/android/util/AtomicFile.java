package android.util;

import java.io.*;
import java.nio.file.*;

/** Test-only file-system adapter for both Android AtomicFile protocols, not Android execution. */
public final class AtomicFile {
    public static boolean legacy;
    public static int opens;
    private final File base, backup, next;
    public AtomicFile(File file) {
        base = file; backup = new File(file + ".bak"); next = new File(file + ".new");
    }
    private static void replace(File source, File destination) throws IOException {
        Files.move(source.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }
    public FileOutputStream startWrite() throws IOException {
        if (legacy) {
            if (base.exists() && !backup.exists()) replace(base, backup);
            else if (base.exists() && !base.delete()) throw new IOException("Cannot stage base");
            return new FileOutputStream(base);
        }
        return new FileOutputStream(next);
    }
    public void finishWrite(FileOutputStream stream) throws IOException {
        stream.getFD().sync(); stream.close();
        if (legacy) backup.delete();
        else replace(next, base);
    }
    public void failWrite(FileOutputStream stream) {
        try { stream.close(); } catch (IOException ignored) { }
        try {
            if (legacy) { base.delete(); if (backup.exists()) replace(backup, base); }
            else next.delete();
        } catch (IOException failure) { throw new IllegalStateException(failure); }
    }
    public FileInputStream openRead() throws IOException {
        opens++;
        if (backup.exists()) replace(backup, base);
        if (base.exists()) next.delete();
        return new FileInputStream(base);
    }
    public void delete() { base.delete(); backup.delete(); next.delete(); }
}
