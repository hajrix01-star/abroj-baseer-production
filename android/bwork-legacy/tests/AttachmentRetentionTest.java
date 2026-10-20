package com.baseer.bwork.legacy;

import java.awt.image.BufferedImage;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Set;
import java.util.UUID;
import javax.imageio.ImageIO;

/**
 * Host behavioral regression, not Android runtime evidence. The runner transplants the exact
 * current MainActivity.cleanupAttachments method into AttachmentCleanupHarness. ChatStore and
 * AttachmentSupport are the real sources. Android stubs are resolved but never invoked.
 */
public final class AttachmentRetentionTest {
    private static int passed;
    private interface Checked { void run() throws Exception; }
    private static void check(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
        ++passed;
        System.out.println("PASS " + label);
    }
    private static void rejects(Checked action, String label) throws Exception {
        boolean rejected = false;
        try { action.run(); } catch (IOException expected) { rejected = true; }
        check(rejected, label);
    }

    /** Exact 0.4.2 HEAD 8165f946 cleanup body, renamed only for isolated synthetic replay. */
    private static final class FrozenCleanup extends AttachmentCleanupHarness {
        void frozenCleanup() {
            if (importing || store == null || voiceRecorder != null) return;
            Set<String> live = store.attachmentPaths();
            File[] files = new File(getFilesDir(), "attachments").listFiles();
            if (files == null) return;
            for (File file : files) {
                String path = file.getAbsolutePath();
                if (file.isFile() && file.getName().matches("[a-f0-9-]{36}\\.[a-zA-Z0-9]{1,12}") && !live.contains(path) && !path.equals(cameraPath) && (exportAttachment == null || !path.equals(exportAttachment.path))) file.delete();
            }
        }
    }
    private static <T extends AttachmentCleanupHarness> T setup(T app, Path base, boolean alias) throws Exception {
        Path real = Files.createDirectories(base.resolve("data/data/com.baseer.bwork.legacy/files"));
        Files.createDirectory(real.resolve("attachments"));
        Files.createDirectories(base.resolve("data/user"));
        Files.createSymbolicLink(base.resolve("data/user/0"), base.resolve("data/data"));
        app.filesDir = (alias ? base.resolve("data/user/0/com.baseer.bwork.legacy/files") : real).toFile();
        app.store = new ChatStore(new File(app.filesDir, "isolated-chat.bin"));
        return app;
    }
    private static File generated(AttachmentCleanupHarness app, boolean voice) throws Exception {
        File file = new File(new File(app.filesDir, "attachments"), UUID.randomUUID() + (voice ? ".m4a" : ".bin"));
        if (voice) {
            // Path retention only; these bytes do not claim to test a media decoder.
            Files.write(file.toPath(), new byte[]{1, 2, 3, 4});
        } else {
            BufferedImage bitmap = new BufferedImage(32, 24, BufferedImage.TYPE_INT_RGB);
            for (int y = 0; y < 24; ++y) for (int x = 0; x < 32; ++x)
                bitmap.setRGB(x, y, x < 16 ? (y < 12 ? 0xff0000 : 0x0000ff) : (y < 12 ? 0x00ff00 : 0xffffff));
            if (!ImageIO.write(bitmap, "PNG", file)) throw new IOException("Synthetic PNG unavailable");
        }
        return file;
    }
    private static ChatStore.Attachment attachment(File file, boolean canonical, boolean voice) throws Exception {
        return new ChatStore.Attachment(UUID.randomUUID().toString(),
                canonical ? file.getCanonicalPath() : file.getAbsolutePath(),
                voice ? "synthetic.m4a" : "synthetic.png", voice ? "audio/mp4" : "image/png", file.length());
    }
    private static void makeLive(AttachmentCleanupHarness app, String kind, ChatStore.Attachment file) throws Exception {
        String company = ChatStore.INITIAL_COMPANY_ID;
        String conversation = app.store.conversations(company).get(0).id;
        if ("share".equals(kind)) app.store.stagePendingShare("", Collections.singletonList(file));
        else {
            app.store.setDraft(company, conversation, "", Collections.singletonList(file));
            if ("sent".equals(kind) || "undo".equals(kind)) {
                ChatStore.Message sent = app.store.send(company, conversation);
                if ("undo".equals(kind)) app.store.deleteMessageLocally(company, conversation, sent.id);
            }
        }
        // Exercise persisted metadata, including the private undo record, rather than a fake set.
        app.store = new ChatStore(new File(app.filesDir, "isolated-chat.bin"));
    }
    private static byte[] digest(File file) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath()));
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("bwork-retention-");
        try {
            for (String kind : new String[]{"draft", "sent", "undo", "share", "voice"}) {
                FrozenCleanup old = setup(new FrozenCleanup(), root.resolve("frozen-" + kind), true);
                File file = generated(old, "voice".equals(kind));
                ChatStore.Attachment a = attachment(file, true, "voice".equals(kind));
                makeLive(old, kind, a);
                if (!"voice".equals(kind)) check(ImageIO.read(file).getWidth() == 32, kind + " has valid synthetic image pixels before frozen cleanup");
                check(AttachmentSupport.checkedPrivateFile(new File(old.filesDir, "attachments"), a.path, a.size).isFile(), kind + " source passes confinement before frozen cleanup");
                old.frozenCleanup();
                check(!file.exists() && old.store.attachmentPaths().contains(a.path), "Frozen bug reproduced: " + kind + " original deleted but reference persists");
                rejects(() -> AttachmentSupport.checkedPrivateFile(new File(old.filesDir, "attachments"), a.path, a.size), kind + " preview/export rejects missing original after frozen cleanup");
            }
            for (boolean alias : new boolean[]{false, true}) for (boolean canonical : new boolean[]{false, true}) {
                if (!(alias && canonical)) {
                    FrozenCleanup old = setup(new FrozenCleanup(), root.resolve("frozen-control-" + alias + canonical), alias);
                    File f = generated(old, false); makeLive(old, "draft", attachment(f, canonical, false)); old.frozenCleanup();
                    check(f.exists(), "Frozen negative control survives; alias=" + alias + ", canonical=" + canonical);
                }
                for (String kind : new String[]{"draft", "sent", "undo", "share", "voice"}) {
                    AttachmentCleanupHarness app = setup(new AttachmentCleanupHarness(), root.resolve("current-" + alias + canonical + kind), alias);
                    File file = generated(app, "voice".equals(kind)); byte[] before = digest(file);
                    ChatStore.Attachment a = attachment(file, canonical, "voice".equals(kind)); makeLive(app, kind, a);
                    app.runCleanup(); app.runCleanup();
                    check(Arrays.equals(before, digest(file)) && app.store.attachmentPaths().contains(a.path),
                            "Current cleanup preserves exact " + kind + " bytes; alias=" + alias + ", canonical=" + canonical);
                }
                for (String kind : new String[]{"camera", "export"}) {
                    AttachmentCleanupHarness app = setup(new AttachmentCleanupHarness(), root.resolve(kind + alias + canonical), alias);
                    File file = generated(app, false); byte[] before = digest(file); ChatStore.Attachment a = attachment(file, canonical, false);
                    if ("camera".equals(kind)) app.cameraPath = a.path; else app.exportAttachment = a;
                    app.runCleanup();
                    check(Arrays.equals(before, digest(file)), "Current cleanup preserves uncommitted " + kind + "; alias=" + alias + ", canonical=" + canonical);
                }
            }
            AttachmentCleanupHarness app = setup(new AttachmentCleanupHarness(), root.resolve("conservative"), true);
            File orphan = generated(app, false); byte[] before = digest(orphan);
            File folder = new File(app.filesDir, "attachments");
            Path inRootLink = folder.toPath().resolve(UUID.randomUUID() + ".bin"); Files.createSymbolicLink(inRootLink, orphan.toPath());
            Path outside = root.resolve("outside.bin"); Files.write(outside, new byte[]{9, 8, 7});
            Path escape = folder.toPath().resolve(UUID.randomUUID() + ".bin"); Files.createSymbolicLink(escape, outside);
            Path broken = folder.toPath().resolve(UUID.randomUUID() + ".bin"); Files.createSymbolicLink(broken, root.resolve("missing.bin"));
            Path nested = Files.createDirectory(folder.toPath().resolve(UUID.randomUUID() + ".bin")); Files.write(nested.resolve("keep.bin"), new byte[]{1});
            Path unknown = folder.toPath().resolve("other-original.bin"); Files.write(unknown, new byte[]{2});
            app.runCleanup();
            check(Arrays.equals(before, digest(orphan)), "True UUID orphan is intentionally retained until reviewed storage cleanup exists");
            check(Files.isSymbolicLink(inRootLink) && Files.isSymbolicLink(escape) && Files.isSymbolicLink(broken), "Cleanup neither follows nor deletes any leaf symlink");
            check(Arrays.equals(Files.readAllBytes(outside), new byte[]{9, 8, 7}), "Outside symlink target remains untouched");
            check(Files.exists(nested.resolve("keep.bin")) && Files.exists(unknown), "Nested and unknown files remain untouched");
            app.store = null; app.runCleanup();
            check(Arrays.equals(before, digest(orphan)), "Missing/stale store cannot trigger any deletion");
            check(AttachmentSupport.checkedPrivateFile(folder, orphan.getAbsolutePath(), orphan.length()).equals(orphan.getCanonicalFile()), "Private read permits platform-like ancestor alias");
            rejects(() -> AttachmentSupport.checkedPrivateFile(folder, inRootLink.toString(), orphan.length()), "Private read still rejects in-root leaf symlink");
            rejects(() -> AttachmentSupport.checkedPrivateFile(folder, escape.toString(), 3), "Private read still rejects symlink escape");
            rejects(() -> AttachmentSupport.checkedPrivateFile(folder, outside.toString(), 3), "Private read still rejects direct outside path");
            rejects(() -> AttachmentSupport.checkedPrivateFile(folder, orphan.getAbsolutePath(), orphan.length() + 1), "Private read still rejects size mismatch");
            System.out.println("PASS " + passed + " attachment retention assertions; host execution only, not Android/media/device validation.");
        } finally {
            // Test-created scratch only. Files.walk does not follow symbolic links by default.
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                paths.sorted(Comparator.reverseOrder()).forEach(path -> { try { Files.deleteIfExists(path); } catch (IOException ignored) { } });
            }
        }
    }
}
