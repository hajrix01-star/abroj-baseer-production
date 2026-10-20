package com.baseer.bwork.legacy;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileDescriptor;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.channels.Channels;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.DigestInputStream;
import java.security.DigestOutputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * Checked append-only local records. The small BCH4 root is the only commit point.
 * Segments and recovery archives are never removed, scanned, or rewritten here.
 * SHA-256 detects accidental changes; it is not encryption or authentication.
 * All cooperating readers/writers use a stable OS file lock. Each instance also
 * pins the exact root bytes seen at construction, rejecting stale writes.
 * A successful read validates the complete immutable chain. Later appends on
 * that open instance trust those immutable segments while rechecking the root
 * identity, avoiding history-sized I/O for each local message. Every read and
 * every constructor-only instance's first append validates the full chain again.
 *
 * Legacy ObjectStream roots are only identified and hashed here, never decoded.
 * Their first commit MUST contain the complete already-validated legacy state.
 */
public final class StoreJournal {
    public static final int VERSION = 4;
    public static final int MAX_VALUE_BYTES = 1024 * 1024;
    public static final int MAX_KEY_BYTES = 4096;
    public static final int MAX_RECORDS_PER_SEGMENT = 4096;
    public static final long MAX_SEGMENT_BYTES = 16L * 1024L * 1024L;
    private static final int ROOT_MAGIC = 0x42434834; // BCH4
    private static final int SEGMENT_MAGIC = 0x42435334; // BCS4
    private static final int LEGACY_MAGIC = 0xaced0005;
    private static final int HASH_BYTES = 32;
    private static final int MAX_ROOT_BYTES = 256;
    private static final int MAX_NAME_BYTES = 64;
    private static final byte[] ZERO_HASH = new byte[HASH_BYTES];
    // Avoid OverlappingFileLockException for cooperating callers in one JVM.
    private static final Object PROCESS_LOCK = new Object();
    private final File root;
    private byte[] expectedRootHash;
    private boolean uncertain;
    // Valid only for expectedRootHash; instance operations are serialized, including
    // outcome handling after the OS file lock is released.
    private boolean validatedChain;

    /** Immutable transaction entry. A null value is a deletion. */
    public static final class Record {
        public final String key;
        private final byte[] keyBytes;
        private final byte[] bytes;
        public Record(String key, byte[] value) {
            if (key == null || key.length() == 0 || key.length() > MAX_KEY_BYTES)
                throw new IllegalArgumentException("Invalid journal key");
            try { keyBytes = utf8(key); }
            catch (CharacterCodingException bad) { throw new IllegalArgumentException("Invalid UTF-8 key", bad); }
            if (keyBytes.length == 0 || keyBytes.length > MAX_KEY_BYTES)
                throw new IllegalArgumentException("Journal key is too long");
            if (value != null && value.length > MAX_VALUE_BYTES)
                throw new IllegalArgumentException("Journal value exceeds 1 MiB");
            this.key = key;
            this.bytes = value == null ? null : value.clone();
        }
        public byte[] value() { return bytes == null ? null : bytes.clone(); }
        private long encodedSize() { return 8L + keyBytes.length + (bytes == null ? 0 : bytes.length); }
    }

    /** Metadata describes a checked root; available does not deserialize legacy data. */
    public static final class Metadata {
        public final boolean available;
        public final boolean journal;
        public final boolean legacy;
        public final long savedAt;
        public final long generation;
        /** Exact root-byte SHA-256; null when the root is absent. */
        public final String rootHash;
        private Metadata(Snapshot snapshot, Root manifest) {
            available = snapshot.hash != null;
            journal = snapshot.magic == ROOT_MAGIC;
            legacy = snapshot.magic == LEGACY_MAGIC;
            savedAt = manifest == null ? snapshot.modifiedAt : manifest.savedAt;
            generation = manifest == null ? 0 : manifest.generation;
            rootHash = snapshot.hash == null ? null : hex(snapshot.hash);
        }
    }

    /** Root was replaced, but durability could not be confirmed. Reopen before use. */
    public static final class CommitUncertainException extends IOException {
        private static final long serialVersionUID = 1L;
        CommitUncertainException(IOException cause) {
            super("Journal root was replaced, but directory sync failed; reopen storage before continuing", cause);
        }
    }

