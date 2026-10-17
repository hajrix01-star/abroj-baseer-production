package com.baseer.freshchat;

import android.content.Context;
import android.graphics.Color;

/** Resource-resolved semantic tokens, with a bounded adapter for existing Ui call sites. */
final class UiPalette {
    private UiPalette() { }
    static int surface(Context c) { return c.getColor(R.color.bchat_surface); }
    static int ink(Context c) { return c.getColor(R.color.bchat_ink); }
    static int muted(Context c) { return c.getColor(R.color.bchat_muted); }
    static int accent(Context c) { return c.getColor(R.color.bchat_accent); }
    static int line(Context c) { return c.getColor(R.color.bchat_line); }
    static int canvas(Context c) { return c.getColor(R.color.bchat_canvas); }
    static int sent(Context c) { return c.getColor(R.color.bchat_sent); }
    static int received(Context c) { return c.getColor(R.color.bchat_received); }

    static int foreground(Context c, int token) {
        if (token == Ui.INK) return ink(c);
        if (token == Ui.MUTED) return muted(c);
        if (token == Ui.GREEN) return accent(c);
        if (token == Ui.LINE) return line(c);
        if (token == Ui.SKY) return c.getColor(R.color.bchat_accent_bright);
        if (token == Ui.TASK_ACTIVE) return accent(c);
        if (token == Ui.TASK_DONE) return c.getColor(R.color.bchat_success);
        if (token == Ui.TASK_CLOSED) return muted(c);
        return token; // In particular WHITE is still white on primary/header controls.
    }

    static int background(Context c, int token) {
        if (token == Color.WHITE) return surface(c);
        if (token == Ui.LIGHT) return c.getColor(R.color.bchat_background);
        if (token == Ui.CHAT_CANVAS) return canvas(c);
        if (token == Ui.CHAT_SENT) return sent(c);
        if (token == Ui.LINE) return line(c);
        if (token == Ui.LIME || token == Ui.ACTION_TONAL) return c.getColor(R.color.bchat_tonal);
        if (token == Ui.ACTION_TONAL_PRESSED) return c.getColor(R.color.bchat_tonal_pressed);
        if (token == Ui.ACTION_DISABLED) return c.getColor(R.color.bchat_disabled);
        if (token == Ui.TASK_ACTIVE_TINT) return c.getColor(R.color.bchat_tonal);
        if (token == Ui.TASK_DONE_TINT) return c.getColor(R.color.bchat_success_tint);
        if (token == Ui.TASK_CLOSED_TINT) return c.getColor(R.color.bchat_disabled);
        return token;
    }
}
