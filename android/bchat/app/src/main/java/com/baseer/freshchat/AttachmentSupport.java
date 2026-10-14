package com.baseer.freshchat;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.text.Normalizer;
import java.util.Locale;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Original-byte attachment import/export. Call blocking methods on the caller's I/O executor.
 * Imports need a user-selected or user-shared content URI grant. Export needs the content URI
 * returned from the caller's explicit ACTION_CREATE_DOCUMENT flow. No external intents are
 * launched, and neither an extension nor a provider-supplied MIME type executes a file.
 */
public final class AttachmentSupport {
    public static final long MAX_FILE_BYTES = 25L * 1024L * 1024L;
    public static final long MAX_BATCH_BYTES = 100L * 1024L * 1024L;
    private static final String BINARY_MIME = "application/octet-stream";
    private static final Pattern MIME = Pattern.compile(
            "[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*");

    private AttachmentSupport() { }

    /** Safe classification only: no private path, filename, or file contents in the exception. */
    public static final class SourceUnavailableException extends IOException {
        public enum Reason { MISSING, INVALID, CHANGED, CORRUPT }
        public final Reason reason;
        SourceUnavailableException(Reason reason) {
            super("ATTACHMENT_SOURCE_" + reason.name()); this.reason = reason;
        }
    }

    /** Copies all original bytes, never recompressing photos or transcoding imported audio. */
    public static ChatStore.Attachment importUri(Context context, Uri source,
                                                String fallbackMime, long remainingBudget)
            throws IOException {
        requireContentUri(source);
        long limit = checkedLimit(remainingBudget);
        ContentResolver resolver = context.getApplicationContext().getContentResolver();
        String providerMime = null;
        try {
            providerMime = resolver.getType(source);
        } catch (SecurityException denied) {
            throw new IOException("لم يُمنح الإذن لقراءة هذا المرفق", denied);
        } catch (RuntimeException unsupportedMetadata) {
            // An openable provider need not expose a type. The bytes remain opaque.
        }
        String mime = safeMime(providerMime, fallbackMime);
        String suppliedName = null;
        long declaredSize = -1L;
        try (Cursor cursor = resolver.query(source,
                new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameColumn = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int sizeColumn = cursor.getColumnIndex(OpenableColumns.SIZE);
                if (nameColumn >= 0 && !cursor.isNull(nameColumn)) {
                    suppliedName = cursor.getString(nameColumn);
                }
                if (sizeColumn >= 0 && !cursor.isNull(sizeColumn)) {
                    declaredSize = cursor.getLong(sizeColumn);
                }
            }
        } catch (SecurityException denied) {
            throw new IOException("لم يُمنح الإذن لقراءة هذا المرفق", denied);
        } catch (RuntimeException unsupportedMetadata) {
            // Missing or malformed metadata never substitutes for the streaming byte limit.
        }
        if (declaredSize > limit) throw sizeError();
        String name = safeDisplayName(suppliedName, mime);
        String id = UUID.randomUUID().toString();
        File destination = createPrivateFile(context, id, ".bin");
        boolean complete = false;
        try {
            long size;
            MessageDigest digest = newDigest();
            InputStream original = resolver.openInputStream(source);
            try (InputStream input = original == null ? null : new DigestInputStream(original, digest);
                 FileOutputStream output = new FileOutputStream(destination)) {
                if (input == null) throw new IOException("تعذّر فتح المرفق");
                size = copyLimited(input, output, limit);
                validateImportedSize(declaredSize, size, mime);
                output.getFD().sync();
            }
            ChatStore.Attachment attachment = new ChatStore.Attachment(id,
                    destination.getCanonicalPath(), name, mime, size, hex(digest.digest()));
            complete = true;
            return attachment;
        } catch (SecurityException denied) {
            throw new IOException("لم يُمنح الإذن لقراءة هذا المرفق", denied);
        } catch (RuntimeException failedProvider) {
            throw new IOException("تعذّر استيراد المرفق", failedProvider);
        } finally {
            if (!complete) deleteIncomplete(destination);
        }
    }

    /**
     * Saves only to the explicit SAF destination supplied by the caller. On failure a provider
     * may retain an empty/partial output document; the private source is never changed.
     */
    public static void saveToUri(Context context, ChatStore.Attachment attachment, Uri destination)
            throws IOException {
        requireContentUri(destination);
        File source = requirePrivateFile(context, attachment);
        verifyDigest(source, attachment.sha256);
        MessageDigest digest = newDigest();
        try (InputStream input = new DigestInputStream(new FileInputStream(source), digest);
             OutputStream output = context.getApplicationContext().getContentResolver().openOutputStream(destination, "wt")) {
            if (output == null) throw new IOException("Output unavailable");
            long copied = copyLimited(input, output, attachment.size);
            if (copied != attachment.size || attachment.sha256 != null
                    && !attachment.sha256.equals(hex(digest.digest()))) {
                throw new SourceUnavailableException(SourceUnavailableException.Reason.CORRUPT);
            }
            output.flush();
        } catch (IOException | RuntimeException failure) {
            // SAF providers do not necessarily roll back a failed output. Never delete unrelated data.
            throw new IOException("ATTACHMENT_EXPORT_PARTIAL", failure);
        }
    }

