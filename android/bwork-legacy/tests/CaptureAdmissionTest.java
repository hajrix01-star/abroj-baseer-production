package com.baseer.bwork.legacy;

import java.io.File;
import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Base64;
import java.util.Collections;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Valid synthetic PNG/WAV files; ordinary fault, restart and interleaving tests only. */
public final class CaptureAdmissionTest {
    static final String CO = "demo-nour", CV = CO + "-ops", OTHER = "demo-madar";
    static final byte[] RED = Base64.getDecoder().decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC");
    static final byte[] GREEN = Base64.getDecoder().decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNg+M8AAAICAQB7CYF4AAAAAElFTkSuQmCC");
    static final byte[] BLUE = Base64.getDecoder().decode("iVBORw0KGgoAAAANSUhEUgAAAAMAAAADCAIAAADZSiLoAAAAD0lEQVR4nGNgYPgPQ5gsAH2gCPgfW8MjAAAAAElFTkSuQmCC");
    static Thread ui;
    static ExecutorService workers;
    static Path fixtureParent;
    static int tests;
    interface Check { void run() throws Exception; }
    static void test(String name, Check check) throws Exception {
        check.run(); tests++; System.out.println("PASS " + name);
    }
    static void require(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    static void throwsType(Class<? extends Throwable> type, Check work) throws Exception {
        try { work.run(); } catch (Throwable error) {
            if (type.isInstance(error)) return;
            throw new AssertionError("Expected " + type.getSimpleName() + " but received " + error, error);
        }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
    static String uuid() { return UUID.randomUUID().toString(); }
    static String sha(byte[] bytes) throws Exception {
        byte[] value = MessageDigest.getInstance("SHA-256").digest(bytes);
        StringBuilder result = new StringBuilder();
        for (byte b : value) result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }
    static CaptureAdmission.DigestResult hash(CaptureAdmission ledger, CaptureAdmission.HashTicket ticket) throws Exception {
        try { return workers.submit(() -> ledger.hash(ticket, ui)).get(); }
        catch (ExecutionException failure) {
            if (failure.getCause() instanceof Exception) throw (Exception) failure.getCause();
            throw (Error) failure.getCause();
        }
    }
    static final class Capture {
        final String id = uuid(), attachment = uuid();
        final Path path;
        final String name, mime;
        final CaptureAdmission.Kind kind;
        Capture(Path path, CaptureAdmission.Kind kind) {
            this.path = path; this.kind = kind; this.name = kind == CaptureAdmission.Kind.PHOTO ? "Synthetic photo.png" : "Synthetic voice.wav";
            this.mime = kind == CaptureAdmission.Kind.PHOTO ? "image/png" : "audio/wav";
        }
    }
    static final class Fixture implements AutoCloseable {
        final Path home, sources, journal, chat;
        CaptureAdmission ledger;
        Fixture() throws Exception {
            home = fixtureParent == null ? Files.createTempDirectory("bwork-capture-valid-")
                    : Files.createTempDirectory(fixtureParent, "bwork-capture-valid-");
            sources = Files.createDirectory(home.resolve("attachments"));
            journal = home.resolve("capture-admission.bin"); chat = home.resolve("chat.bin");
            ledger = reopen();
        }
        CaptureAdmission reopen() throws Exception { return new CaptureAdmission(journal.toFile(), sources.toFile()); }
        Capture reserve() throws Exception { return reserve(CaptureAdmission.Kind.PHOTO); }
        Capture reserve(CaptureAdmission.Kind kind) throws Exception {
            Capture capture = new Capture(sources.resolve(uuid() + (kind == CaptureAdmission.Kind.PHOTO ? ".png" : ".wav")), kind);
            reserve(capture, CO, CV); return capture;
        }
        void reserve(Capture capture, String company, String conversation) throws Exception {
            ledger.reserve(capture.id, capture.attachment, company, conversation,
                    capture.path.toFile(), capture.name, capture.mime, capture.kind);
        }
        Capture pending() throws Exception {
            Capture capture = reserve(); Files.write(capture.path, RED); ledger.seal(capture.id); return capture;
        }
        Capture ready() throws Exception {
            Capture capture = pending();
            require(ledger.acceptDigest(hash(ledger, ledger.claimHash(capture.id))), "hash accepted");
            return capture;
        }
        ChatStore store() throws Exception { return new ChatStore(chat.toFile()); }
        void publish(ChatStore store, CaptureAdmission.AdmissionTicket ticket) throws Exception {
            ChatStore.Draft before = store.draft(ticket.job.company, ticket.job.conversation);
            java.util.ArrayList<ChatStore.Attachment> files = new java.util.ArrayList<ChatStore.Attachment>(before.attachments);
            files.add(ticket.attachment);
            store.setDraft(ticket.job.company, ticket.job.conversation, before.text, files, before.replyToMessageId);
        }
        public void close() throws Exception { remove(home); }
    }
    static void remove(Path path) throws IOException {
        if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            try (DirectoryStream<Path> children = Files.newDirectoryStream(path)) {
                for (Path child : children) remove(child);
            }
        }
        Files.deleteIfExists(path);
    }
    static void phase(CaptureAdmission ledger, Capture capture, CaptureAdmission.Phase expected) {
        require(ledger.get(capture.id).phase == expected, "Expected " + expected + ", got " + ledger.get(capture.id).phase);
    }
    static void original(Capture capture, byte[] bytes) throws Exception {
        require(Files.exists(capture.path) && Arrays.equals(bytes, Files.readAllBytes(capture.path)), "Original fixture bytes remain intact");
    }
    static void blockRoot(Path root, Check operation) throws Exception {
        Path held = root.resolveSibling(root.getFileName() + ".fixture-held");
        Files.move(root, held); Files.createDirectory(root);
        try { operation.run(); }
        finally { Files.delete(root); Files.move(held, root); }
    }
    static byte[] wav() {
        java.nio.ByteBuffer data = java.nio.ByteBuffer.allocate(60).order(java.nio.ByteOrder.LITTLE_ENDIAN);
        data.put(new byte[]{'R','I','F','F'}).putInt(52).put(new byte[]{'W','A','V','E','f','m','t',' '});
        data.putInt(16).putShort((short) 1).putShort((short) 1).putInt(8000).putInt(16000);
        data.putShort((short) 2).putShort((short) 16).put(new byte[]{'d','a','t','a'}).putInt(16);
        for (int i = 0; i < 8; i++) data.putShort((short) (i % 2 == 0 ? 1000 : -1000));
        return data.array();
    }

    public static void main(String[] args) throws Exception {
        ui = Thread.currentThread(); workers = Executors.newFixedThreadPool(2);
        if (args.length > 0) fixtureParent = new File(args[0]).getCanonicalFile().toPath();
        try {
            test("reservation survives restart before producer starts", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve(); CaptureAdmission restarted = f.reopen();
                    phase(restarted, c, CaptureAdmission.Phase.RESERVED);
                    CaptureAdmission.Job job = restarted.get(c.id);
                    require(job.attachmentId.equals(c.attachment) && job.company.equals(CO) && job.conversation.equals(CV)
                            && job.path.equals(c.path.toFile().getCanonicalPath()) && job.size == -1 && job.sha256 == null, "exact uncompleted capture");
                    require(!Files.exists(c.path), "reservation never creates capture bytes");
                }
            });
            test("repeated callback and reservation do not create or retarget jobs", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); byte[] root = Files.readAllBytes(f.journal);
                    f.reserve(c, CO, CV); f.ledger.seal(c.id);
                    require(f.ledger.jobs().size() == 1 && Arrays.equals(root, Files.readAllBytes(f.journal)), "idempotent no-write callback");
                    throwsType(IllegalArgumentException.class, () -> f.reserve(c, OTHER, OTHER + "-ops"));
                    require(f.ledger.get(c.id).company.equals(CO), "original target retained"); original(c, RED);
                }
            });
            test("changed capture path or metadata cannot reuse an ID", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve();
                    throwsType(IllegalArgumentException.class, () -> f.ledger.reserve(c.id, c.attachment, CO, CV,
                            f.sources.resolve("another.png").toFile(), c.name, c.mime, c.kind));
                    throwsType(IllegalArgumentException.class, () -> f.ledger.reserve(c.id, c.attachment, CO, CV,
                            c.path.toFile(), "Changed.png", c.mime, c.kind));
                    require(f.ledger.jobs().size() == 1, "original reservation only");
                }
            });
            test("attachment IDs and canonical paths remain unique across receipts", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve(); f.ledger.cancel(c.id);
                    throwsType(IllegalArgumentException.class, () -> f.ledger.reserve(uuid(), c.attachment, CO, CV,
                            f.sources.resolve("another.png").toFile(), c.name, c.mime, c.kind));
                    throwsType(IllegalArgumentException.class, () -> f.ledger.reserve(uuid(), uuid(), CO, CV,
                            c.path.toFile(), c.name, c.mime, c.kind));
                    phase(f.reopen(), c, CaptureAdmission.Phase.CANCELED);
                }
            });
            test("existing legacy capture cannot be retrospectively enrolled", () -> {
                try (Fixture f = new Fixture()) {
                    Path legacy = f.sources.resolve("legacy.png"); Files.write(legacy, RED);
                    ChatStore store = f.store(); ChatStore.Attachment old = new ChatStore.Attachment(legacy.toString(), "Legacy.png", "image/png", RED.length);
                    store.setDraft(CO, CV, "legacy", Collections.singletonList(old));
                    throwsType(IOException.class, () -> f.ledger.reserve(uuid(), uuid(), CO, CV, legacy.toFile(), "Legacy.png", "image/png", CaptureAdmission.Kind.PHOTO));
                    require(f.ledger.jobs().isEmpty() && f.store().draft(CO, CV).attachments.get(0).sha256 == null, "legacy remains unmodified and uncertified");
                    require(Arrays.equals(RED, Files.readAllBytes(legacy)), "legacy original unchanged");
                }
            });
            test("active capacity is enforced before accepting a new producer", () -> {
                try (Fixture f = new Fixture()) {
                    Capture first = null;
                    for (int i = 0; i < CaptureAdmission.MAX_ACTIVE_JOBS; i++) { Capture c = f.reserve(); if (first == null) first = c; }
                    throwsType(IOException.class, () -> f.reserve());
                    require(f.ledger.jobs().size() == CaptureAdmission.MAX_ACTIVE_JOBS, "no over-capacity reservation");
                    f.ledger.cancel(first.id); f.reserve();
                    require(f.reopen().jobs().size() == CaptureAdmission.MAX_ACTIVE_JOBS + 1, "cancellation releases active capacity but retains receipt");
                }
            });
            test("owned directory aliases canonicalize without changing identity", () -> {
                try (Fixture f = new Fixture()) {
                    Path alias = f.home.resolve("owned-alias"); Files.createSymbolicLink(alias, f.sources);
                    CaptureAdmission ledger = new CaptureAdmission(f.journal.toFile(), alias.toFile());
                    String id = uuid(); Path target = alias.resolve("canonical.png");
                    ledger.reserve(id, uuid(), CO, CV, target.toFile(), "Photo.png", "image/png", CaptureAdmission.Kind.PHOTO);
                    require(ledger.get(id).path.equals(f.sources.resolve("canonical.png").toString()), "canonical identity retained");
                    require(f.reopen().get(id).path.equals(ledger.get(id).path), "alias survives canonical reopen");
                }
            });
            test("outside paths are rejected without modifying any source", () -> {
                try (Fixture f = new Fixture()) {
                    throwsType(IOException.class, () -> f.ledger.reserve(uuid(), uuid(), CO, CV,
                            f.home.resolve("outside.png").toFile(), "Photo.png", "image/png", CaptureAdmission.Kind.PHOTO));
                    require(f.ledger.jobs().isEmpty(), "no outside job");
                }
            });
            test("unfinished unavailable source stays reserved and can finish later", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve(); throwsType(IOException.class, () -> f.ledger.seal(c.id));
                    phase(f.ledger, c, CaptureAdmission.Phase.RESERVED);
                    Files.write(c.path, RED); f.ledger.seal(c.id); phase(f.reopen(), c, CaptureAdmission.Phase.PENDING); original(c, RED);
                }
            });
            test("photo hash is off-main and retains exact digest through restart", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    throwsType(IllegalStateException.class, () -> f.ledger.hash(ticket, ui));
                    require(f.ledger.acceptDigest(hash(f.ledger, ticket)), "background result accepted");
                    CaptureAdmission.Job ready = f.reopen().get(c.id);
                    require(sha(RED).equals(ready.sha256) && ready.attachmentId.equals(c.attachment) && ready.size == RED.length, "exact ready attachment");
                    original(c, RED);
                }
            });
            test("valid voice capture uses the same admission contract", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve(CaptureAdmission.Kind.VOICE); byte[] bytes = wav(); Files.write(c.path, bytes);
                    f.ledger.seal(c.id); f.ledger.acceptDigest(hash(f.ledger, f.ledger.claimHash(c.id)));
                    CaptureAdmission.Job ready = f.reopen().get(c.id);
                    require(ready.kind == CaptureAdmission.Kind.VOICE && ready.mime.equals("audio/wav") && ready.sha256.equals(sha(bytes)), "voice identity and hash");
                    original(c, bytes);
                }
            });
            test("repeated claims and duplicate hash callbacks are idempotent", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    require(f.ledger.claimHash(c.id) == null, "one active ticket per generation");
                    CaptureAdmission.DigestResult result = hash(f.ledger, ticket);
                    require(f.ledger.acceptDigest(result) && !f.ledger.acceptDigest(result), "one acceptance");
                    require(!f.ledger.hashFailed(ticket, CaptureAdmission.Failure.IO_RETRY) && f.ledger.claimHash(c.id) == null, "late failure cannot demote READY");
                }
            });
            test("retry state survives restart without forgetting identity", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket old = f.ledger.claimHash(c.id);
                    f.ledger.hashFailed(old, CaptureAdmission.Failure.IO_RETRY);
                    CaptureAdmission restarted = f.reopen(); phase(restarted, c, CaptureAdmission.Phase.RETRY);
                    require(restarted.get(c.id).failure == CaptureAdmission.Failure.IO_RETRY, "retry reason retained");
                    CaptureAdmission.HashTicket retry = restarted.claimHash(c.id);
                    require(retry.job.generation > old.job.generation && restarted.acceptDigest(hash(restarted, retry)), "retry receives fresh ticket"); original(c, RED);
                }
            });
            test("ordinary size change cannot reseal or certify the same capture", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); Files.write(c.path, BLUE);
                    f.ledger.seal(c.id); require(f.ledger.get(c.id).size == RED.length, "duplicate completion cannot change sealed size");
                    CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    throwsType(IOException.class, () -> hash(f.ledger, ticket));
                    f.ledger.hashFailed(ticket, CaptureAdmission.Failure.SOURCE_CHANGED);
                    phase(f.reopen(), c, CaptureAdmission.Phase.RETRY); original(c, BLUE);
                }
            });
            test("same-size ordinary modification time change fails hashing", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); long sealed = f.ledger.get(c.id).modifiedMillis;
                    Files.write(c.path, GREEN); Files.setLastModifiedTime(c.path, FileTime.fromMillis(sealed + 5000));
                    CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    throwsType(IOException.class, () -> hash(f.ledger, ticket));
                    require(f.ledger.get(c.id).sha256 == null, "changed source is not certified"); original(c, GREEN);
                }
            });
            test("delayed hash callback rejects changed source metadata", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    CaptureAdmission.DigestResult result = hash(f.ledger, ticket);
                    Files.write(c.path, GREEN); Files.setLastModifiedTime(c.path, FileTime.fromMillis(ticket.job.modifiedMillis + 5000));
                    throwsType(IOException.class, () -> f.ledger.acceptDigest(result));
                    require(!f.ledger.requiresReopen(), "source failure is not journal uncertainty");
                    f.ledger.hashFailed(ticket, CaptureAdmission.Failure.SOURCE_CHANGED);
                    phase(f.reopen(), c, CaptureAdmission.Phase.RETRY); original(c, GREEN);
                }
            });
            test("delayed callback rejects ordinary same-size source replacement", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    CaptureAdmission.DigestResult result = hash(f.ledger, ticket);
                    Path replacement = f.sources.resolve("replacement.png"); Files.write(replacement, GREEN);
                    Files.setLastModifiedTime(replacement, FileTime.fromMillis(ticket.job.modifiedMillis));
                    Files.move(replacement, c.path, StandardCopyOption.REPLACE_EXISTING);
                    Object fileKey = Files.readAttributes(c.path, java.nio.file.attribute.BasicFileAttributes.class).fileKey();
                    if (fileKey != null) throwsType(IOException.class, () -> f.ledger.acceptDigest(result));
                    else System.out.println("NOTE filesystem exposes no file key; replacement check limited to size/time");
                    original(c, GREEN);
                }
            });
            test("cancel while a hash callback is outstanding cannot resurrect it", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket ticket = f.ledger.claimHash(c.id);
                    CaptureAdmission.DigestResult result = hash(f.ledger, ticket);
                    require(f.ledger.cancel(c.id) && !f.ledger.acceptDigest(result), "cancel fences callback");
                    require(!f.ledger.hashFailed(ticket, CaptureAdmission.Failure.IO_RETRY), "late retry ignored");
                    phase(f.reopen(), c, CaptureAdmission.Phase.CANCELED); original(c, RED);
                }
            });
            test("cancel remains terminal across duplicate completion and restart", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); f.ledger.cancel(c.id); f.ledger = f.reopen();
                    f.ledger.seal(c.id); f.reserve(c, CO, CV);
                    require(!f.ledger.cancel(c.id) && f.ledger.claimHash(c.id) == null && f.ledger.beginAdmission(c.id) == null, "canceled cannot restart");
                    phase(f.ledger, c, CaptureAdmission.Phase.CANCELED); original(c, RED);
                }
            });
            test("restart during hashing fences the previous worker generation", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.HashTicket old = f.ledger.claimHash(c.id);
                    CaptureAdmission.DigestResult late = hash(f.ledger, old);
                    CaptureAdmission fresh = f.reopen(); CaptureAdmission.HashTicket replacement = fresh.claimHash(c.id);
                    require(replacement.job.generation > old.job.generation && !fresh.acceptDigest(late), "fresh ledger rejects old session");
                    throwsType(IOException.class, () -> f.ledger.acceptDigest(late));
                    require(f.ledger.requiresReopen(), "old writer root identity rejects overwrite");
                    fresh.acceptDigest(hash(fresh, replacement)); phase(f.reopen(), c, CaptureAdmission.Phase.READY); original(c, RED);
                }
            });
            test("stale ledger writer must reopen before accepting any job", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.reserve(); CaptureAdmission stale = f.reopen(); f.ledger.cancel(c.id);
                    Path path = f.sources.resolve("late.png");
                    throwsType(IOException.class, () -> stale.reserve(uuid(), uuid(), CO, CV, path.toFile(), "Late.png", "image/png", CaptureAdmission.Kind.PHOTO));
                    require(stale.requiresReopen() && f.reopen().jobs().size() == 1 && !Files.exists(path), "stale write cannot admit a producer");
                }
            });
            test("ordinary metadata write failure leaves last acknowledged job and original", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); byte[] prior = Files.readAllBytes(f.journal);
                    blockRoot(f.journal, () -> throwsType(IOException.class, () -> f.ledger.cancel(c.id)));
                    require(f.ledger.requiresReopen() && Arrays.equals(prior, Files.readAllBytes(f.journal)), "failed save did not acknowledge cancellation");
                    phase(f.ledger, c, CaptureAdmission.Phase.READY); phase(f.reopen(), c, CaptureAdmission.Phase.READY); original(c, RED);
                }
            });
            test("lost READY callback is recovered from durable metadata", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); f.ledger.acceptDigest(hash(f.ledger, f.ledger.claimHash(c.id)));
                    CaptureAdmission restarted = f.reopen(); phase(restarted, c, CaptureAdmission.Phase.READY);
                    require(restarted.claimHash(c.id) == null && restarted.get(c.id).sha256.equals(sha(RED)), "established digest never recomputed");
                }
            });
            test("admission ticket is exact-target and never sends", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); int before = store.messageCount(CO, CV);
                    CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    require(ticket.job.company.equals(CO) && ticket.job.conversation.equals(CV) && ticket.attachment.id.equals(c.attachment)
                            && ticket.attachment.sha256.equals(sha(RED)), "ticket identity exact");
                    require(f.ledger.beginAdmission(c.id) == null && store.draft(CO, CV).attachments.isEmpty()
                            && store.messageCount(CO, CV) == before, "ticket alone performs no chat mutation or send");
                }
            });
            test("issued admission tickets never regain READY even before an apparent write", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    require(f.ledger.reconcileDraft(c.id, store) == CaptureAdmission.Observation.NOT_FOUND
                            && f.ledger.beginAdmission(c.id) == null && f.ledger.claimHash(c.id) == null,
                            "absence and an apparently unused ticket never authorize retry");
                    require(f.ledger.dismissUnresolved(c.id, (expected, closure) -> closure.run()), "only explicit closure is available");
                    phase(f.reopen(), c, CaptureAdmission.Phase.DISMISSED); original(c, RED);
                }
            });
            test("restart after dispatch never assumes that absence permits retry", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    CaptureAdmission fresh = f.reopen(); phase(fresh, c, CaptureAdmission.Phase.ADMITTING);
                    require(fresh.reconcileDraft(c.id, store) == CaptureAdmission.Observation.NOT_FOUND && fresh.beginAdmission(c.id) == null,
                            "missing evidence remains unresolved");
                    throwsType(IllegalStateException.class, () -> fresh.cancel(c.id)); original(c, RED);
                }
            });
            test("editor-only acceptance is not durable admission evidence", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    EditorState editor = new EditorState(CO, CV, null, "", Collections.<ChatStore.Attachment>emptyList(), null);
                    editor.update("", Collections.singletonList(ticket.attachment), null);
                    require(editor.dirty() && f.ledger.reconcileDraft(c.id, f.store()) == CaptureAdmission.Observation.NOT_FOUND, "editor memory cannot acknowledge store");
                    phase(f.ledger, c, CaptureAdmission.Phase.ADMITTING);
                }
            });
            test("actual store success with lost receipt reconciles exactly after restart", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); store.setDraft(CO, CV, "Keep my text", Collections.<ChatStore.Attachment>emptyList());
                    int before = store.messageCount(CO, CV); f.publish(store, f.ledger.beginAdmission(c.id));
                    CaptureAdmission fresh = f.reopen();
                    require(fresh.reconcileDraft(c.id, store) == CaptureAdmission.Observation.CONFIRMED, "fresh exact durable evidence");
                    require(fresh.reconcileDraft(c.id, store) == CaptureAdmission.Observation.CONFIRMED, "repeat receipt is idempotent");
                    phase(f.reopen(), c, CaptureAdmission.Phase.ADMITTED);
                    require(f.store().draft(CO, CV).attachments.size() == 1 && f.store().draft(CO, CV).text.equals("Keep my text")
                            && f.store().messageCount(CO, CV) == before, "no duplication, text loss or send"); original(c, RED);
                }
            });
            test("uncertain store acknowledgement keeps exact job and blocks replay", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    f.ledger.admissionUncertain(ticket); CaptureAdmission fresh = f.reopen();
                    require(fresh.get(c.id).needsReconciliation() && fresh.get(c.id).sha256.equals(sha(RED))
                            && fresh.beginAdmission(c.id) == null && fresh.claimHash(c.id) == null, "uncertain is retained and fenced");
                    throwsType(IllegalStateException.class, () -> fresh.cancel(c.id)); original(c, RED);
                }
            });
            test("same attachment in another conversation cannot acknowledge original target", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    store.setDraft(OTHER, OTHER + "-ops", "other", Collections.singletonList(ticket.attachment));
                    require(f.ledger.reconcileDraft(c.id, store) == CaptureAdmission.Observation.NOT_FOUND, "wrong destination is not evidence");
                    phase(f.ledger, c, CaptureAdmission.Phase.ADMITTING);
                }
            });
            test("digest-less or conflicting store descriptor cannot certify capture", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    ChatStore.Attachment missingDigest = new ChatStore.Attachment(ticket.attachment.id, ticket.attachment.path,
                            ticket.attachment.name, ticket.attachment.mime, ticket.attachment.size);
                    store.setDraft(CO, CV, "", Collections.singletonList(missingDigest));
                    require(f.ledger.reconcileDraft(c.id, store) == CaptureAdmission.Observation.CONFLICT, "SHA required in durable state");
                    ChatStore.Attachment changedName = new ChatStore.Attachment(ticket.attachment.id, ticket.attachment.path,
                            "Another name.png", ticket.attachment.mime, ticket.attachment.size, ticket.attachment.sha256);
                    store.setDraft(CO, CV, "", Collections.singletonList(changedName));
                    require(f.ledger.reconcileDraft(c.id, store) == CaptureAdmission.Observation.CONFLICT, "all descriptor fields must match");
                }
            });
            test("stale ChatStore snapshot cannot falsely acknowledge a removed attachment", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore stale = f.store(); f.publish(stale, f.ledger.beginAdmission(c.id));
                    ChatStore current = f.store(); current.setDraft(CO, CV, "Removed intentionally", Collections.<ChatStore.Attachment>emptyList());
                    require(stale.draft(CO, CV).attachments.size() == 1, "fixture has a stale non-disabled store");
                    require(f.ledger.reconcileDraft(c.id, stale) == CaptureAdmission.Observation.NOT_FOUND, "reconcile must reread durable store");
                    phase(f.ledger, c, CaptureAdmission.Phase.ADMITTING); original(c, RED);
                }
            });
            test("user send before receipt is inconclusive and never auto-replayed", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    f.publish(store, ticket); ChatStore.Draft draft = store.draft(CO, CV); int before = store.messageCount(CO, CV);
                    store.sendDraftSnapshot(CO, CV, draft.text, draft.attachments, draft.replyToMessageId, uuid());
                    f.ledger.admissionUncertain(ticket); CaptureAdmission fresh = f.reopen();
                    require(fresh.reconcileDraft(c.id, store) == CaptureAdmission.Observation.NOT_FOUND && fresh.beginAdmission(c.id) == null,
                            "sent draft is not auto-added again");
                    require(f.store().messageCount(CO, CV) == before + 1 && f.store().draft(CO, CV).attachments.isEmpty(), "one user-requested send only"); original(c, RED);
                }
            });
            test("ordinary chat write failure is held for explicit reconciliation", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    blockRoot(f.chat, () -> throwsType(IOException.class, () -> f.publish(store, ticket)));
                    f.ledger.admissionUncertain(ticket);
                    require(f.reopen().reconcileDraft(c.id, f.store()) == CaptureAdmission.Observation.NOT_FOUND, "negative observation never restarts dispatch");
                    require(f.store().draft(CO, CV).attachments.isEmpty(), "failed write did not publish"); original(c, RED);
                }
            });
            test("receipt write failure after successful chat write reconciles without duplicate", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); f.publish(store, f.ledger.beginAdmission(c.id));
                    blockRoot(f.journal, () -> throwsType(IOException.class, () -> f.ledger.reconcileDraft(c.id, store)));
                    require(f.ledger.requiresReopen(), "receipt acknowledgement not claimed");
                    CaptureAdmission fresh = f.reopen();
                    require(fresh.reconcileDraft(c.id, store) == CaptureAdmission.Observation.CONFIRMED && f.store().draft(CO, CV).attachments.size() == 1,
                            "one durable attachment survives lost receipt"); original(c, RED);
                }
            });
            test("confirmed admission stays terminal without changing chat or original", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); ChatStore store = f.store(); f.publish(store, f.ledger.beginAdmission(c.id));
                    f.ledger.reconcileDraft(c.id, store); require(!f.ledger.cancel(c.id), "confirmed receipt stays terminal");
                    phase(f.reopen(), c, CaptureAdmission.Phase.ADMITTED);
                    require(f.store().draft(CO, CV).attachments.size() == 1 && f.ledger.beginAdmission(c.id) == null, "caller owns explicit draft removal"); original(c, RED);
                }
            });
            test("explicit quiescent dismissal closes tracking without asserting publication", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id);
                    f.ledger.admissionUncertain(ticket); ChatStore store = f.store(); int before = store.messageCount(CO, CV);
                    require(f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        require(expected.company.equals(CO) && expected.conversation.equals(CV) && expected.attachmentId.equals(c.attachment), "barrier scoped exactly");
                        require(closure.run(), "quiescent explicit closure");
                    }), "tracking explicitly closed");
                    phase(f.reopen(), c, CaptureAdmission.Phase.DISMISSED);
                    require(!f.ledger.cancel(c.id) && f.ledger.beginAdmission(c.id) == null && f.ledger.claimHash(c.id) == null,
                            "dismissed receipt cannot restart");
                    require(f.store().draft(CO, CV).attachments.isEmpty() && f.store().messageCount(CO, CV) == before,
                            "dismissal makes no chat mutation or publication assertion"); original(c, RED);
                }
            });
            test("quiescent drain can finish publisher acknowledgement without deadlock", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    CountDownLatch start = new CountDownLatch(1);
                    Future<?> publisher = workers.submit(() -> {
                        start.await(); f.publish(store, ticket); f.ledger.reconcileDraft(c.id, store); return null;
                    });
                    boolean dismissed = f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        start.countDown();
                        try { publisher.get(10, java.util.concurrent.TimeUnit.SECONDS); }
                        catch (Exception error) { throw new IOException("Publisher failed to drain", error); }
                        require(!closure.run(), "confirmed receipt cannot become dismissed");
                    });
                    require(!dismissed, "concurrent confirmed publication wins"); phase(f.reopen(), c, CaptureAdmission.Phase.ADMITTED); original(c, RED);
                }
            });
            test("quiescent drain may retain a dispatched but unacknowledged draft", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    CountDownLatch start = new CountDownLatch(1);
                    Future<?> publisher = workers.submit(() -> { start.await(); f.publish(store, ticket); f.ledger.admissionUncertain(ticket); return null; });
                    require(f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        start.countDown();
                        try { publisher.get(10, java.util.concurrent.TimeUnit.SECONDS); }
                        catch (Exception error) { throw new IOException("Publisher failed to drain", error); }
                        closure.run();
                    }), "unknown-outcome tracking may close after drain");
                    phase(f.reopen(), c, CaptureAdmission.Phase.DISMISSED);
                    require(f.store().draft(CO, CV).attachments.size() == 1, "dismissal never deletes an already published draft"); original(c, RED);
                }
            });
            test("stale ledger closure cannot overwrite a newer terminal receipt", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id); final CaptureAdmission fresh = f.reopen();
                    throwsType(IOException.class, () -> f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        fresh.dismissUnresolved(c.id, (current, settled) -> settled.run());
                        closure.run();
                    }));
                    require(f.ledger.requiresReopen(), "stale closure is fenced by journal root identity");
                    phase(f.reopen(), c, CaptureAdmission.Phase.DISMISSED); original(c, RED);
                }
            });
            test("quiescence after a lost acknowledgement never permits READY or re-add", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); CaptureAdmission.AdmissionTicket ticket = f.ledger.beginAdmission(c.id); ChatStore store = f.store();
                    CountDownLatch start = new CountDownLatch(1);
                    Future<?> pending = workers.submit(() -> { start.await(); f.publish(store, ticket); return null; });
                    require(f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        start.countDown();
                        try { pending.get(10, java.util.concurrent.TimeUnit.SECONDS); }
                        catch (Exception error) { throw new IOException("Unacknowledged publisher did not drain", error); }
                        require(f.ledger.get(c.id).phase == CaptureAdmission.Phase.ADMITTING, "ACK is deliberately lost");
                        closure.run();
                    }), "explicit tracking closure only");
                    phase(f.reopen(), c, CaptureAdmission.Phase.DISMISSED);
                    require(f.ledger.beginAdmission(c.id) == null && f.store().draft(CO, CV).attachments.size() == 1,
                            "one published attachment and no replay capability"); original(c, RED);
                }
            });
            test("duplicate and escaped quiescent closures cannot create another write", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id);
                    final CaptureAdmission.QuiescentAction[] escaped = new CaptureAdmission.QuiescentAction[1];
                    require(f.ledger.dismissUnresolved(c.id, (expected, closure) -> {
                        escaped[0] = closure; closure.run();
                        try { throwsType(IllegalStateException.class, () -> closure.run()); }
                        catch (Exception error) { throw new IOException(error); }
                    }), "first synchronous closure succeeds");
                    byte[] root = Files.readAllBytes(f.journal);
                    throwsType(IllegalStateException.class, () -> escaped[0].run());
                    require(Arrays.equals(root, Files.readAllBytes(f.journal)), "escaped duplicate cannot mutate receipt");
                }
            });
            test("missing barrier execution is a failure and delayed closure stays invalid", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id);
                    final CaptureAdmission.QuiescentAction[] escaped = new CaptureAdmission.QuiescentAction[1];
                    throwsType(IOException.class, () -> f.ledger.dismissUnresolved(c.id, (expected, closure) -> escaped[0] = closure));
                    throwsType(IllegalStateException.class, () -> escaped[0].run());
                    phase(f.reopen(), c, CaptureAdmission.Phase.ADMITTING); original(c, RED);
                }
            });
            test("dismissal frees active capacity while retaining exact terminal identity", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); f.ledger.beginAdmission(c.id);
                    for (int i = 1; i < CaptureAdmission.MAX_ACTIVE_JOBS; i++) f.reserve();
                    throwsType(IOException.class, () -> f.reserve());
                    f.ledger.dismissUnresolved(c.id, (expected, closure) -> closure.run()); f.reserve();
                    CaptureAdmission reopened = f.reopen();
                    require(reopened.jobs().size() == CaptureAdmission.MAX_ACTIVE_JOBS + 1 && reopened.get(c.id).sha256.equals(sha(RED)), "retained receipt plus new active capacity");
                    phase(reopened, c, CaptureAdmission.Phase.DISMISSED); original(c, RED);
                }
            });
            test("independent captures cannot cancel or overwrite one another", () -> {
                try (Fixture f = new Fixture()) {
                    Capture a = f.ready(), b = f.ready(); f.ledger.cancel(a.id);
                    phase(f.ledger, a, CaptureAdmission.Phase.CANCELED); phase(f.ledger, b, CaptureAdmission.Phase.READY);
                    require(!f.ledger.get(a.id).attachmentId.equals(f.ledger.get(b.id).attachmentId), "distinct exact identities"); original(a, RED); original(b, RED);
                }
            });
            test("cancel and hash acknowledgement interleavings converge without resurrection", () -> {
                for (int i = 0; i < 12; i++) try (Fixture f = new Fixture()) {
                    Capture c = f.pending(); CaptureAdmission.DigestResult result = hash(f.ledger, f.ledger.claimHash(c.id));
                    CountDownLatch start = new CountDownLatch(1);
                    Future<Boolean> accept = workers.submit(() -> { start.await(); return f.ledger.acceptDigest(result); });
                    Future<Boolean> cancel = workers.submit(() -> { start.await(); return f.ledger.cancel(c.id); });
                    start.countDown(); accept.get(); require(cancel.get(), "cancel accepted");
                    phase(f.reopen(), c, CaptureAdmission.Phase.CANCELED); original(c, RED);
                }
            });
            test("journal is metadata-only with one bounded record per capture", () -> {
                try (Fixture f = new Fixture()) {
                    Capture c = f.ready(); java.util.Map<String, byte[]> records = new StoreJournal(f.journal.toFile()).read();
                    require(records.size() == 1 && records.containsKey("capture/" + c.id), "no chat payload keys");
                    require(records.values().iterator().next().length < 24 * 1024, "small bounded job record");
                    throwsType(UnsupportedOperationException.class, () -> f.ledger.jobs().clear());
                }
            });
            System.out.println("PASS: " + tests + " capture-admission cases (plus 12 cancellation interleavings)");
        } finally { workers.shutdownNow(); }
    }
}
