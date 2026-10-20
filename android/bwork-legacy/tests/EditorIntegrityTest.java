package com.baseer.bwork.legacy;

import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

/** Pure descriptor and real synthetic-store checks for the candidate editor integration seam. */
public final class EditorIntegrityTest {
    static final String CO = "demo-nour", CV = CO + "-ops";
    static final String FIRST = repeat('a'), SECOND = repeat('b');
    static final List<ChatStore.Attachment> NONE = Collections.emptyList();
    static int tests;
    interface Check { void run() throws Exception; }
    static void test(String name, Check work) throws Exception { work.run(); tests++; System.out.println("PASS " + name); }
    static void require(boolean value, String why) { if (!value) throw new AssertionError(why); }
    static String repeat(char c) { char[] text = new char[64]; Arrays.fill(text, c); return new String(text); }
    static ChatStore.Attachment file(String name, String digest) {
        return new ChatStore.Attachment(UUID.randomUUID().toString(), "/tmp/bwork-synthetic-editor/" + name, name, "image/png", 69, digest);
    }
    static ChatStore.Attachment digest(ChatStore.Attachment file, String value) {
        return new ChatStore.Attachment(file.id, file.path, file.name, file.mime, file.size, value);
    }
    static EditorState editor(ChatStore.Attachment... files) { return new EditorState(CO, CV, null, "text", Arrays.asList(files), null); }
    static void rejects(Check work) throws Exception {
        try { work.run(); } catch (IllegalArgumentException expected) { return; }
        throw new AssertionError("Expected conflicting metadata to be rejected");
    }
    public static void main(String[] args) throws Exception {
        test("integrity-only upgrade creates a dirty revision", () -> {
            ChatStore.Attachment plain = file("one.png", null), known = digest(plain, FIRST); EditorState state = editor(plain);
            long revision = state.snapshot().revision;
            require(state.update("text", Collections.singletonList(known), null), "upgrade is not hidden by matching IDs");
            require(state.dirty() && state.snapshot().revision > revision && state.snapshot().files.get(0).sha256.equals(FIRST), "upgrade tracked");
        });
        test("stale text edit cannot discard an established checksum", () -> {
            ChatStore.Attachment plain = file("one.png", null), known = digest(plain, FIRST); EditorState state = editor(known);
            state.update("new text", Collections.singletonList(plain), "reply");
            require(state.snapshot().text.equals("new text") && state.snapshot().replyId.equals("reply")
                    && state.snapshot().files.get(0).sha256.equals(FIRST), "text and reply apply without downgrade");
        });
        test("digest-less duplicate snapshot is a no-op without downgrade", () -> {
            ChatStore.Attachment plain = file("one.png", null), known = digest(plain, FIRST); EditorState state = editor(known);
            long revision = state.snapshot().revision;
            require(!state.update("text", Collections.singletonList(plain), null) && state.snapshot().revision == revision,
                    "same effective contents stay unchanged");
        });
        test("incoming removal wins without resurrecting established files", () -> {
            ChatStore.Attachment a = file("one.png", FIRST), b = file("two.png", SECOND); EditorState state = editor(a, b);
            state.update("text", Collections.singletonList(digest(b, null)), null);
            require(state.snapshot().files.size() == 1 && state.snapshot().files.get(0).id.equals(b.id)
                    && state.snapshot().files.get(0).sha256.equals(SECOND), "removed file absent and retained digest kept");
        });
        test("contradictory non-null checksum is rejected atomically", () -> {
            ChatStore.Attachment known = file("one.png", FIRST); EditorState state = editor(known);
            EditorState.Snapshot before = state.snapshot();
            rejects(() -> state.update("should not apply", Collections.singletonList(digest(known, SECOND)), "new reply"));
            require(state.snapshot().revision == before.revision && state.snapshot().text.equals(before.text)
                    && state.snapshot().files.get(0).sha256.equals(FIRST), "conflict preserves prior complete editor");
        });
        test("same ID cannot inherit checksum across different source metadata", () -> {
            ChatStore.Attachment known = file("one.png", FIRST); EditorState state = editor(known);
            List<ChatStore.Attachment> conflicts = Arrays.asList(
                    new ChatStore.Attachment(known.id, known.path + ".other", known.name, known.mime, known.size),
                    new ChatStore.Attachment(known.id, known.path, "renamed.png", known.mime, known.size),
                    new ChatStore.Attachment(known.id, known.path, known.name, "image/jpeg", known.size),
                    new ChatStore.Attachment(known.id, known.path, known.name, known.mime, known.size + 1));
            for (ChatStore.Attachment changed : conflicts) rejects(() -> state.update("changed", Collections.singletonList(changed), null));
            require(state.snapshot().text.equals("text") && state.snapshot().files.get(0) == known, "no conflicting source admitted");
        });
        test("duplicate incoming IDs cannot partially update editor", () -> {
            ChatStore.Attachment known = file("one.png", FIRST); EditorState state = editor(known);
            rejects(() -> state.update("changed", Arrays.asList(known, digest(known, null)), null));
            require(state.snapshot().files.size() == 1 && state.snapshot().text.equals("text"), "duplicate rejected before mutation");
        });
        test("incoming order is retained while checksums stay attached to exact IDs", () -> {
            ChatStore.Attachment a = file("one.png", FIRST), b = file("two.png", SECOND); EditorState state = editor(a, b);
            state.update("text", Arrays.asList(digest(b, null), digest(a, null)), null);
            require(state.snapshot().files.get(0).id.equals(b.id) && state.snapshot().files.get(0).sha256.equals(SECOND)
                    && state.snapshot().files.get(1).id.equals(a.id) && state.snapshot().files.get(1).sha256.equals(FIRST), "order and identity separated");
        });
        test("old durable acknowledgement cannot acknowledge a newer checksum upgrade", () -> {
            ChatStore.Attachment plain = file("one.png", null); EditorState state = editor(plain);
            state.requireSave(); EditorState.Snapshot prior = state.snapshot();
            state.update("text", Collections.singletonList(digest(plain, FIRST)), null); state.committed(prior);
            require(state.dirty(), "integrity upgrade still needs persistence");
            state.committed(state.snapshot()); require(!state.dirty(), "current upgrade acknowledged");
        });
        test("recovery merges durable digest without replacing saved edits or readding removals", () -> {
            ChatStore.Attachment a = file("one.png", FIRST), b = file("two.png", SECOND);
            EditorState saved = editor(digest(b, null)); saved.update("saved latest", Collections.singletonList(digest(b, null)), "reply");
            EditorState recovered = EditorState.recover(saved.snapshot(), Arrays.asList(a, b));
            require(recovered.dirty() && recovered.snapshot().text.equals("saved latest") && recovered.snapshot().replyId.equals("reply")
                    && recovered.snapshot().editorId.equals(saved.snapshot().editorId) && recovered.snapshot().files.size() == 1
                    && recovered.snapshot().files.get(0).id.equals(b.id) && recovered.snapshot().files.get(0).sha256.equals(SECOND), "durable checksums only, saved membership wins");
        });
        test("conflicting durable recovery is visible instead of silently choosing a digest", () -> {
            ChatStore.Attachment known = file("one.png", FIRST); EditorState saved = editor(digest(known, SECOND));
            rejects(() -> EditorState.recover(saved.snapshot(), Collections.singletonList(known)));
            require(saved.snapshot().files.get(0).sha256.equals(SECOND), "saved editor remains unmodified for explicit conflict handling");
        });
        test("legacy files remain digest-less through editing and recovery", () -> {
            ChatStore.Attachment old = file("legacy.png", null); EditorState state = editor(old);
            state.update("new legacy text", Collections.singletonList(old), null);
            EditorState recovered = EditorState.recover(state.snapshot(), Collections.singletonList(old));
            require(recovered.snapshot().files.get(0).sha256 == null, "no file read or retrospective certification");
        });
        test("sending and retired editor ownership checks remain intact", () -> {
            ChatStore.Attachment plain = file("one.png", null); EditorState sending = editor(plain);
            sending.beginSend(UUID.randomUUID().toString(), CO, CV);
            require(!sending.update("changed", Collections.singletonList(digest(plain, FIRST)), null), "sending remains locked");
            EditorState retired = editor(plain); retired.retire();
            require(!retired.update("changed", Collections.singletonList(digest(plain, FIRST)), null), "retired remains closed");
        });
        test("real stale draft write boundary preserves digest and explicit removals", () -> {
            Path home = args.length == 0 ? Files.createTempDirectory("bwork-integrity-editor-")
                    : Files.createTempDirectory(new File(args[0]).getCanonicalFile().toPath(), "bwork-integrity-editor-");
            try {
                Path path = home.resolve("one.png"), other = home.resolve("two.png");
                Files.write(path, CaptureAdmissionTest.RED); Files.write(other, CaptureAdmissionTest.GREEN);
                ChatStore.Attachment a = new ChatStore.Attachment(UUID.randomUUID().toString(), path.toString(), "one.png", "image/png",
                        CaptureAdmissionTest.RED.length, CaptureAdmissionTest.sha(CaptureAdmissionTest.RED));
                ChatStore.Attachment b = new ChatStore.Attachment(UUID.randomUUID().toString(), other.toString(), "two.png", "image/png",
                        CaptureAdmissionTest.GREEN.length, CaptureAdmissionTest.sha(CaptureAdmissionTest.GREEN));
                ChatStore store = new ChatStore(home.resolve("chat.bin").toFile()); store.setDraft(CO, CV, "old", Arrays.asList(a, b));
                List<ChatStore.Attachment> stale = Collections.singletonList(digest(b, null));
                ArrayList<ChatStore.Attachment> write = IntegrityAttachments.preserve(store.draft(CO, CV).attachments, stale);
                store.setDraft(CO, CV, "latest saved text", write);
                ChatStore.Draft reopened = store.reopen().draft(CO, CV);
                require(reopened.text.equals("latest saved text") && reopened.attachments.size() == 1
                        && reopened.attachments.get(0).id.equals(b.id) && reopened.attachments.get(0).sha256.equals(b.sha256), "exact persisted integrity and removal");
                require(Arrays.equals(CaptureAdmissionTest.RED, Files.readAllBytes(path)) && Arrays.equals(CaptureAdmissionTest.GREEN, Files.readAllBytes(other)), "originals untouched");
            } finally { CaptureAdmissionTest.remove(home); }
        });
        System.out.println("PASS: " + tests + " editor-integrity cases");
    }
}