    public StoreJournal(File root) throws IOException {
        this.root = normalize(root);
        expectedRootHash = locked(this.root, new IOCall<byte[]>() {
            public byte[] run() throws IOException {
                Snapshot snapshot = snapshot(StoreJournal.this.root);
                requireRecognized(snapshot);
                if (snapshot.hash == null && Files.exists(lastGoodFile(StoreJournal.this.root).toPath(), LinkOption.NOFOLLOW_LINKS))
                    throw new IOException("Journal root is missing; explicit recovery is required");
                return snapshot.hash;
            }
        });
    }

    public static boolean isJournal(File file) throws IOException {
        File target = normalize(file);
        if (!Files.exists(target.toPath(), LinkOption.NOFOLLOW_LINKS)) return false;
        requireRegular(target);
        try (DataInputStream in = new DataInputStream(new FileInputStream(target))) {
            try { return in.readInt() == ROOT_MAGIC; }
            catch (EOFException shortFile) { return false; }
        }
    }

    /** Return state in stable insertion order. Replacements keep their position. */
    public synchronized Map<String, byte[]> read() throws IOException {
        try {
        return locked(root, new IOCall<Map<String, byte[]>>() {
            public Map<String, byte[]> run() throws IOException {
                validatedChain = false;
                checkExpected(snapshot(root));
                Map<String, byte[]> state = readState(root);
                validatedChain = true;
                return state;
            }
        });
        } catch (IOException failure) {
            validatedChain = false;
            throw failure;
        }
    }

    /** Read a specific manifest, including a .last-good root, without fallback. */
    public static Map<String, byte[]> readFile(File specificRoot) throws IOException {
        final File target = normalize(specificRoot);
        return locked(lockOwner(target), new IOCall<Map<String, byte[]>>() {
            public Map<String, byte[]> run() throws IOException { return readState(target); }
        });
    }

    public static File lastGoodFile(File root) { return new File(root.getPath() + ".last-good"); }

    public static Map<String, byte[]> readLastGood(File root) throws IOException {
        final File original = normalize(root);
        return locked(original, new IOCall<Map<String, byte[]>>() {
            public Map<String, byte[]> run() throws IOException {
                File backup = lastGoodFile(original);
                requireRegular(backup);
                return readState(backup);
            }
        });
    }

    /** Checks the entire referenced chain, without retaining record values. */
    public static Metadata inspect(File root) throws IOException {
        final File target = normalize(root);
        return locked(lockOwner(target), new IOCall<Metadata>() {
            public Metadata run() throws IOException {
                Snapshot snapshot = snapshot(target);
                requireRecognized(snapshot);
                Root manifest = snapshot.magic == ROOT_MAGIC ? readRoot(target) : null;
                if (manifest != null) chain(target.getParentFile(), manifest);
                return new Metadata(snapshot, manifest);
            }
        });
    }

