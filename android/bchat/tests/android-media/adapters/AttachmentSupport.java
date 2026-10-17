package com.baseer.freshchat;

import android.content.Context;
import java.io.File;
import java.io.IOException;

/** Synthetic private audio fixture only; not production import/authentication coverage. */
final class AttachmentSupport {
    static File requirePrivateFile(Context context, ChatStore.Attachment attachment) throws IOException {
        File root = new File(context.getFilesDir(), "fixture-audio").getCanonicalFile();
        File file = new File(attachment.path).getCanonicalFile();
        if (!root.equals(file.getParentFile()) || !file.getName().equals("fixture.bin") || !file.isFile())
            throw new SourceUnavailableException();
        return file;
    }
    static final class SourceUnavailableException extends IOException {
        enum Reason { MISSING, IO }
        final Reason reason = Reason.IO;
    }
}
