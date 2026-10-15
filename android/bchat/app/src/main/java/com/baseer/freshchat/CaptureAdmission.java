package com.baseer.freshchat;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.HashSet;
import java.util.Set;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

/**
 * Inactive integration candidate: durable receipts for newly-created captures only.
 * No chat data, UI, sending, file deletion, discovery, or retrospective enrollment.
 * All methods that touch the journal or source are blocking: invoke them off-main.
 * An admission attempt must be serialized with that destination's editor/store
 * writes, removal and sending by the integrating process-owned coordinator.
 */
public final class CaptureAdmission {
    public static final long MAX_CAPTURE_BYTES = 25L * 1024L * 1024L;
    public static final int MAX_ACTIVE_JOBS = 32;
    private static final int FORMAT = 1;
    private static final String PREFIX = "capture/";
    public enum Kind { PHOTO, VOICE }
    public enum Phase { RESERVED, PENDING, HASHING, RETRY, READY, ADMITTING, UNCERTAIN, ADMITTED, CANCELED, DISMISSED }
    public enum Failure { NONE, SOURCE_UNAVAILABLE, SOURCE_CHANGED, IO_RETRY }
    public enum Observation { CONFIRMED, NOT_FOUND, CONFLICT }

    /** Immutable job metadata. Terminal receipts are retained; no retention policy is imposed. */
    public static final class Job {
        public final String captureId, attachmentId, company, conversation, path, name, mime;
        public final Kind kind;
        public final Phase phase;
        public final long size, modifiedMillis, generation;
        public final String sha256;
        public final Failure failure;
        private final String workerOwner, token;
        private Job(String captureId, String attachmentId, String company, String conversation,
                    String path, String name, String mime, Kind kind, Phase phase, long size,
                    long modifiedMillis, long generation, String sha256, Failure failure,
                    String workerOwner, String token) {
            this.captureId = uuid(captureId); this.attachmentId = uuid(attachmentId);
            this.company = bounded(company, 1024); this.conversation = bounded(conversation, 1024);
            this.path = bounded(path, 4096); this.name = bounded(name, 255);
            this.mime = bounded(mime, 200); this.kind = Objects.requireNonNull(kind);
            this.phase = Objects.requireNonNull(phase); this.size = size;
            this.modifiedMillis = modifiedMillis; this.generation = generation;
            this.sha256 = sha256; this.failure = Objects.requireNonNull(failure);
            this.workerOwner = workerOwner; this.token = token;
            if (size < -1 || size > MAX_CAPTURE_BYTES || generation < 0 || modifiedMillis < 0)
                throw new IllegalArgumentException("Invalid capture metadata");
            if (sha256 != null && !sha256.matches("[a-f0-9]{64}"))
                throw new IllegalArgumentException("Invalid capture checksum");
            if (kind == Kind.PHOTO && !mime.startsWith("image/")
                    || kind == Kind.VOICE && !mime.startsWith("audio/"))
                throw new IllegalArgumentException("Capture kind does not match MIME type");
            new ChatStore.Attachment(attachmentId, path, name, mime, Math.max(0, size), sha256);
            if (phase == Phase.RESERVED && (size != -1 || sha256 != null)
                    || phase != Phase.RESERVED && phase != Phase.CANCELED && size <= 0)
                throw new IllegalArgumentException("Capture phase does not match completed source");
            boolean hasDigest = phase == Phase.READY || phase == Phase.ADMITTING
                    || phase == Phase.UNCERTAIN || phase == Phase.ADMITTED || phase == Phase.DISMISSED;
            if (hasDigest && sha256 == null || !hasDigest && phase != Phase.CANCELED && sha256 != null)
                throw new IllegalArgumentException("Capture phase does not match checksum");
            boolean leased = phase == Phase.HASHING || phase == Phase.ADMITTING || phase == Phase.UNCERTAIN;
            if (leased) { uuid(workerOwner); uuid(token); }
            else if (workerOwner != null || token != null)
                throw new IllegalArgumentException("Inactive capture has a worker lease");
        }
        public ChatStore.Attachment readyAttachment() {
            if (sha256 == null) throw new IllegalStateException("Capture has no established checksum");
            return new ChatStore.Attachment(attachmentId, path, name, mime, size, sha256);
        }
        public boolean needsReconciliation() { return phase == Phase.ADMITTING || phase == Phase.UNCERTAIN; }
        private Job changed(Phase next, long bytes, long modified, long nextGeneration,
                            String digest, Failure reason, String owner, String nextToken) {
            return new Job(captureId, attachmentId, company, conversation, path, name, mime,
                    kind, next, bytes, modified, nextGeneration, digest, reason, owner, nextToken);
        }
    }