    /** Atomic commit. Large deltas are streamed into multiple bounded segments. */
    public synchronized void commit(List<Record> delta) throws IOException {
        if (delta == null) throw new IllegalArgumentException("Missing journal delta");
        final List<Record> records = new ArrayList<Record>(delta);
        for (Record record : records) if (record == null) throw new IllegalArgumentException("Null journal record");
        final boolean[] rootReplaced = new boolean[1];
        try {
            locked(root, new IOCall<Void>() {
            public Void run() throws IOException {
                Snapshot before = snapshot(root);
                checkExpected(before);
                requireRecognized(before);
                Root prior = before.magic == ROOT_MAGIC ? readRoot(root) : null;
                if (prior != null) {
                    if (!validatedChain) {
                        chain(root.getParentFile(), prior);
                        validatedChain = true;
                    }
                    if (records.isEmpty()) return null;
                    if (prior.generation == Long.MAX_VALUE) throw new IOException("Journal generation exhausted");
                }
                long generation = prior == null ? 1 : prior.generation + 1;
                String previousName = prior == null ? "" : prior.segment;
                byte[] previousHash = prior == null ? ZERO_HASH : prior.segmentHash;
                int offset = 0;
                do {
                    int end = offset;
                    long size = 256; // Conservative bounded header/footer reserve.
                    while (end < records.size() && end - offset < MAX_RECORDS_PER_SEGMENT
                            && size + records.get(end).encodedSize() <= MAX_SEGMENT_BYTES) {
                        size += records.get(end).encodedSize();
                        end++;
                    }
                    String name = "bch4-" + UUID.randomUUID().toString() + ".segment";
                    Segment next = writeSegment(new File(root.getParentFile(), name), generation,
                            previousName, previousHash, records, offset, end);
                    previousName = name;
                    previousHash = next.hash;
                    offset = end;
                } while (offset < records.size());
                // Ensure newly referenced immutable names are durable before root publication.
                syncDirectory(root.getParentFile());
                byte[] nextRoot = encodeRoot(new Root(generation, System.currentTimeMillis(), previousName, previousHash));
                File stagedRoot = uniqueSibling(root, ".staged-");
                writeBytes(stagedRoot, nextRoot);
                if (before.hash != null) {
                    // Archive exact original bytes before .last-good or the live root can change.
                    archive(root, before);
                    File backup = lastGoodFile(root);
                    Snapshot oldBackup = snapshot(backup);
                    if (oldBackup.hash != null) archive(backup, oldBackup);
                    File stagedBackup = uniqueSibling(root, ".backup-staged-");
                    copyChecked(root, stagedBackup, before.hash);
                    atomicReplace(stagedBackup, backup);
                    syncDirectory(root.getParentFile());
                }
                checkExpected(snapshot(root));
                atomicReplace(stagedRoot, root); // Sole commit point.
                rootReplaced[0] = true;
                expectedRootHash = sha256(nextRoot);
                try { syncDirectory(root.getParentFile()); }
                catch (IOException durabilityFailure) {
                    uncertain = true;
                    throw new CommitUncertainException(durabilityFailure);
                }
                validatedChain = true;
                return null;
            }
        });
        } catch (IOException failure) {
            // A lock/channel close can also fail after the root was committed.
            if (rootReplaced[0]) {
                uncertain = true;
                validatedChain = false;
                if (failure instanceof CommitUncertainException) throw failure;
                throw new CommitUncertainException(failure);
            }
            throw failure;
        }
    }

    /** Explicitly restore the checked backup, retaining the displaced root and backup. */
    public static void recover(File root) throws IOException { recover(root, null, false); }

    /** Recovery with stale-preview protection; null expectedHash means an absent live root. */
    public static void recover(File root, String expectedHash) throws IOException { recover(root, expectedHash, true); }

    private static void recover(File file, final String expectedHash, final boolean enforceExpected) throws IOException {
        final File root = normalize(file);
        final boolean[] rootReplaced = new boolean[1];
        try {
        locked(root, new IOCall<Void>() {
            public Void run() throws IOException {
                Snapshot before = snapshot(root);
                String actual = before.hash == null ? null : hex(before.hash);
                if (enforceExpected && !(actual == null ? expectedHash == null : actual.equals(expectedHash)))
                    throw new IOException("Storage changed after recovery preview; reopen before recovering");
                File backup = lastGoodFile(root);
                Snapshot saved = snapshot(backup);
                requireRecognized(saved);
                if (saved.hash == null) throw new IOException("No last-good root is available");
                if (saved.magic == ROOT_MAGIC) chain(root.getParentFile(), readRoot(backup));
                // Legacy validation belongs to the domain reader, never ObjectInputStream here.
                if (before.hash != null) archive(root, before);
                File staged = uniqueSibling(root, ".recovery-staged-");
                copyChecked(backup, staged, saved.hash);
                syncDirectory(root.getParentFile());
                atomicReplace(staged, root);
                rootReplaced[0] = true;
                try { syncDirectory(root.getParentFile()); }
                catch (IOException durabilityFailure) { throw new CommitUncertainException(durabilityFailure); }
                return null;
            }
        });
        } catch (IOException failure) {
            if (rootReplaced[0] && !(failure instanceof CommitUncertainException)) throw new CommitUncertainException(failure);
            throw failure;
        }
    }

    private void checkExpected(Snapshot current) throws IOException {
        if (uncertain) throw new IOException("Journal commit outcome requires reopening storage");
        if (!Arrays.equals(expectedRootHash, current.hash))
            throw new IOException("Storage changed; reopen before writing or reading this instance");
    }

