package com.baseer.freshchat;

/** Keep one signed APK on the configured server for phones and emulators. */
public final class RuntimeOrigin {
    private RuntimeOrigin() { }

    public static String forHardware(String hardware, String configuredOrigin) {
        // Hardware must not silently switch a QA release back to the local test server.
        return configuredOrigin;
    }
}