    /** Obtained only after a durable HASHING transition; an old ticket cannot update a new generation. */
    public static final class HashTicket {
        public final Job job;
        private final String owner, token;
        private HashTicket(Job job) { this.job = job; this.owner = job.workerOwner; this.token = job.token; }
    }
    /** Can only be produced by hashing the sealed ticket source. */
    public static final class DigestResult {
        public final String sha256;
        private final HashTicket ticket;
        private final Object fileKey;
        private DigestResult(HashTicket ticket, String sha256, Object fileKey) {
            this.ticket = ticket; this.sha256 = sha256; this.fileKey = fileKey;
        }
    }
    /** One explicit draft publication attempt; not a send operation or permission to retarget. */
    public static final class AdmissionTicket {
        public final Job job;
        public final ChatStore.Attachment attachment;
        private final String owner, token;
        private AdmissionTicket(Job job) {
            this.job = job; this.attachment = job.readyAttachment();
            this.owner = job.workerOwner; this.token = job.token;
        }
    }

    /**
     * Integrating coordinator must drain all previous publication attempts for this capture,
     * then hold its ORIGINAL destination's draft/send/remove exclusion while invoking closure.
     * It must invoke closure synchronously on the calling thread, exactly once. This is an
     * explicit integration requirement; current MainActivity does not implement this barrier.
     */
    public interface PublicationBarrier {
        void withQuiescentDestination(Job expected, QuiescentAction closure) throws IOException;
    }
    public interface QuiescentAction { boolean run() throws IOException; }

    private final File sourceDirectory;
    private final StoreJournal journal;
    private final String owner = UUID.randomUUID().toString();
    private final Map<String, Job> jobs = new LinkedHashMap<String, Job>();
    private final Set<String> attachmentIds = new HashSet<String>();
    private final Set<String> sourcePaths = new HashSet<String>();
    private int activeJobs;
    private boolean reopenRequired;

