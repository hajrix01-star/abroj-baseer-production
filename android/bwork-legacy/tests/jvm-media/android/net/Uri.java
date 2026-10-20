package android.net;
public final class Uri {
    private final java.net.URI value;
    private Uri(String value) { this.value = java.net.URI.create(value); }
    public static Uri parse(String value) { return new Uri(value); }
    public String getScheme() { return value.getScheme(); }
    public String getAuthority() { return value.getAuthority(); }
}