    /** Admission-only, off-main helper for freshly finished camera/voice files. Never call on UI bind. */
    public static ChatStore.Attachment withIntegrity(Context context, ChatStore.Attachment attachment) throws IOException {
        File source = requirePrivateFile(context, attachment);
        if (attachment.sha256 != null) { verifyDigest(source, attachment.sha256); return attachment; }
        validateImportedSize(attachment.size, source.length(), attachment.mime);
        return new ChatStore.Attachment(attachment.id, source.getCanonicalPath(), attachment.name,
                attachment.mime, attachment.size, hashFile(source, attachment.size));
    }

    static void validateImportedSize(long declared, long copied, String mime) throws IOException {
        if (declared >= 0 && declared != copied) throw new IOException("ATTACHMENT_IMPORT_CHANGED");
        if (copied == 0 && (mime.startsWith("image/") || mime.startsWith("audio/")
                || mime.startsWith("video/") || "application/pdf".equals(mime)))
            throw new IOException("ATTACHMENT_IMPORT_EMPTY_MEDIA");
    }

    static MessageDigest newDigest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    static String hex(byte[] bytes) {
        char[] result = new char[bytes.length * 2]; final char[] digits = "0123456789abcdef".toCharArray();
        for (int i = 0; i < bytes.length; i++) {
            result[i * 2] = digits[(bytes[i] & 255) >>> 4]; result[i * 2 + 1] = digits[bytes[i] & 15];
        }
        return new String(result);
    }
    static String hashFile(File source, long expectedSize) throws IOException {
        MessageDigest digest = newDigest();
        try (InputStream input = new DigestInputStream(new FileInputStream(source), digest)) {
            long copied = copyLimited(input, new OutputStream() {
                @Override public void write(int ignored) { }
                @Override public void write(byte[] ignored, int offset, int length) { }
            }, Math.min(expectedSize, MAX_FILE_BYTES));
            if (copied != expectedSize) throw new SourceUnavailableException(SourceUnavailableException.Reason.CHANGED);
        }
        return hex(digest.digest());
    }
    static void verifyDigest(File source, String expected) throws IOException {
        if (expected != null && !expected.equals(hashFile(source, source.length())))
            throw new SourceUnavailableException(SourceUnavailableException.Reason.CORRUPT);
    }

    /** Validates confinement and integrity before a preview, local playback, or export. */
    public static File requirePrivateFile(Context context, ChatStore.Attachment attachment)
            throws IOException {
        if (attachment == null) throw new IOException("المرفق غير موجود");
        return checkedPrivateFile(attachmentDirectory(context), attachment.path, attachment.size);
    }

    static File attachmentDirectory(Context context) throws IOException {
        if (context == null) throw new IOException("مساحة التطبيق غير متاحة");
        Context application = context.getApplicationContext();
        if (application == null) throw new IOException("مساحة التطبيق غير متاحة");
        File root = application.getFilesDir().getCanonicalFile();
        File directory = new File(root, "attachments");
        if (!directory.getCanonicalFile().equals(directory)) {
            throw new IOException("مسار المرفقات غير صالح");
        }
        if (!directory.isDirectory() && !directory.mkdirs()) {
            throw new IOException("تعذّر إنشاء مجلد المرفقات");
        }
        return directory;
    }

    static File createPrivateFile(Context context, String id, String suffix) throws IOException {
        try {
            if (!UUID.fromString(id).toString().equals(id)
                    || !(".bin".equals(suffix) || ".m4a".equals(suffix))) {
                throw new IOException("اسم المرفق الداخلي غير صالح");
            }
        } catch (IllegalArgumentException | NullPointerException invalid) {
            throw new IOException("اسم المرفق الداخلي غير صالح", invalid);
        }
        File file = new File(attachmentDirectory(context), id + suffix);
        if (!file.createNewFile()) throw new IOException("تعذّر إنشاء ملف المرفق");
        return file;
    }

    static File checkedPrivateFile(File directory, String path, long expectedSize) throws IOException {
        if (path == null || expectedSize < 0 || expectedSize > MAX_FILE_BYTES) {
            throw new IOException("بيانات المرفق غير صالحة");
        }
        File original = new File(path);
        File canonical = original.getCanonicalFile();
        // Android may expose its private root through /data/user/0 -> /data/data. Permit that
        // platform-owned ancestor alias, but never a symlink attachment or a canonical escape.
        if (!original.isAbsolute() || Files.isSymbolicLink(original.toPath())
                || !directory.getCanonicalFile().equals(canonical.getParentFile())) {
            throw new SourceUnavailableException(SourceUnavailableException.Reason.INVALID);
        }
        // Classify absence only after confinement. A missing original cannot be restored
        // by displaying a cached thumbnail, changing a MIME type, or installing an update.
        if (!canonical.exists()) throw new SourceUnavailableException(SourceUnavailableException.Reason.MISSING);
        if (!canonical.isFile()) throw new SourceUnavailableException(SourceUnavailableException.Reason.INVALID);
        if (canonical.length() != expectedSize) throw new SourceUnavailableException(SourceUnavailableException.Reason.CHANGED);
        return canonical;
    }

