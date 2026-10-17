package com.baseer.freshchat.sync;

import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

/** Executes the production store against real temporary files and explicit JVM Android adapters. */
public final class ConnectedMediaStoreTest {
    private static final byte[] BYTES = "unchanged private original\n".getBytes(StandardCharsets.UTF_8);
    private static final Uri URI = Uri.parse("content://fixture/selected");
    private static final AccountScope ACCOUNT = new AccountScope("https://bchat.example", "qa", 7);
    private static final long NOW = 2_000_000_000_000L;
    private static int checks;
    interface Action { void run() throws Exception; }

    static final class Provider extends ContentResolver {
        final byte[] bytes;
        final CountDownLatch entered, release;
        final AtomicInteger opens = new AtomicInteger();
        Provider() { this(BYTES, null, null); }
        Provider(byte[] bytes, CountDownLatch entered, CountDownLatch release) {
            this.bytes = bytes; this.entered = entered; this.release = release;
        }
        public String getType(Uri uri) { return "image/jpeg"; }
        public Cursor query(Uri uri, String[] c, String s, String[] a, String sort) { return null; }
        public InputStream openInputStream(Uri uri) {
            opens.incrementAndGet();
            return new ByteArrayInputStream(bytes) {
                boolean waited;
                @Override public synchronized int read(byte[] target, int offset, int size) {
                    if (!waited && entered != null) {
                        waited = true; entered.countDown();
                        try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("Provider timed out"); }
                        catch (InterruptedException failure) { throw new AssertionError(failure); }
                    }
                    return super.read(target, offset, size);
                }
            };
        }
        public OutputStream openOutputStream(Uri uri, String mode) { throw new UnsupportedOperationException(); }
    }
    static final class App extends Context {
        final File root;
        App(File root) { this.root = root; }
        public File getFilesDir() { return root; }
        public ContentResolver getContentResolver() { return new Provider(); }
    }
    static final class Fixture implements AutoCloseable {
        final Path root = Files.createTempDirectory("bchat-connected-store-");
        final BChatConnectedMediaStore store = new BChatConnectedMediaStore(new App(root.toFile()));
        Fixture() throws IOException { }
        File scope(AccountScope account) throws IOException {
            Path path = root.resolve("bchat-v2-media").resolve(account.key);
            Files.createDirectories(path); return path.toFile();
        }
        File file(String uuid, String extension) throws IOException { return new File(scope(ACCOUNT), uuid + extension); }
        BChatConnectedMediaStore.Entry stage(long room) throws IOException { return stage(new Provider(), ACCOUNT, room, 2, room + 100); }
        BChatConnectedMediaStore.Entry stage(Provider provider, AccountScope account, long room,
                                             long company, long membership) throws IOException {
            return store.stage(provider, account, room, company, membership, URI, "", 0);
        }
        public void close() throws IOException {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
    static void check(boolean condition, String name) {
        if (!condition) throw new AssertionError(name);
        checks++; System.out.println("PASS " + name);
    }
    static void rejects(Action action, String name) throws Exception {
        try { action.run(); throw new AssertionError(name); }
        catch (IOException expected) { check(true, name); }
    }
    static BChatConnectedMediaStore.Problem problem(BChatConnectedMediaStore.Diagnostics diagnostics, String code) {
        for (BChatConnectedMediaStore.Problem problem : diagnostics.problems) if (code.equals(problem.code)) return problem;
        throw new AssertionError("Missing diagnostic " + code);
    }
    static long actualBytes(File folder) {
        long result = 0;
        for (File file : Objects.requireNonNull(folder.listFiles())) if (file.isFile()) result += file.length();
        return result;
    }
    static void corruptedRoomIsolation() throws Exception {
        try (Fixture f = new Fixture()) {
            BChatConnectedMediaStore.Entry damaged = f.stage(1), healthy = f.stage(2);
            File json = f.file(damaged.uploadUuid, ".json"), original = f.file(damaged.uploadUuid, ".bin");
            Files.write(json.toPath(), "not-json".getBytes(StandardCharsets.UTF_8));
            check(f.store.pending(ACCOUNT, 2, 102).clientUuid.equals(healthy.clientUuid), "Corrupt room A cannot poison pending room B");
            check(f.stage(3) != null, "Corrupt room A cannot prevent staging room C");
            BChatConnectedMediaStore.Problem issue = problem(f.store.diagnostics(ACCOUNT), "metadata_invalid");
            check(issue.uploadUuid.equals(damaged.uploadUuid) && issue.roomId == 0 && issue.companyId == 0,
                    "Unknown corrupt context is diagnostic only; never inferred authorization");
            check(original.isFile() && Arrays.equals(BYTES, Files.readAllBytes(original.toPath())) && json.isFile(),
                    "Corrupt metadata and original remain available for recovery");
        }
    }
    static void backupAndBounds() throws Exception {
        for (boolean legacy : new boolean[]{true, false}) {
            AtomicFile.legacy = legacy;
            try (Fixture f = new Fixture()) {
                BChatConnectedMediaStore.Entry entry = f.stage(1);
                File json = f.file(entry.uploadUuid, ".json"), backup = f.file(entry.uploadUuid, ".json.bak");
                Files.move(json.toPath(), backup.toPath());
                int calls = AtomicFile.opens;
                f.store.cleanupExpiredParts(ACCOUNT, NOW);
                BChatConnectedMediaStore.Entry restored = f.store.pending(ACCOUNT, 1, 101);
                check(restored.clientUuid.equals(entry.clientUuid) && json.isFile() && !backup.exists()
                        && AtomicFile.opens > calls, "Missing base recovers backup before cleanup, Atomic mode " + legacy);
                Files.write(f.file(entry.uploadUuid, ".json.new").toPath(), "partial".getBytes(StandardCharsets.UTF_8));
                check(f.store.diagnostics(ACCOUNT).requestCount == 1, "Atomic variants never count as duplicate requests " + legacy);
                byte[] oversized = new byte[24 * 1024 + 1]; Arrays.fill(oversized, (byte)'x');
                Files.write(json.toPath(), oversized);
                check(problem(f.store.diagnostics(ACCOUNT), "metadata_oversized").uploadUuid.equals(entry.uploadUuid)
                        && json.length() == oversized.length, "Oversized metadata is bounded, reported and preserved " + legacy);
            }
        }
        AtomicFile.legacy = false;
    }
    static void missingBytesAndScope() throws Exception {
        try (Fixture f = new Fixture()) {
            BChatConnectedMediaStore.Entry missing = f.stage(1), good = f.stage(2);
            Files.delete(f.file(missing.uploadUuid, ".bin").toPath());
            BChatConnectedMediaStore.Problem issue = problem(f.store.diagnostics(ACCOUNT), "media_missing");
            check(issue.roomId == 1 && issue.membershipId == 101 && issue.companyId == 2,
                    "Missing bytes retain only parsed, account-bound context");
            check(f.store.pending(ACCOUNT, 2, 102).uploadUuid.equals(good.uploadUuid), "Missing original in A leaves B usable");
            check(f.store.pending(ACCOUNT, 2, 999) == null, "Another membership never inherits a pending request");
            AccountScope other = new AccountScope("https://bchat.example", "qa", 8);
            check(f.store.diagnostics(other).problems.isEmpty() && f.store.pending(other, 2, 102) == null,
                    "Diagnostics and pending entries are isolated by verified account");
            rejects(() -> f.store.file(other, good), "Cross-account file lookup fails closed");
            f.store.purgeCompaniesNotIn(ACCOUNT, Collections.singleton(2L));
            check(f.store.pending(ACCOUNT, 1, 101) == null
                    && problem(f.store.diagnostics(ACCOUNT), "media_missing").uploadUuid.equals(missing.uploadUuid),
                    "Company review keeps damaged request diagnostic-only without granting file access");
            check(f.file(good.uploadUuid, ".bin").exists(), "Scope review does not silently delete unrelated originals");
            f.store.purgeAccount(ACCOUNT);
            check(f.store.diagnostics(ACCOUNT).requestCount == 0, "Explicit account revocation can retire broken private files");
        }
        try (Fixture f = new Fixture()) {
            BChatConnectedMediaStore.Entry denied = f.stage(1);
            BChatConnectedMediaStore.Entry allowed = f.stage(new Provider(), ACCOUNT, 2, 3, 102);
            BChatConnectedMediaStore.Entry unknown = f.stage(3);
            Files.write(f.file(unknown.uploadUuid, ".json").toPath(), new byte[]{'!'});
            f.store.purgeCompaniesNotIn(ACCOUNT, Collections.singleton(3L));
            check(!f.file(denied.uploadUuid, ".bin").exists()
                    && f.store.pending(ACCOUNT, 2, 102).uploadUuid.equals(allowed.uploadUuid),
                    "Verified company reduction removes only denied classified requests");
            check(f.file(unknown.uploadUuid, ".bin").isFile() && f.store.pending(ACCOUNT, 3, 103) == null,
                    "Unclassified corrupt original is retained without implicit authorization or whole-account deletion");
            rejects(() -> f.store.file(ACCOUNT, unknown), "Unclassified original cannot be exposed through file API");
        }
    }
    static void quotasAndCleanup() throws Exception {
        try (Fixture f = new Fixture()) {
            String orphanId = UUID.randomUUID().toString();
            File orphan = f.file(orphanId, ".bin");
            try (RandomAccessFile bytes = new RandomAccessFile(orphan, "rw")) { bytes.setLength(50L * 1024 * 1024); }
            Provider provider = new Provider();
            check(f.store.diagnostics(ACCOUNT).usedBytes == actualBytes(f.scope(ACCOUNT)), "Quota reports actual orphan bytes");
            rejects(() -> f.stage(provider, ACCOUNT, 1, 2, 101), "Unindexed original counts against 50 MiB before provider opens");
            check(provider.opens.get() == 0 && orphan.isFile(), "Over-budget refusal preserves original and avoids copying");
            f.store.cleanupExpiredParts(ACCOUNT, NOW);
            check(orphan.isFile(), "Housekeeping never removes an orphan original");
        }
        try (Fixture f = new Fixture()) {
            File old = f.file(UUID.randomUUID().toString(), ".part"), recent = f.file(UUID.randomUUID().toString(), ".part");
            Files.write(old.toPath(), BYTES); Files.write(recent.toPath(), BYTES);
            old.setLastModified(NOW - BChatConnectedMediaStore.INACTIVE_PART_RETENTION_MILLIS - 1);
            recent.setLastModified(NOW - 1000);
            check(f.store.diagnostics(ACCOUNT).usedBytes == BYTES.length * 2L, "Partial bytes count in actual budget");
            check(f.store.cleanupExpiredParts(ACCOUNT, NOW) == 1 && !old.exists() && recent.exists(),
                    "Only inactive partials older than 24 hours are removed");
        }
        try (Fixture f = new Fixture()) {
            for (int room = 1; room <= 20; room++) f.stage(room);
            check(f.store.diagnostics(ACCOUNT).requestCount == 20, "20th request commits without double counting its .part");
            rejects(() -> f.stage(21), "21st request respects existing request limit");
        }
    }
    static void activeCopyAndRevocation() throws Exception {
        for (boolean revoke : new boolean[]{false, true}) {
            try (Fixture f = new Fixture()) {
                CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
                ExecutorService workers = Executors.newFixedThreadPool(2);
                try {
                    Future<BChatConnectedMediaStore.Entry> staged = workers.submit(() ->
                            f.stage(new Provider(BYTES, entered, release), ACCOUNT, 1, 2, 101));
                    check(entered.await(3, TimeUnit.SECONDS), "Provider copy started " + revoke);
                    File part = Arrays.stream(Objects.requireNonNull(f.scope(ACCOUNT).listFiles()))
                            .filter(file -> file.getName().endsWith(".part")).findFirst().get();
                    part.setLastModified(NOW - 2 * BChatConnectedMediaStore.INACTIVE_PART_RETENTION_MILLIS);
                    Future<?> scan = workers.submit(() -> {
                        try {
                            if (revoke) f.store.purgeAccount(ACCOUNT);
                            else f.store.cleanupExpiredParts(ACCOUNT, NOW);
                        } catch (IOException failure) { throw new RuntimeException(failure); }
                    });
                    scan.get(2, TimeUnit.SECONDS);
                    check(part.exists(), "Cleanup/revocation never deletes an active provider file " + revoke);
                    release.countDown();
                    if (revoke) {
                        try { staged.get(3, TimeUnit.SECONDS); throw new AssertionError("Revoked stage committed"); }
                        catch (ExecutionException expected) { check(expected.getCause() instanceof IOException,
                                "Revocation generation prevents late stage commit"); }
                        check(f.store.diagnostics(ACCOUNT).requestCount == 0, "Revoked active copy retires its own files after release");
                    } else {
                        BChatConnectedMediaStore.Entry entry = staged.get(3, TimeUnit.SECONDS);
                        check(Arrays.equals(BYTES, Files.readAllBytes(f.store.file(ACCOUNT, entry).toPath())),
                                "Concurrent scan avoids monitor deadlock and preserves original bytes");
                    }
                } finally { release.countDown(); workers.shutdownNow(); workers.awaitTermination(3, TimeUnit.SECONDS); }
            }
        }
    }
    static void concurrentReceiptAndScan() throws Exception {
        try (Fixture f = new Fixture()) {
            BChatConnectedMediaStore.Entry entry = f.stage(1);
            BChatConnectedMediaStore second = new BChatConnectedMediaStore(new App(f.root.toFile()));
            ExecutorService workers = Executors.newFixedThreadPool(2);
            try {
                Future<?> write = workers.submit(() -> {
                    try { for (int i = 0; i < 80; i++) f.store.markUploaded(ACCOUNT, entry, 55); }
                    catch (IOException failure) { throw new RuntimeException(failure); }
                });
                Future<?> read = workers.submit(() -> {
                    try { for (int i = 0; i < 80; i++) {
                        if (second.pending(ACCOUNT, 1, 101) == null || !second.diagnostics(ACCOUNT).problems.isEmpty())
                            throw new AssertionError("Atomic write exposed incomplete record");
                    } } catch (IOException failure) { throw new RuntimeException(failure); }
                });
                write.get(5, TimeUnit.SECONDS); read.get(5, TimeUnit.SECONDS);
                BChatConnectedMediaStore.Entry uploaded = second.pending(ACCOUNT, 1, 101);
                check(uploaded.mediaId == 55 && uploaded.clientUuid.equals(entry.clientUuid),
                        "Cross-helper receipt/scan serialization retains request identity");
                second.acknowledge(ACCOUNT, uploaded);
                check(f.store.diagnostics(ACCOUNT).requestCount == 0, "Only exact verified acknowledgement retires request");
            } finally { workers.shutdownNow(); workers.awaitTermination(3, TimeUnit.SECONDS); }
        }
    }
    static void boundedDiagnostics() throws Exception {
        try (Fixture f = new Fixture()) {
            for (int i = 0; i < 105; i++) Files.write(f.file(UUID.randomUUID().toString(), ".bin").toPath(), new byte[]{1});
            BChatConnectedMediaStore.Diagnostics diagnostics = f.store.diagnostics(ACCOUNT);
            check(diagnostics.problems.size() == 100 && diagnostics.totalProblemCount == 105
                    && diagnostics.truncated && diagnostics.usedBytes == 105,
                    "Diagnostics are bounded with explicit total/truncation; bytes still fully counted");
            try { diagnostics.problems.clear(); throw new AssertionError("Mutable diagnostics"); }
            catch (UnsupportedOperationException expected) { check(true, "Diagnostic snapshot is immutable"); }
        }
    }
    public static void main(String[] args) throws Exception {
        corruptedRoomIsolation(); backupAndBounds(); missingBytesAndScope(); quotasAndCleanup();
        activeCopyAndRevocation(); concurrentReceiptAndScan(); boundedDiagnostics();
        System.out.println("PASS " + checks + " production-store JVM checks; Android/device NOT executed");
    }
}
