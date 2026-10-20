package android.database;
public interface Cursor extends AutoCloseable {
    boolean moveToFirst(); int getColumnIndex(String name); boolean isNull(int column);
    String getString(int column); long getLong(int column); void close();
}
