package com.baseer.bwork.legacy;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Random;

/**
 * JVM tests of the helper's pure byte/path/metadata policy. Include android.jar on the classpath
 * to resolve framework types, but no stubbed Android method, provider, or microphone is called.
 */
public final class AttachmentPolicyTest {
    private static int passed;
    private interface CheckedAction { void run() throws Exception; }

    private static void check(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
        ++passed;
        System.out.println("PASS " + label);
    }

    private static boolean rejects(CheckedAction action) throws Exception {
        try { action.run(); return false; } catch (IOException expected) { return true; }
    }

    public static void main(String[] args) throws Exception {
        check("image/jpeg".equals(AttachmentSupport.safeMime(" Image/JPEG ; charset=UTF-8 ", null)),
                "Concrete MIME is normalized without active interpretation");
        check("audio/mp4".equals(AttachmentSupport.safeMime(null, "audio/mp4")),
                "Audio fallback MIME is retained");
        check("application/octet-stream".equals(AttachmentSupport.safeMime("*/*", "image/*")),
                "Wildcard MIME becomes opaque generic data");
        check("application/octet-stream".equals(AttachmentSupport.safeMime("text/html\r\nevil", null)),
                "Invalid MIME metadata is rejected");
        check("application/vnd.example+zip".equals(
                AttachmentSupport.safeMime("application/vnd.example+zip", null)),
                "Generic vendor file MIME is allowed without launch or execution");
        check("attachment.pdf".equals(AttachmentSupport.safeDisplayName(null, "application/pdf")),
                "Missing display name receives a safe fallback");
        check("attachment".equals(AttachmentSupport.safeDisplayName("...", "text/plain")),
                "Dot-only file names cannot become traversal names");
        String unsafe = AttachmentSupport.safeDisplayName("../a\\b\u202Egpj.exe\n", "application/octet-stream");
        check(!unsafe.contains("/") && !unsafe.contains("\\") && !unsafe.contains("\u202E")
                        && !unsafe.contains("\n") && !unsafe.startsWith("."),
                "Path separators, control characters, and bidi spoofing are removed");
        check("تقرير العمل.pdf".equals(AttachmentSupport.safeDisplayName("تقرير العمل.pdf", "application/pdf")),
                "Arabic original display names remain readable");
        StringBuilder longArabic = new StringBuilder();
        for (int i = 0; i < 160; ++i) longArabic.append("ت");
        String bounded = AttachmentSupport.safeDisplayName(longArabic + ".pdf", "application/pdf");
        check(bounded.length() <= 140 && bounded.getBytes(StandardCharsets.UTF_8).length <= 240
                        && bounded.endsWith(".pdf"),
                "Long Unicode names obey character and byte limits while preserving extension");
        StringBuilder emojis = new StringBuilder();
        for (int i = 0; i < 200; ++i) emojis.append("\uD83C\uDFB5");
        String emojiName = AttachmentSupport.safeDisplayName(emojis + ".m4a", "audio/mp4");
        check(emojiName.equals(new String(emojiName.getBytes(StandardCharsets.UTF_8), StandardCharsets.UTF_8)),
                "Name truncation never splits a Unicode surrogate pair");
        check(AttachmentSupport.checkedLimit(AttachmentSupport.MAX_BATCH_BYTES) == AttachmentSupport.MAX_FILE_BYTES
                        && AttachmentSupport.checkedLimit(123L) == 123L
                        && AttachmentSupport.checkedLimit(0L) == 0L,
                "Remaining batch budget and per-file maximum both apply");
        check(rejects(() -> AttachmentSupport.checkedLimit(-1)), "Negative remaining budgets are rejected");

        byte[] source = new byte[180_321];
        new Random(517L).nextBytes(source);
        ByteArrayOutputStream copied = new ByteArrayOutputStream();
        long bytes = AttachmentSupport.copyLimited(new ByteArrayInputStream(source), copied, source.length);
        check(bytes == source.length && Arrays.equals(source, copied.toByteArray()),
                "Random binary attachment bytes are copied exactly without recompression");
        ByteArrayOutputStream limited = new ByteArrayOutputStream();
        check(rejects(() -> AttachmentSupport.copyLimited(new ByteArrayInputStream(source), limited, 32767))
                        && limited.size() <= 32767,
                "Oversized streams stop before writing beyond the remaining limit");
        check(AttachmentSupport.copyLimited(new ByteArrayInputStream(new byte[0]),
                        new ByteArrayOutputStream(), 0) == 0,
                "A legitimate empty generic file can be copied with zero remaining bytes");
        check(rejects(() -> AttachmentSupport.copyLimited(new ByteArrayInputStream(new byte[]{1}),
                        new ByteArrayOutputStream(), 0)),
                "A nonempty unknown-size file is rejected when batch budget is exhausted");
        InputStream unusual = new ByteArrayInputStream(new byte[]{1, 2, 3}) {
            private boolean zero = true;
            @Override public synchronized int read(byte[] target, int offset, int count) {
                if (zero) { zero = false; return 0; }
                return super.read(target, offset, count);
            }
        };
        ByteArrayOutputStream unusualCopy = new ByteArrayOutputStream();
        check(AttachmentSupport.copyLimited(unusual, unusualCopy, 3) == 3
                        && Arrays.equals(new byte[]{1, 2, 3}, unusualCopy.toByteArray()),
                "A zero-byte stream read cannot spin or lose original bytes");
        Thread.currentThread().interrupt();
        try {
            check(rejects(() -> AttachmentSupport.copyLimited(new ByteArrayInputStream(source),
                            new ByteArrayOutputStream(), source.length)) && Thread.currentThread().isInterrupted(),
                    "Canceled copying stops immediately and preserves the interruption signal");
        } finally { Thread.interrupted(); }

        Path root = Files.createTempDirectory("baseer-attachment-policy-");
        try {
            Path directory = Files.createDirectory(root.resolve("attachments"));
            Path file = directory.resolve("original.bin");
            Files.write(file, source);
            check(file.toFile().getCanonicalFile().equals(AttachmentSupport.checkedPrivateFile(
                            directory.toFile(), file.toString(), source.length)),
                    "Only an intact direct child of private attachments is accepted");
            Path outside = root.resolve("outside.bin");
            Files.write(outside, source);
            check(rejects(() -> AttachmentSupport.checkedPrivateFile(directory.toFile(),
                            outside.toString(), source.length)),
                    "A file elsewhere in internal storage cannot be exported");
            check(rejects(() -> AttachmentSupport.checkedPrivateFile(directory.toFile(),
                            directory.resolve("../outside.bin").toString(), source.length)),
                    "Explicit traversal paths are rejected");
            Path symlink = directory.resolve("link.bin");
            Files.createSymbolicLink(symlink, outside);
            check(rejects(() -> AttachmentSupport.checkedPrivateFile(directory.toFile(),
                            symlink.toString(), source.length)),
                    "Symlink escape paths are rejected");
            check(rejects(() -> AttachmentSupport.checkedPrivateFile(directory.toFile(),
                            file.toString(), source.length + 1L)),
                    "Changed attachment byte count is detected before output is opened");
            check(rejects(() -> AttachmentSupport.checkedPrivateFile(directory.toFile(),
                            directory.resolve("missing.bin").toString(), 0)),
                    "Missing files are rejected");
            try {
                AttachmentSupport.checkedPrivateFile(directory.toFile(), directory.resolve("missing.bin").toString(), 0);
                throw new AssertionError("Missing original accepted");
            } catch (AttachmentSupport.SourceUnavailableException missing) {
                check(missing.reason == AttachmentSupport.SourceUnavailableException.Reason.MISSING
                                && !missing.getMessage().contains(root.toString()),
                        "Missing original is classified without disclosing its path");
            }
            try {
                AttachmentSupport.checkedPrivateFile(directory.toFile(), outside.toString(), source.length);
                throw new AssertionError("Outside source accepted");
            } catch (AttachmentSupport.SourceUnavailableException blocked) {
                check(blocked.reason == AttachmentSupport.SourceUnavailableException.Reason.INVALID,
                        "Outside source is blocked before absence classification");
            }
            try {
                AttachmentSupport.checkedPrivateFile(directory.toFile(), file.toString(), source.length + 1L);
                throw new AssertionError("Changed source accepted");
            } catch (AttachmentSupport.SourceUnavailableException changed) {
                check(changed.reason == AttachmentSupport.SourceUnavailableException.Reason.CHANGED,
                        "Changed bytes are distinct from a missing original");
            }
            Path partial = directory.resolve("partial.bin");
            Files.write(partial, new byte[]{1});
            AttachmentSupport.deleteIncomplete(partial.toFile());
            AttachmentSupport.deleteIncomplete(partial.toFile());
            check(!Files.exists(partial), "Partial-file cleanup is idempotent");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> {
                    try { Files.delete(path); } catch (IOException failure) { throw new RuntimeException(failure); }
                });
            }
        }
        System.out.println("PASS: " + passed + " attachment policy tests (no Android runtime execution)");
    }
}
