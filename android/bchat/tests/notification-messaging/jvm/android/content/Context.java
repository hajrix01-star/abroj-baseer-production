package android.content;

/** Explicit JVM adapter, not Android Resources. */
public final class Context {
    public String getString(int resource) {
        if (resource == 1) return "New message in BChat";
        if (resource == 2) return "Sent an attachment";
        throw new AssertionError("Unknown fixture resource");
    }
    public int getColor(int ignored) { throw new AssertionError("Legacy path must not allocate a Person icon"); }
}