    private static Map<String, byte[]> readState(File file) throws IOException {
        Snapshot snapshot = snapshot(file);
        requireRecognized(snapshot);
        LinkedHashMap<String, byte[]> state = new LinkedHashMap<String, byte[]>();
        if (snapshot.hash == null) return state;
        if (snapshot.magic != ROOT_MAGIC) throw new IOException("Legacy snapshot requires the domain legacy reader");
        List<Segment> segments = chain(file.getParentFile(), readRoot(file));
        Collections.reverse(segments);
        for (Segment segment : segments) readSegment(segment.file, segment.hash, state);
        return state;
    }

    private static List<Segment> chain(File directory, Root root) throws IOException {
        ArrayList<Segment> segments = new ArrayList<Segment>();
        Set<String> seen = new HashSet<String>();
        String name = root.segment;
        byte[] hash = root.segmentHash;
        long generation = root.generation;
        while (!name.isEmpty()) {
            if (!seen.add(name)) throw new IOException("Journal chain contains a repeated segment");
            Segment segment = readSegment(new File(directory, name), hash, null);
            if (segment.generation > generation || segment.generation < 1
                    || (segments.isEmpty() && segment.generation != root.generation))
                throw new IOException("Journal generation mismatch");
            segments.add(segment);
            generation = segment.generation;
            name = segment.previousName;
            hash = segment.previousHash;
        }
        return segments;
    }

    private static Segment readSegment(File file, byte[] expectedHash, Map<String, byte[]> state) throws IOException {
        requireRegular(file);
        long length = Files.size(file.toPath());
        if (length < 88 || length > MAX_SEGMENT_BYTES) throw new IOException("Invalid journal segment size");
        MessageDigest digest = digest();
        try (InputStream raw = new BufferedInputStream(new FileInputStream(file))) {
            BoundedInputStream body = new BoundedInputStream(raw, length - HASH_BYTES);
            DataInputStream in = new DataInputStream(new DigestInputStream(body, digest));
            if (in.readInt() != SEGMENT_MAGIC || in.readInt() != VERSION) throw new IOException("Unsupported journal segment");
            long generation = in.readLong();
            String previous = readName(in, body, true);
            byte[] previousHash = new byte[HASH_BYTES];
            in.readFully(previousHash);
            if (previous.isEmpty() != Arrays.equals(previousHash, ZERO_HASH)) throw new IOException("Invalid journal predecessor");
            int count = in.readInt();
            if (count < 0 || count > MAX_RECORDS_PER_SEGMENT || count > body.remaining / 9L)
                throw new IOException("Invalid journal record count");
            byte[] skip = state == null ? new byte[8192] : null;
            for (int i = 0; i < count; i++) {
                int keyLength = in.readInt();
                if (keyLength < 1 || keyLength > MAX_KEY_BYTES || keyLength > body.remaining - 4)
                    throw new IOException("Invalid journal key length");
                byte[] keyBytes = new byte[keyLength];
                in.readFully(keyBytes);
                String key = decodeUtf8(keyBytes);
                int valueLength = in.readInt();
                if (valueLength < -1 || valueLength > MAX_VALUE_BYTES || valueLength > body.remaining)
                    throw new IOException("Invalid journal value length");
                if (valueLength == -1) { if (state != null) state.remove(key); }
                else if (state != null) {
                    byte[] value = new byte[valueLength];
                    in.readFully(value);
                    state.put(key, value);
                } else {
                    int remaining = valueLength;
                    while (remaining > 0) { int n = Math.min(remaining, skip.length); in.readFully(skip, 0, n); remaining -= n; }
                }
            }
            if (in.read() != -1) throw new IOException("Unexpected journal segment bytes");
            byte[] actual = digest.digest();
            byte[] stored = new byte[HASH_BYTES];
            new DataInputStream(raw).readFully(stored);
            if (raw.read() != -1 || !MessageDigest.isEqual(actual, stored) || !MessageDigest.isEqual(actual, expectedHash))
                throw new IOException("Journal segment checksum mismatch");
            return new Segment(file, generation, previous, previousHash, actual);
        }
    }

