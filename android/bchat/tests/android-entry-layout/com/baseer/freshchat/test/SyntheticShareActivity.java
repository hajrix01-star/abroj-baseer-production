package com.baseer.freshchat.test;

import android.app.Activity;
import android.content.*;
import android.graphics.*;
import android.net.Uri;
import android.os.Bundle;
import android.widget.TextView;
import java.io.*;
import java.security.MessageDigest;

/** Runs as the separate test-package UID, granting only its own freshly generated fixture. */
public final class SyntheticShareActivity extends Activity {
    public static final String TOKEN = "syntheticToken", SHA = "syntheticSha256";
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        String token = getIntent().getStringExtra(TOKEN);
        File file = SyntheticShareProvider.file(this, token);
        if ("cleanup".equals(getIntent().getAction())) { if (file.exists()) file.delete(); finish(); return; }
        TextView label = new TextView(this); label.setText("Disposable synthetic PNG sharing fixture"); setContentView(label);
        try {
            Bitmap bitmap = Bitmap.createBitmap(40, 30, Bitmap.Config.ARGB_8888); bitmap.eraseColor(Color.rgb(40, 120, 200));
            try (FileOutputStream output = new FileOutputStream(file)) {
                if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)) throw new IOException("PNG encoding failed");
            } finally { bitmap.recycle(); }
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream input = new FileInputStream(file)) { byte[] data = new byte[4096]; for (int n; (n = input.read(data)) >= 0;) digest.update(data, 0, n); }
            StringBuilder sha = new StringBuilder(); for (byte value : digest.digest()) sha.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            Uri uri = Uri.parse("content://com.baseer.freshchat.entryboundarytest.fixture/" + token);
            Intent send = new Intent(Intent.ACTION_SEND).setType("image/png").setComponent(new ComponentName("com.baseer.bchat.preview", "com.baseer.freshchat.MainActivity"))
                    .putExtra(Intent.EXTRA_TEXT, "Synthetic granted PNG العربية / English").putExtra(Intent.EXTRA_STREAM, uri)
                    .putExtra(SHA, sha.toString()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            send.setClipData(ClipData.newRawUri("Synthetic generated PNG", uri));
            startActivity(send); finish();
        } catch (Exception error) { label.setText("Synthetic source failed: " + error.getClass().getSimpleName()); }
    }
}
