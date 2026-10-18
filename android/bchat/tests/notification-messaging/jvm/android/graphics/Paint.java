package android.graphics;
public final class Paint {
    public static final int ANTI_ALIAS_FLAG = 1;
    public enum Align { CENTER }
    public Paint(int flags) { throw new AssertionError("Legacy Paint allocation"); }
    public void setColor(int color) { }
    public void setTextAlign(Align align) { }
    public void setTextSize(float size) { }
    public float measureText(String text) { return 0; }
    public float getTextSize() { return 0; }
    public float ascent() { return 0; }
    public float descent() { return 0; }
}
