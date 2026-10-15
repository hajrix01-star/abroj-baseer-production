package android.content;
import java.io.File;
/** Test-only JVM adapter, never part of the application. */
public abstract class Context {
    public Context getApplicationContext() { return this; }
    public abstract ContentResolver getContentResolver();
    public abstract File getFilesDir();
}
