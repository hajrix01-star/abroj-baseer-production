package com.baseer.freshchat;
import android.content.Context;
/** Audio lifecycle fixture does not claim localization coverage (tested separately). */
final class AppLocale {
    static Context wrap(Context context) { return context; }
    static String error(Context context, String code) { return code; }
}
