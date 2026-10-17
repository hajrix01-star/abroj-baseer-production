package android.graphics;
public final class Bitmap {
    public enum Config { ARGB_8888 }
    public static Bitmap createBitmap(int w, int h, Config c) { throw new AssertionError("Legacy bitmap allocation"); }
}
