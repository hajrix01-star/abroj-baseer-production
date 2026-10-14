package com.baseer.freshchat;

/** Keep one signed APK for phones and the local Android emulator. */
public final class RuntimeOrigin {
    private static final String EMULATOR_LOCAL_ORIGIN = "https://localhost:18443";

    private RuntimeOrigin() { }

    public static String forHardware(String hardware, String phoneOrigin) {
        if ("ranchu".equalsIgnoreCase(hardware) || "goldfish".equalsIgnoreCase(hardware)) {
            return EMULATOR_LOCAL_ORIGIN;
        }
        return phoneOrigin;
    }
}
