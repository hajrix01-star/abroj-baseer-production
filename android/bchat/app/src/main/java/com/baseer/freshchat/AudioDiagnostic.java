package com.baseer.freshchat;

import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.List;

/** Bounded, memory-only diagnostics. Never accepts paths, names, messages or audio bytes. */
public final class AudioDiagnostic {
    public static final int CAPACITY = 12;
    public enum Stage { SOURCE, SETUP, PREPARE, DURATION, FOCUS, START, PAUSE, SEEK, SPEED, PROGRESS }
    public enum Kind { IO, SECURITY, STATE, ARGUMENT, RUNTIME, NATIVE, TIMEOUT, INVALID, DENIED, MISSING }
    public static final class Event {
        public final Stage stage;
        public final Kind kind;
        public final int what, extra;
        Event(Stage stage, Kind kind, int what, int extra) {
            this.stage = stage; this.kind = kind; this.what = what; this.extra = extra;
        }
        public String code() { return "BP-" + stage.name() + "-" + kind.name(); }
        public String summary() { return code() + " what=" + what + " extra=" + extra; }
        public boolean unsupported() { return kind == Kind.NATIVE && (what == -1010 || extra == -1010); }
        public String guidance() {
            if (stage == Stage.SOURCE && kind == Kind.MISSING) return "ATTACHMENT_SOURCE_MISSING";
            if (stage == Stage.FOCUS) return "الصوت مشغول حاليًا. أوقف المكالمة أو الصوت الآخر ثم أعد المحاولة.";
            if (stage == Stage.SOURCE) return "تعذّر فتح النسخة المحلية. أعد اختيار الملف من مصدره؛ لا تحذف التطبيق أو المسودة.";
            if (unsupported()) return "صيغة الصوت غير مدعومة في مشغّل هذا الجهاز. من تفاصيل المرفق اختر «حفظ نسخة…» لتجربتها في مشغّل آخر.";
            if (stage == Stage.SPEED) return "تغيير السرعة غير متاح لهذا الملف على هذا الجهاز؛ أُبقيت السرعة السابقة.";
            return "تعذّر تشغيل الصوت. اضغط التشغيل لإعادة المحاولة. يمكنك حفظ الأصل من تفاصيل المرفق ← «حفظ نسخة…».";
        }
    }
    private final ArrayDeque<Event> events = new ArrayDeque<>();
    public Event record(Stage stage, Kind kind, int what, int extra) {
        if (stage == null || kind == null) throw new IllegalArgumentException("Stage and kind required");
        Event event = new Event(stage, kind, what, extra);
        if (events.size() == CAPACITY) events.removeFirst();
        events.addLast(event); return event;
    }
    public Event exception(Stage stage, Throwable failure) {
        Kind kind = failure instanceof SecurityException ? Kind.SECURITY
                : failure instanceof IllegalStateException ? Kind.STATE
                : failure instanceof IllegalArgumentException ? Kind.ARGUMENT
                : failure instanceof IOException ? Kind.IO : Kind.RUNTIME;
        // Deliberately do not retain Throwable, its message, stack, or cause.
        return record(stage, kind, 0, 0);
    }
    public List<Event> snapshot() { return new ArrayList<>(events); }
    public String summary() {
        StringBuilder text = new StringBuilder();
        for (Event event : events) { if (text.length() > 0) text.append('\n'); text.append(event.summary()); }
        return text.toString();
    }
}
