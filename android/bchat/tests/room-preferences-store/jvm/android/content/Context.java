package android.content;
import java.io.File;
/** Explicit JVM Context boundary; never Android or application storage. */
public class Context {
    private final File files;
    public int fileLookups;
    public Context(File files) { this.files = files; }
    public Context getApplicationContext() { return this; }
    public File getFilesDir() { ++fileLookups; return files; }
}