    public CaptureAdmission(File journalRoot, File privateAttachmentDirectory) throws IOException {
        if (journalRoot == null || privateAttachmentDirectory == null)
            throw new IllegalArgumentException("Journal and private attachment directory are required");
        sourceDirectory = privateAttachmentDirectory.getCanonicalFile();
        // Android may expose /data/user/0 and /data/data aliases for the same owned directory.
        // Persist only canonical paths, without rejecting the application's legitimate alias.
        if (!Files.isDirectory(sourceDirectory.toPath(), LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Private attachment directory is unavailable");
        File metadata = journalRoot.getCanonicalFile();
        if (metadata.toPath().startsWith(sourceDirectory.toPath()))
            throw new IOException("Capture metadata must be outside the capture source directory");
        journal = new StoreJournal(metadata);
        for (Map.Entry<String, byte[]> record : journal.read().entrySet()) {
            Job job = decode(record.getValue());
            if (!record.getKey().equals(PREFIX + job.captureId))
                throw new IOException("This is not a capture-admission journal");
            checkedPath(job.path);
            if (!attachmentIds.add(job.attachmentId) || !sourcePaths.add(job.path))
                throw new IOException("Capture identities are not unique");
            if (active(job)) activeJobs++;
            jobs.put(job.captureId, job);
        }
    }

    /** Reserve BEFORE starting a new producer. Never call for existing draft/history attachments. */
    public synchronized Job reserve(String captureId, String attachmentId, String company,
                                    String conversation, File newPath, String name, String mime, Kind kind)
            throws IOException {
        usable();
        if (newPath == null) throw new IllegalArgumentException("Capture path is required");
        String path = checkedPath(newPath.getCanonicalPath()).getPath();
        Job proposed = new Job(captureId, attachmentId, company, conversation, path, name,
                mime, kind, Phase.RESERVED, -1, 0, 0, null, Failure.NONE, null, null);
        Job existing = jobs.get(captureId);
        if (existing != null) {
            if (!sameIdentity(existing, proposed)) throw new IllegalArgumentException("Capture identity cannot change");
            return existing;
        }
        if (Files.exists(newPath.toPath(), LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Only a new, uncreated capture path can be reserved");
        if (attachmentIds.contains(attachmentId) || sourcePaths.contains(path))
            throw new IllegalArgumentException("Capture attachment ID and path cannot be reused");
        if (activeJobs >= MAX_ACTIVE_JOBS) throw new IOException("Finish or cancel pending captures before starting another");
        return save(proposed);
    }

    /** Producer must have finished, closed and durably synced its source before this call.
     * This component syncs metadata only; original-file power-loss durability is an integration gate. */
    public synchronized Job seal(String captureId) throws IOException {
        usable(); Job job = required(captureId);
        if (job.phase != Phase.RESERVED) return job; // Repeated/late callback cannot resurrect or reseal.
        BasicFileAttributes attributes = sourceAttributes(job);
        long size = attributes.size();
        if (size <= 0 || size > MAX_CAPTURE_BYTES) throw new IOException("Capture has an invalid completed size");
        return save(job.changed(Phase.PENDING, size, attributes.lastModifiedTime().toMillis(),
                job.generation, null, Failure.NONE, null, null));
    }

    /** A reopened ledger may reclaim an interrupted hash, always with a new generation. */
    public synchronized HashTicket claimHash(String captureId) throws IOException {
        usable(); Job job = required(captureId);
        boolean interrupted = job.phase == Phase.HASHING && !owner.equals(job.workerOwner);
        if (job.phase != Phase.PENDING && job.phase != Phase.RETRY && !interrupted) return null;
        Job claimed = save(job.changed(Phase.HASHING, job.size, job.modifiedMillis,
                increment(job.generation), null, Failure.NONE, owner, UUID.randomUUID().toString()));
        return new HashTicket(claimed);
    }

    /**
     * Hash on a background thread only. On Android pass Looper.getMainLooper().getThread().
     * Sealed metadata and before/after file identity checks catch ordinary replacement/change.
     * They do not make a mutable filesystem an authenticated or immutable content store.
     */
    public DigestResult hash(HashTicket ticket, Thread forbiddenUiThread) throws IOException {
        if (ticket == null || forbiddenUiThread == null) throw new IllegalArgumentException("Ticket and UI thread are required");
        if (Thread.currentThread() == forbiddenUiThread)
            throw new IllegalStateException("Capture hashing is forbidden on the UI thread");
        if (!owner.equals(ticket.owner)) throw new IllegalArgumentException("Hash ticket belongs to another ledger session");
        Job job = ticket.job;
        BasicFileAttributes before = sourceAttributes(job);
        requireSealed(job, before);
        MessageDigest digest;
        try { digest = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
        long count = 0;
        try (InputStream input = Files.newInputStream(checkedPath(job.path).toPath(), LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer = new byte[32768];
            int read;
            while ((read = input.read(buffer)) != -1) {
                if (Thread.currentThread().isInterrupted()) throw new IOException("Capture hashing was interrupted");
                count += read;
                if (count > job.size || count > MAX_CAPTURE_BYTES) throw new IOException("Capture source changed");
                digest.update(buffer, 0, read);
            }
        }
        BasicFileAttributes after = sourceAttributes(job);
        requireSealed(job, after);
        if (count != job.size || before.fileKey() != null && after.fileKey() != null
                && !before.fileKey().equals(after.fileKey())) throw new IOException("Capture source changed");
        return new DigestResult(ticket, hex(digest.digest()), after.fileKey());
    }

    public synchronized boolean acceptDigest(DigestResult result) throws IOException {
        usable(); if (result == null) throw new IllegalArgumentException("Missing digest result");
        Job job = required(result.ticket.job.captureId);
        if (!matchesHash(job, result.ticket)) return false;
        // A delayed callback must still refer to the sealed source that was just hashed.
        BasicFileAttributes current = sourceAttributes(job);
        requireSealed(job, current);
        if (result.fileKey != null && current.fileKey() != null && !result.fileKey.equals(current.fileKey()))
            throw new IOException("Capture source was replaced after hashing");
        // No source re-hash or legacy enrollment occurs at editor/store/bind/send boundaries.
        save(job.changed(Phase.READY, job.size, job.modifiedMillis, job.generation,
                result.sha256, Failure.NONE, null, null));
        return true;
    }

    public synchronized boolean hashFailed(HashTicket ticket, Failure failure) throws IOException {
        usable(); if (ticket == null || failure == null || failure == Failure.NONE)
            throw new IllegalArgumentException("A hash ticket and failure are required");
        Job job = required(ticket.job.captureId);
        if (!matchesHash(job, ticket)) return false;
        save(job.changed(Phase.RETRY, job.size, job.modifiedMillis, job.generation,
                null, failure, null, null));
        return true;
    }

    /** Call only AFTER destination/capacity checks, immediately before the serialized draft write. */
    public synchronized AdmissionTicket beginAdmission(String captureId) throws IOException {
        usable(); Job job = required(captureId);
        if (job.phase != Phase.READY) return null;
        Job claimed = save(job.changed(Phase.ADMITTING, job.size, job.modifiedMillis,
                increment(job.generation), job.sha256, Failure.NONE, owner, UUID.randomUUID().toString()));
        return new AdmissionTicket(claimed);
    }

    /** An exception/lost callback after dispatch is uncertain, never evidence of non-publication. */
    public synchronized boolean admissionUncertain(AdmissionTicket ticket) throws IOException {
        usable(); Job job = required(ticket.job.captureId);
        if (!matchesAdmission(job, ticket)) return false;
        save(job.changed(Phase.UNCERTAIN, job.size, job.modifiedMillis, job.generation,
                job.sha256, Failure.NONE, job.workerOwner, job.token));
        return true;
    }

    /**
     * Reconcile only by exact established presence in the ORIGINAL durable draft. Absence is
     * inconclusive (the user may have sent or removed it); it never permits automatic re-add.
     * Store reads are the sole evidence accepted, not an Activity/editor snapshot or callback.
     */
    public synchronized Observation reconcileDraft(String captureId, ChatStore store) throws IOException {
        usable(); Job job = required(captureId);
        if (job.phase != Phase.ADMITTING && job.phase != Phase.UNCERTAIN && job.phase != Phase.ADMITTED)
            throw new IllegalStateException("Capture has no dispatched admission to reconcile");
        if (store == null || store.requiresReopen()) throw new IOException("Reopen uncertain chat storage before reconciliation");
        // A non-disabled ChatStore may still be stale after another cooperating writer.
        // Caller must serialize this fresh read plus receipt with its draft/send/remove work.
        ChatStore fresh = store.reopen();
        for (ChatStore.Attachment attachment : fresh.draft(job.company, job.conversation).attachments) {
            if (!attachment.id.equals(job.attachmentId)) continue;
            if (!IntegrityAttachments.exact(job.readyAttachment(), attachment)) return Observation.CONFLICT;
            if (job.phase != Phase.ADMITTED) save(job.changed(Phase.ADMITTED, job.size,
                    job.modifiedMillis, job.generation, job.sha256, Failure.NONE, null, null));
            return Observation.CONFIRMED;
        }
        return Observation.NOT_FOUND;
    }

    /**
     * Explicitly close unresolved tracking after the coordinator has quiesced publication.
     * DISMISSED asserts no publication outcome; it never removes a draft or source, retries,
     * retargets, or sends. A fresh/changed attempt or completed admission cannot be dismissed.
     */
    public boolean dismissUnresolved(String captureId, PublicationBarrier barrier) throws IOException {
        if (barrier == null) throw new IllegalArgumentException("Publication quiescence barrier is required");
        final Job expected;
        synchronized (this) {
            usable(); expected = required(captureId);
            if (!expected.needsReconciliation()) return false;
        }
        return quiescentDismissal(expected, barrier);
    }

    private boolean quiescentDismissal(final Job expected, PublicationBarrier barrier) throws IOException {
        if (barrier == null) throw new IllegalArgumentException("Publication quiescence barrier is required");
        final Thread caller = Thread.currentThread();
        final boolean[] active = {true}, called = {false}, changed = {false};
        QuiescentAction closure = new QuiescentAction() {
            public boolean run() throws IOException {
                if (Thread.currentThread() != caller || !active[0] || called[0])
                    throw new IllegalStateException("Quiescent closure must run once, synchronously on its caller");
                called[0] = true;
                synchronized (CaptureAdmission.this) {
                    usable(); Job current = required(expected.captureId);
                    if (!current.needsReconciliation() || current.generation != expected.generation
                            || !sameIdentity(current, expected) || !Objects.equals(current.token, expected.token)) return false;
                    save(current.changed(Phase.DISMISSED, current.size, current.modifiedMillis,
                            increment(current.generation), current.sha256, Failure.NONE, null, null));
                    changed[0] = true;
                    return true;
                }
            }
        };
        // Never hold the ledger monitor while draining another publisher: its ACK may need it.
        try { barrier.withQuiescentDestination(expected, closure); }
        finally { active[0] = false; }
        if (!called[0]) throw new IOException("Publication barrier did not run the quiescent closure");
        return changed[0];
    }

    /** Pre-admission tombstone; confirmed/dismissed receipts are already terminal and stay intact. */
    public synchronized boolean cancel(String captureId) throws IOException {
        usable(); Job job = required(captureId);
        if (job.needsReconciliation()) throw new IllegalStateException("Settle admission before cancel/removal");
        if (job.phase == Phase.CANCELED || job.phase == Phase.ADMITTED || job.phase == Phase.DISMISSED) return false;
        save(job.changed(Phase.CANCELED, job.size, job.modifiedMillis, increment(job.generation),
                job.sha256, Failure.NONE, null, null));
        return true;
    }
    public synchronized Job get(String captureId) { return required(captureId); }
    public synchronized List<Job> jobs() { return Collections.unmodifiableList(new ArrayList<Job>(jobs.values())); }
    public synchronized boolean requiresReopen() { return reopenRequired; }

    private boolean matchesHash(Job job, HashTicket ticket) {
        return job.phase == Phase.HASHING && job.generation == ticket.job.generation
                && owner.equals(ticket.owner) && Objects.equals(job.workerOwner, ticket.owner)
                && Objects.equals(job.token, ticket.token) && sameIdentity(job, ticket.job);
    }
    private boolean matchesAdmission(Job job, AdmissionTicket ticket) {
        return job.phase == Phase.ADMITTING && job.generation == ticket.job.generation
                && owner.equals(ticket.owner) && Objects.equals(job.workerOwner, ticket.owner)
                && Objects.equals(job.token, ticket.token) && sameIdentity(job, ticket.job);
    }
    private Job save(Job job) throws IOException {
        try {
            journal.commit(Collections.singletonList(new StoreJournal.Record(PREFIX + job.captureId, encode(job))));
        } catch (IOException failure) { reopenRequired = true; throw failure; }
        Job prior = jobs.put(job.captureId, job); // Never acknowledge uncertain writes in memory.
        if (prior == null) { attachmentIds.add(job.attachmentId); sourcePaths.add(job.path); }
        if (prior != null && active(prior)) activeJobs--;
        if (active(job)) activeJobs++;
        return job;
    }
    private static boolean active(Job job) { return job.phase != Phase.ADMITTED && job.phase != Phase.CANCELED && job.phase != Phase.DISMISSED; }
    private void usable() throws IOException { if (reopenRequired) throw new IOException("Reopen capture metadata before retrying"); }
    private Job required(String id) { Job job = jobs.get(id); if (job == null) throw new IllegalArgumentException("Unknown capture"); return job; }
    private File checkedPath(String path) throws IOException {
        File file = new File(path);
        File canonical = file.getCanonicalFile();
        if (!file.isAbsolute() || !canonical.equals(file) || !sourceDirectory.equals(canonical.getParentFile()))
            throw new IOException("Capture must have a unique canonical private path");
        return canonical;
    }
    private BasicFileAttributes sourceAttributes(Job job) throws IOException {
        BasicFileAttributes attributes = Files.readAttributes(checkedPath(job.path).toPath(),
                BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (!attributes.isRegularFile()) throw new IOException("Capture source is unavailable");
        return attributes;
    }
    private static void requireSealed(Job job, BasicFileAttributes attributes) throws IOException {
        if (job.size <= 0 || attributes.size() != job.size
                || attributes.lastModifiedTime().toMillis() != job.modifiedMillis)
            throw new IOException("Capture source changed after completion");
    }
    private static long increment(long value) { if (value == Long.MAX_VALUE) throw new IllegalStateException("Capture generation exhausted"); return value + 1; }
    private static boolean sameIdentity(Job a, Job b) {
        return a.captureId.equals(b.captureId) && a.attachmentId.equals(b.attachmentId)
                && a.company.equals(b.company) && a.conversation.equals(b.conversation)
                && a.path.equals(b.path) && a.name.equals(b.name) && a.mime.equals(b.mime) && a.kind == b.kind;
    }
    private static String bounded(String value, int max) {
        if (value == null || value.length() == 0 || value.length() > max)
            throw new IllegalArgumentException("Missing or oversized capture field");
        return value;
    }
    private static String uuid(String value) {
        if (value == null || !UUID.fromString(value).toString().equals(value))
            throw new IllegalArgumentException("A canonical UUID is required");
        return value;
    }
    private static String hex(byte[] bytes) {
        char[] output = new char[bytes.length * 2]; char[] digits = "0123456789abcdef".toCharArray();
        for (int i = 0; i < bytes.length; i++) { output[i * 2] = digits[(bytes[i] & 255) >>> 4]; output[i * 2 + 1] = digits[bytes[i] & 15]; }
        return new String(output);
    }
    private static void nullable(DataOutputStream out, String value) throws IOException {
        out.writeBoolean(value != null); if (value != null) out.writeUTF(value);
    }
    private static String nullable(DataInputStream in) throws IOException { return in.readBoolean() ? in.readUTF() : null; }
    private static byte[] encode(Job job) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (DataOutputStream out = new DataOutputStream(bytes)) {
            out.writeInt(FORMAT); out.writeUTF(job.captureId); out.writeUTF(job.attachmentId);
            out.writeUTF(job.company); out.writeUTF(job.conversation); out.writeUTF(job.path);
            out.writeUTF(job.name); out.writeUTF(job.mime); out.writeUTF(job.kind.name());
            out.writeUTF(job.phase.name()); out.writeLong(job.size); out.writeLong(job.modifiedMillis);
            out.writeLong(job.generation); nullable(out, job.sha256); out.writeUTF(job.failure.name());
            nullable(out, job.workerOwner); nullable(out, job.token);
        }
        return bytes.toByteArray();
    }
    private static Job decode(byte[] bytes) throws IOException {
        if (bytes == null) throw new IOException("Missing capture metadata");
        try (DataInputStream in = new DataInputStream(new ByteArrayInputStream(bytes))) {
            if (in.readInt() != FORMAT) throw new IOException("Unsupported capture-admission version");
            Job job = new Job(in.readUTF(), in.readUTF(), in.readUTF(), in.readUTF(),
                    in.readUTF(), in.readUTF(), in.readUTF(), Kind.valueOf(in.readUTF()),
                    Phase.valueOf(in.readUTF()), in.readLong(), in.readLong(), in.readLong(),
                    nullable(in), Failure.valueOf(in.readUTF()), nullable(in), nullable(in));
            if (in.read() != -1) throw new IOException("Trailing capture metadata");
            return job;
        } catch (IllegalArgumentException invalid) { throw new IOException("Invalid capture metadata", invalid); }
    }
}
