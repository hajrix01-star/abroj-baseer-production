package android.util;
import java.io.*;
import java.nio.file.*;
/** Modern .new/.bak behavior on actual JVM files, not Android AtomicFile execution. */
public class AtomicFile {
    private final File base, next, backup;
    public AtomicFile(File base) { this.base = base; next = new File(base + ".new"); backup = new File(base + ".bak"); }
    private void recover() throws IOException {
        if (backup.exists()) Files.move(backup.toPath(), base.toPath(), StandardCopyOption.REPLACE_EXISTING);
    }
    public FileOutputStream startWrite() throws IOException { recover(); return new FileOutputStream(next); }
    public void finishWrite(FileOutputStream stream) {
        try { stream.getFD().sync(); stream.close(); Files.move(next.toPath(), base.toPath(), StandardCopyOption.REPLACE_EXISTING); }
        catch (IOException ignored) { } // The production platform can log, not throw, these failures.
    }
    public void failWrite(FileOutputStream stream) {
        try { stream.close(); } catch (IOException ignored) { }
        next.delete();
    }
    public FileInputStream openRead() throws IOException {
        recover(); if (base.exists()) next.delete(); return new FileInputStream(base);
    }
}