    static long checkedLimit(long remainingBudget) throws IOException {
        if (remainingBudget < 0) throw sizeError();
        return Math.min(MAX_FILE_BYTES, Math.min(MAX_BATCH_BYTES, remainingBudget));
    }

    /** Package-visible for byte-fidelity and adversarial stream tests without Android. */
    static long copyLimited(InputStream input, OutputStream output, long limit) throws IOException {
        if (limit < 0) throw sizeError();
        byte[] buffer = new byte[32768];
        long copied = 0;
        while (true) {
            if (Thread.currentThread().isInterrupted()) throw new IOException("أُلغيت عملية نسخ المرفق");
            int count = input.read(buffer);
            if (count < 0) break;
            if (count == 0) {
                // Avoid an unbounded busy loop for an unusual stream returning zero bytes.
                int single = input.read();
                if (single < 0) break;
                if (copied >= limit) throw sizeError();
                output.write(single);
                copied++;
                continue;
            }
            if (count > limit - copied) throw sizeError();
            output.write(buffer, 0, count);
            copied += count;
        }
        return copied;
    }

    static String safeMime(String providerMime, String fallbackMime) {
        String checked = normalizedMime(providerMime);
        if (checked == null) checked = normalizedMime(fallbackMime);
        return checked == null ? BINARY_MIME : checked;
    }

    private static String normalizedMime(String value) {
        if (value == null || value.length() > 200) return null;
        int parameter = value.indexOf(';');
        String candidate = (parameter < 0 ? value : value.substring(0, parameter))
                .trim().toLowerCase(Locale.ROOT);
        return MIME.matcher(candidate).matches() ? candidate : null;
    }

    static String safeDisplayName(String name, String mime) {
        String fallback = "application/pdf".equals(mime) ? "attachment.pdf" : "attachment";
        if (name == null) return fallback;
        // Bound work even if a broken provider returns megabytes of display-name metadata.
        String normalized = Normalizer.normalize(name.substring(0, Math.min(name.length(), 4096)),
                Normalizer.Form.NFC);
        StringBuilder safe = new StringBuilder();
        for (int offset = 0; offset < normalized.length();) {
            int point = normalized.codePointAt(offset);
            offset += Character.charCount(point);
            int type = Character.getType(point);
            if (Character.isISOControl(point) || type == Character.FORMAT
                    || type == Character.SURROGATE || type == Character.LINE_SEPARATOR
                    || type == Character.PARAGRAPH_SEPARATOR
                    || "/\\<>:\"|?*".indexOf(point) >= 0) safe.append('_');
            else safe.appendCodePoint(point);
            // Provider metadata is untrusted; don't allocate an unbounded second copy.
            if (safe.length() >= 512) break;
        }
        String result = safe.toString().trim();
        while (result.startsWith(".")) result = result.substring(1);
        while (result.endsWith(".")) result = result.substring(0, result.length() - 1);
        if (result.trim().isEmpty()) return fallback;
        if (result.length() > 140 || result.getBytes(StandardCharsets.UTF_8).length > 240) {
            int dot = result.lastIndexOf('.');
            String extension = dot > 0 && result.length() - dot <= 16 ? result.substring(dot) : "";
            String stem = extension.isEmpty() ? result : result.substring(0, dot);
            int maxChars = 140 - extension.length();
            int maxBytes = 240 - extension.getBytes(StandardCharsets.UTF_8).length;
            StringBuilder bounded = new StringBuilder();
            int bytes = 0;
            for (int offset = 0; offset < stem.length();) {
                int point = stem.codePointAt(offset);
                String part = new String(Character.toChars(point));
                int length = part.getBytes(StandardCharsets.UTF_8).length;
                if (bounded.length() + part.length() > maxChars || bytes + length > maxBytes) break;
                bounded.append(part);
                bytes += length;
                offset += Character.charCount(point);
            }
            result = bounded.toString().trim() + extension;
        }
        return result.isEmpty() ? fallback : result;
    }

    private static void requireContentUri(Uri uri) throws IOException {
        if (uri == null || !ContentResolver.SCHEME_CONTENT.equals(uri.getScheme())
                || uri.getAuthority() == null || uri.getAuthority().isEmpty()) {
            throw new IOException("اختر الملف أو مكان الحفظ عبر منتقي ملفات النظام");
        }
    }

    private static IOException sizeError() {
        return new IOException("حدود المرفقات: 25 MB للملف و100 MB للمشاركة");
    }

    static void deleteIncomplete(File file) {
        if (file != null && file.exists()) {
            // Only UUID files created by this helper or the recorder are passed here.
            // No orphan sweep: previously admitted draft/message/undo originals remain untouched.
            file.delete();
        }
    }
}
