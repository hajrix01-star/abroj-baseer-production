package android.app;

import android.graphics.drawable.Icon;
/** Forbidden sentinel: every Person construction fails in the legacy-only fixture. */
public final class Person {
    public static final class Builder {
        public Builder() { throw new AssertionError("Person/API28 reached on API26/27 path"); }
        public Builder setName(CharSequence name) { return this; }
        public Builder setKey(String key) { return this; }
        public Builder setIcon(Icon icon) { return this; }
        public Person build() { return null; }
    }
}
