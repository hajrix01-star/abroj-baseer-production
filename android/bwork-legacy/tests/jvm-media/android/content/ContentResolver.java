package android.content;
import android.net.Uri;
import android.database.Cursor;
import java.io.*;
public abstract class ContentResolver {
    public static final String SCHEME_CONTENT = "content";
    public abstract String getType(Uri uri);
    public abstract Cursor query(Uri uri, String[] columns, String selection, String[] args, String sort);
    public abstract InputStream openInputStream(Uri uri) throws IOException;
    public abstract OutputStream openOutputStream(Uri uri, String mode) throws IOException;
}