    private static Segment writeSegment(File file, long generation, String previous, byte[] previousHash,
                                        List<Record> records, int start, int end) throws IOException {
        MessageDigest digest = digest();
        try (FileChannel channel = FileChannel.open(file.toPath(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            BufferedOutputStream raw = new BufferedOutputStream(Channels.newOutputStream(channel));
            DigestOutputStream checked = new DigestOutputStream(raw, digest);
            DataOutputStream out = new DataOutputStream(checked);
            out.writeInt(SEGMENT_MAGIC);
            out.writeInt(VERSION);
            out.writeLong(generation);
            writeName(out, previous);
            out.write(previousHash);
            out.writeInt(end - start);
            for (int i = start; i < end; i++) {
                Record record = records.get(i);
                out.writeInt(record.keyBytes.length);
                out.write(record.keyBytes);
                out.writeInt(record.bytes == null ? -1 : record.bytes.length);
                if (record.bytes != null) out.write(record.bytes);
            }
            out.flush();
            byte[] hash = digest.digest();
            raw.write(hash);
            raw.flush();
            channel.force(true);
            return new Segment(file, generation, previous, previousHash.clone(), hash);
        }
    }

    private static Root readRoot(File file) throws IOException {
        requireRegular(file);
        long size = Files.size(file.toPath());
        if (size < 4 + 4 + 8 + 8 + 4 + 1 + 32 + 32 || size > MAX_ROOT_BYTES)
            throw new IOException("Invalid BCH4 root size");
        byte[] bytes = new byte[(int) size];
        try (DataInputStream input = new DataInputStream(new FileInputStream(file))) {
            input.readFully(bytes);
            if (input.read() != -1) throw new IOException("Root changed while reading");
        }
        int bodyLength = bytes.length - HASH_BYTES;
        byte[] actual = digest().digest(Arrays.copyOf(bytes, bodyLength));
        if (!MessageDigest.isEqual(actual, Arrays.copyOfRange(bytes, bodyLength, bytes.length)))
            throw new IOException("BCH4 root checksum mismatch");
        BoundedInputStream body = new BoundedInputStream(new ByteArrayInputStream(bytes, 0, bodyLength), bodyLength);
        DataInputStream in = new DataInputStream(body);
        if (in.readInt() != ROOT_MAGIC || in.readInt() != VERSION) throw new IOException("Unsupported journal root");
        long generation = in.readLong();
        long savedAt = in.readLong();
        if (generation < 1 || savedAt < 0) throw new IOException("Invalid journal root metadata");
        String segment = readName(in, body, false);
        byte[] hash = new byte[HASH_BYTES];
        in.readFully(hash);
        if (in.read() != -1) throw new IOException("Unexpected journal root bytes");
        return new Root(generation, savedAt, segment, hash);
    }

    private static byte[] encodeRoot(Root root) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream(MAX_ROOT_BYTES);
        DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(ROOT_MAGIC); out.writeInt(VERSION);
        out.writeLong(root.generation); out.writeLong(root.savedAt);
        writeName(out, root.segment); out.write(root.segmentHash); out.flush();
        byte[] hash = sha256(bytes.toByteArray());
        out.write(hash); out.flush();
        return bytes.toByteArray();
    }

    private static String readName(DataInputStream in, BoundedInputStream body, boolean emptyAllowed) throws IOException {
        int size = in.readInt();
        if (size < 0 || size > MAX_NAME_BYTES || size > body.remaining || (!emptyAllowed && size == 0))
            throw new IOException("Invalid segment name length");
        byte[] bytes = new byte[size]; in.readFully(bytes);
        String name = decodeUtf8(bytes);
        if (!(emptyAllowed && name.isEmpty()) && !name.matches("bch4-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\\.segment"))
            throw new IOException("Invalid segment name");
        return name;
    }
    private static void writeName(DataOutputStream out, String name) throws IOException {
        byte[] bytes = name.getBytes(StandardCharsets.UTF_8); out.writeInt(bytes.length); out.write(bytes);
    }

    private static Snapshot snapshot(File file) throws IOException {
        if (!Files.exists(file.toPath(), LinkOption.NOFOLLOW_LINKS)) return new Snapshot(null, 0, 0);
        requireRegular(file);
        MessageDigest digest = digest();
        int magic = 0;
        int prefix = 0;
        try (InputStream in = new BufferedInputStream(new FileInputStream(file))) {
            byte[] buffer = new byte[8192];
            int n;
            while ((n = in.read(buffer)) != -1) {
                digest.update(buffer, 0, n);
                for (int i = 0; prefix < 4 && i < n; i++, prefix++) magic = (magic << 8) | (buffer[i] & 255);
            }
        }
        return new Snapshot(digest.digest(), prefix == 4 ? magic : 0, file.lastModified());
    }
    private static void requireRecognized(Snapshot snapshot) throws IOException {
        if (snapshot.hash != null && snapshot.magic != ROOT_MAGIC && snapshot.magic != LEGACY_MAGIC)
            throw new IOException("Unrecognized local storage; preserve it and recover explicitly");
    }
    private static void archive(File source, Snapshot snapshot) throws IOException {
        String kind = snapshot.magic == LEGACY_MAGIC ? ".legacy-" : ".preserved-";
        File archive = new File(source.getParentFile(), source.getName() + kind + hex(snapshot.hash));
        if (Files.exists(archive.toPath(), LinkOption.NOFOLLOW_LINKS)) {
            if (!Arrays.equals(snapshot(archive).hash, snapshot.hash)) throw new IOException("Preserved root archive does not match");
            return;
        }
        File staged = uniqueSibling(source, ".archive-staged-");
        copyChecked(source, staged, snapshot.hash);
        atomicReplace(staged, archive);
        syncDirectory(source.getParentFile());
    }
    private static void copyChecked(File source, File target, byte[] expectedHash) throws IOException {
        MessageDigest digest = digest();
        try (InputStream in = new BufferedInputStream(new FileInputStream(source));
             FileChannel out = FileChannel.open(target.toPath(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            byte[] bytes = new byte[8192]; int n;
            while ((n = in.read(bytes)) != -1) {
                digest.update(bytes, 0, n);
                ByteBuffer buffer = ByteBuffer.wrap(bytes, 0, n);
                while (buffer.hasRemaining()) out.write(buffer);
            }
            if (!MessageDigest.isEqual(digest.digest(), expectedHash)) throw new IOException("Storage changed during preservation");
            out.force(true);
        }
    }
    private static void writeBytes(File file, byte[] bytes) throws IOException {
        try (FileChannel out = FileChannel.open(file.toPath(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
            ByteBuffer buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) out.write(buffer);
            out.force(true);
        }
    }
    private static void atomicReplace(File source, File target) throws IOException {
        // No non-atomic fallback. Unsupported filesystems must fail closed.
        Files.move(source.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
    }
    private static void syncDirectory(File directory) throws IOException {
        if (!Files.isDirectory(directory.toPath(), LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Storage sync target is not a directory");
        final String vmName;
        try { vmName = System.getProperty("java.vm.name"); }
        catch (SecurityException denied) { throw new IOException("Cannot identify the storage runtime", denied); }
        // Android documents Dalvik as its VM name, including the ART runtime.
        // Mere class presence is insufficient: host tests can include android.jar stubs.
        if (!"Dalvik".equals(vmName)) {
            try (FileChannel channel = FileChannel.open(directory.toPath(), StandardOpenOption.READ)) { channel.force(true); }
            return;
        }
        final Class<?> os;
        try { os = Class.forName("android.system.Os"); }
        catch (ClassNotFoundException unavailable) { throw new IOException("Android directory sync API is unavailable", unavailable); }
        // Use only public Android API 21+ constants/methods. The directory was
        // checked above; O_RDONLY opens its fd without the non-SDK O_DIRECTORY.
        // Do not silently downgrade a failed fsync to best-effort durability.
        FileDescriptor descriptor = null;
        IOException failure = null;
        try {
            Class<?> constants = Class.forName("android.system.OsConstants");
            int flags = constants.getField("O_RDONLY").getInt(null);
            descriptor = (FileDescriptor) os.getMethod("open", String.class, int.class, int.class)
                    .invoke(null, directory.getAbsolutePath(), flags, 0);
            os.getMethod("fsync", FileDescriptor.class).invoke(null, descriptor);
        } catch (ReflectiveOperationException error) {
            failure = new IOException("Android directory fsync failed", reflectionCause(error));
        } finally {
            if (descriptor != null) {
                try { os.getMethod("close", FileDescriptor.class).invoke(null, descriptor); }
                catch (ReflectiveOperationException error) {
                    IOException closeFailure = new IOException("Android directory close failed", reflectionCause(error));
                    if (failure == null) failure = closeFailure; else failure.addSuppressed(closeFailure);
                }
            }
        }
        if (failure != null) throw failure;
    }
    private static Throwable reflectionCause(ReflectiveOperationException error) {
        return error instanceof java.lang.reflect.InvocationTargetException && error.getCause() != null ? error.getCause() : error;
    }
    private static File uniqueSibling(File root, String marker) {
        return new File(root.getParentFile(), root.getName() + marker + UUID.randomUUID().toString());
    }
    private static File normalize(File file) throws IOException {
        if (file == null) throw new IllegalArgumentException("Missing journal root");
        // Canonicalize the parent but do not follow a root-file symlink.
        File absolute = file.getAbsoluteFile();
        File parent = absolute.getParentFile();
        if (parent == null) throw new IOException("Storage requires a parent directory");
        return new File(parent.getCanonicalFile(), absolute.getName());
    }
    private static File lockOwner(File file) {
        String path = file.getPath();
        return path.endsWith(".last-good") ? new File(path.substring(0, path.length() - ".last-good".length())) : file;
    }
    private static void requireRegular(File file) throws IOException {
        if (!Files.isRegularFile(file.toPath(), LinkOption.NOFOLLOW_LINKS)) throw new IOException("Storage file is missing or is not regular: " + file.getName());
    }
    private interface IOCall<T> { T run() throws IOException; }
    private static <T> T locked(File root, IOCall<T> call) throws IOException {
        synchronized (PROCESS_LOCK) {
            File parent = root.getParentFile();
            if (!parent.isDirectory()) throw new IOException("Storage directory is unavailable");
            File lockFile = new File(root.getPath() + ".lock");
            if (Files.exists(lockFile.toPath(), LinkOption.NOFOLLOW_LINKS)) requireRegular(lockFile);
            try (RandomAccessFile lock = new RandomAccessFile(lockFile, "rw");
                 FileLock held = lock.getChannel().lock()) {
                if (!held.isValid()) throw new IOException("Storage lock is unavailable");
                return call.run();
            }
        }
    }
    private static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static byte[] sha256(byte[] bytes) { return digest().digest(bytes); }
    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) out.append(Character.forDigit((b >>> 4) & 15, 16)).append(Character.forDigit(b & 15, 16));
        return out.toString();
    }
    private static byte[] utf8(String text) throws CharacterCodingException {
        ByteBuffer encoded = StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).encode(java.nio.CharBuffer.wrap(text));
        byte[] bytes = new byte[encoded.remaining()]; encoded.get(bytes); return bytes;
    }
    private static String decodeUtf8(byte[] bytes) throws IOException {
        try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch (CharacterCodingException bad) { throw new IOException("Invalid journal UTF-8", bad); }
    }
    private static final class Snapshot {
        final byte[] hash; final int magic; final long modifiedAt;
        Snapshot(byte[] hash, int magic, long modifiedAt) { this.hash = hash; this.magic = magic; this.modifiedAt = modifiedAt; }
    }
    private static final class Root {
        final long generation; final long savedAt; final String segment; final byte[] segmentHash;
        Root(long generation, long savedAt, String segment, byte[] hash) {
            this.generation = generation; this.savedAt = savedAt; this.segment = segment; this.segmentHash = hash;
        }
    }
    private static final class Segment {
        final File file; final long generation; final String previousName; final byte[] previousHash; final byte[] hash;
        Segment(File file, long generation, String previousName, byte[] previousHash, byte[] hash) {
            this.file = file; this.generation = generation; this.previousName = previousName; this.previousHash = previousHash; this.hash = hash;
        }
    }
    private static final class BoundedInputStream extends InputStream {
        final InputStream input; long remaining;
        BoundedInputStream(InputStream input, long remaining) { this.input = input; this.remaining = remaining; }
        public int read() throws IOException {
            if (remaining == 0) return -1;
            int value = input.read(); if (value < 0) throw new EOFException("Incomplete journal body"); remaining--; return value;
        }
        public int read(byte[] bytes, int offset, int length) throws IOException {
            if (length == 0) return 0;
            if (remaining == 0) return -1;
            int count = input.read(bytes, offset, (int) Math.min((long) length, remaining));
            if (count < 0) throw new EOFException("Incomplete journal body"); remaining -= count; return count;
        }
    }
}
