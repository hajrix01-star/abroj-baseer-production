package com.baseer.freshchat.sync;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.AtomicFile;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;

/** Private, durable one-file outbox. The server ACK, not an upload response, retires a file. */
public final class BChatConnectedMediaStore {
    public static final int IMAGE_LIMIT = 5 * 1024 * 1024;
    public static final int PDF_LIMIT = 10 * 1024 * 1024;
    public static final int AUDIO_LIMIT = 10 * 1024 * 1024;
    private static final int MAX_METADATA_BYTES = 24 * 1024;
    private static final int MAX_PENDING_REQUESTS = 20;
    private static final long MAX_STAGED_BYTES = 50L * 1024 * 1024;
    public static final long INACTIVE_PART_RETENTION_MILLIS = 24L * 60 * 60 * 1000;
    private static final int MAX_DIAGNOSTIC_PROBLEMS = 100;
    // One lock across helper instances. Never held while a provider supplies bytes or HTTP runs.
    private static final Object STORE_LOCK = new Object();
    private static final Set<String> ACTIVE_STAGE_ACCOUNTS = new HashSet<>();
    private static final Set<String> ACTIVE_STAGE_PARTS = new HashSet<>();
    private static final Map<String, Long> ACCOUNT_GENERATIONS = new HashMap<>();
    private final File root;

    public BChatConnectedMediaStore(Context context) {
        root = new File(context.getFilesDir(), "bchat-v2-media");
    }

    /** Bounded local diagnostics contain identity and reason only, never a name, caption or bytes. */
    public static final class Problem {
        public final String uploadUuid, code;
        /** Zero when corrupt metadata cannot establish this context. */
        public final long roomId, companyId, membershipId;
        private Problem(String uuid, String code, Entry trusted) {
            this.uploadUuid = uuid;
            this.code = code;
            roomId = trusted == null ? 0 : trusted.roomId;
            companyId = trusted == null ? 0 : trusted.companyId;
            membershipId = trusted == null ? 0 : trusted.membershipId;
        }
    }

    public static final class Diagnostics {
        public final List<Problem> problems;
        public final int totalProblemCount, requestCount;
        public final long usedBytes;
        public final boolean truncated;
        private Diagnostics(Scan scan) {
            problems = Collections.unmodifiableList(new ArrayList<>(scan.problems));
            totalProblemCount = scan.problemCount;
            requestCount = scan.requestCount;
            usedBytes = scan.usedBytes;
            truncated = totalProblemCount > problems.size();
        }
    }

    private static final class Scan {
        final List<Entry> entries = new ArrayList<>();
        final List<Entry> metadata = new ArrayList<>();
        final List<Problem> problems = new ArrayList<>();
        int problemCount, requestCount;
        long usedBytes;
        void problem(String uuid, String code, Entry trusted) {
            problemCount++;
            if (problems.size() < MAX_DIAGNOSTIC_PROBLEMS)
                problems.add(new Problem(uuid, code, trusted));
        }
    }

    private static final class StorageIssue extends IOException {
        final String code;
        StorageIssue(String code) { super(code); this.code = code; }
        StorageIssue(String code, Exception cause) { super(code, cause); this.code = code; }
    }

    public Diagnostics diagnostics(AccountScope account) throws IOException {
        synchronized (STORE_LOCK) { return new Diagnostics(scan(account)); }
    }

    private static String recognizedUuid(File file) {
        String name = file.getName();
        if (!file.isFile() || !name.matches("[0-9a-f-]{36}\\.(bin|part|json)(\\.new|\\.bak)?"))
            return null;
        String uuid = name.substring(0, 36);
        try { requireUuid(uuid); return uuid; }
        catch (IOException invalid) { return null; }
    }

    private File[] files(AccountScope account) throws IOException {
        File[] files = scope(account).listFiles();
        if (files == null) throw new IOException("Cannot inspect media scope");
        return files;
    }

    /** Recover every AtomicFile before computing quotas or any housekeeping decision. */
    private Scan scan(AccountScope account) throws IOException {
        Set<String> metadataIds = new TreeSet<>();
        for (File file : files(account)) {
            String uuid = recognizedUuid(file);
            if (uuid != null && file.getName().startsWith(uuid + ".json")) metadataIds.add(uuid);
        }
        Scan scan = new Scan();
        for (String uuid : metadataIds) {
            Entry entry;
            try { entry = readMetadata(account, uuid); }
            catch (StorageIssue issue) { scan.problem(uuid, issue.code, null); continue; }
            scan.metadata.add(entry);
            File data = data(account, uuid);
            if (!data.isFile()) scan.problem(uuid, "media_missing", entry);
            else if (data.length() != entry.size) scan.problem(uuid, "media_size_mismatch", entry);
            else scan.entries.add(entry);
        }
        Set<String> requestIds = new HashSet<>();
        for (File file : files(account)) {
            // Count actual private bytes, including orphans, partial files and metadata variants.
            if (file.isFile()) {
                long bytes = file.length();
                scan.usedBytes = bytes > Long.MAX_VALUE - scan.usedBytes
                        ? Long.MAX_VALUE : scan.usedBytes + bytes;
            }
            String uuid = recognizedUuid(file);
            if (uuid == null) continue;
            requestIds.add(uuid); // .json/.bak/.new are one request, never three sends.
            if (file.getName().equals(uuid + ".bin") && !metadataIds.contains(uuid))
                scan.problem(uuid, "orphan_media", null);
            if (file.getName().equals(uuid + ".part")
                    && !ACTIVE_STAGE_PARTS.contains(file.getAbsolutePath()))
                scan.problem(uuid, "staging_incomplete", null);
        }
        scan.requestCount = requestIds.size();
        return scan;
    }

    public int cleanupExpiredParts(AccountScope account) throws IOException {
        return cleanupExpiredParts(account, System.currentTimeMillis());
    }

    int cleanupExpiredParts(AccountScope account, long now) throws IOException {
        synchronized (STORE_LOCK) { return cleanupExpiredPartsLocked(account, now); }
    }

    private int cleanupExpiredPartsLocked(AccountScope account, long now) throws IOException {
        scan(account); // Atomic backup recovery precedes cleanup, including for an absent base.
        int removed = 0;
        if (now < INACTIVE_PART_RETENTION_MILLIS) return removed;
        for (File file : files(account)) {
            String uuid = recognizedUuid(file);
            if (uuid == null || !file.getName().equals(uuid + ".part")
                    || ACTIVE_STAGE_PARTS.contains(file.getAbsolutePath())) continue;
            long modified = file.lastModified();
            if (modified > 0 && modified <= now - INACTIVE_PART_RETENTION_MILLIS) {
                if (!file.delete()) throw new IOException("Cannot remove interrupted media staging");
                removed++;
            }
        }
        return removed;
    }

    private String stageScope(AccountScope account) throws IOException {
        return scope(account).getAbsolutePath();
    }

    private long generation(String scope) {
        Long value = ACCOUNT_GENERATIONS.get(scope);
        return value == null ? 0 : value;
    }

    private File scope(AccountScope account) throws IOException {
        if (account == null || !account.key.matches("[0-9a-f]{64}"))
            throw new IOException("Unverified media account");
        File folder = new File(root, account.key);
        if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Cannot create media scope");
        return folder;
    }

    private static void requireUuid(String uuid) throws IOException {
        try {
            UUID value = UUID.fromString(uuid);
            if (!value.toString().equals(uuid) || value.version() != 4) throw new IOException("Invalid UUID");
        } catch (IllegalArgumentException invalid) { throw new IOException("Invalid UUID", invalid); }
    }

    private File data(AccountScope account, String uuid) throws IOException {
        requireUuid(uuid);
        return new File(scope(account), uuid + ".bin");
    }

    private File metadata(AccountScope account, String uuid) throws IOException {
        requireUuid(uuid);
        return new File(scope(account), uuid + ".json");
    }

    private static String cleanName(String input, String kind) {
        if (input == null) input = "";
        int start = Math.max(input.lastIndexOf('/'), input.lastIndexOf('\\')) + 1;
        StringBuilder result = new StringBuilder(160);
        int bytes = 0, scanned = 0;
        for (int offset = start; offset < input.length() && scanned < 512; scanned++) {
            int codePoint = input.codePointAt(offset);
            offset += Character.charCount(codePoint);
            if (Character.isISOControl(codePoint)
                    || (codePoint >= 0xD800 && codePoint <= 0xDFFF)) continue;
            int width = new String(Character.toChars(codePoint)).getBytes(StandardCharsets.UTF_8).length;
            if (bytes + width > 160) break;
            result.appendCodePoint(codePoint);
            bytes += width;
        }
        String name = result.toString().trim();
        return name.isEmpty() ? ("image".equals(kind) ? "image" : "audio".equals(kind)
                ? "voice.m4a" : "document") : name;
    }

    private static String displayName(ContentResolver resolver, Uri uri, String kind) {
        String name = null;
        try (Cursor row = resolver.query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (row != null && row.moveToFirst()) name = row.getString(0);
        } catch (Exception ignored) { /* A provider may omit the optional display name. */ }
        return cleanName(name, kind);
    }

    private static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) result.append(String.format(Locale.ROOT, "%02x", b & 255));
        return result.toString();
    }

    private static void writeJson(File target, JSONObject value) throws IOException {
        AtomicFile atomic = new AtomicFile(target);
        FileOutputStream output = null;
        try {
            output = atomic.startWrite();
            output.write(value.toString().getBytes(StandardCharsets.UTF_8));
            atomic.finishWrite(output);
        } catch (Exception failure) {
            if (output != null) atomic.failWrite(output);
            throw new IOException("Cannot save media request", failure);
        }
    }

    private void requireStageCapacity(AccountScope account, long roomId, long membershipId,
                                      String currentUuid, int extraMetadataBytes) throws IOException {
        Scan scan = scan(account);
        for (Entry existing : scan.metadata)
            if (existing.roomId == roomId && existing.membershipId == membershipId)
                throw new IOException("Resolve the pending media request first");
        int requests = scan.requestCount + (currentUuid == null ? 1 : 0);
        // At commit the current .part is already included in actual bytes and request count.
        if (requests > MAX_PENDING_REQUESTS || extraMetadataBytes > MAX_STAGED_BYTES - scan.usedBytes)
            throw new IOException("Local media staging quota reached");
    }

    /** Never hold the store monitor or commit lock while a SAF provider supplies bytes. */
    static int copyBounded(InputStream input, OutputStream output, MessageDigest sha,
                           int limit) throws IOException {
        if (input == null || output == null || sha == null || limit < 1 || limit > PDF_LIMIT)
            throw new IOException("Invalid media copy bound");
        int size = 0;
        byte[] buffer = new byte[32 * 1024];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (count <= 0 || count > limit - size)
                throw new IOException("The selected file is too large or stalled");
            size += count;
            output.write(buffer, 0, count);
            sha.update(buffer, 0, count);
        }
        return size;
    }

    /** Stage SAF bytes before any network call. Provider-reported MIME is advisory; the server verifies bytes. */
    public Entry stage(ContentResolver resolver, AccountScope account, long roomId,
                                    long companyId, long membershipId, Uri uri, String text,
                                    long replyToMessageId) throws IOException {
        return stage(resolver, account, roomId, companyId, membershipId, uri, text,
                replyToMessageId, "other", 1, 0);
    }

    public Entry stage(ContentResolver resolver, AccountScope account, long roomId,
                                    long companyId, long membershipId, Uri uri, String text,
                                    long replyToMessageId, String documentType, int policyVersion,
                                    long invoiceCaseId) throws IOException {
        return stage(resolver, account, roomId, companyId, membershipId, uri, text,
                replyToMessageId, documentType, policyVersion, invoiceCaseId, null);
    }

    public Entry stage(ContentResolver resolver, AccountScope account, long roomId,
                                    long companyId, long membershipId, Uri uri, String text,
                                    long replyToMessageId, String documentType, int policyVersion,
                                    long invoiceCaseId, String displayNameOverride) throws IOException {
        if (resolver == null || account == null || uri == null || !"content".equals(uri.getScheme())
                || roomId <= 0 || companyId <= 0 || membershipId <= 0 || replyToMessageId < 0
                || (text == null || text.getBytes(StandardCharsets.UTF_8).length > 16 * 1024)
                || policyVersion < 1 || !("other".equals(documentType) || "invoice".equals(documentType)
                || "payment_receipt".equals(documentType))
                || ("payment_receipt".equals(documentType) != (invoiceCaseId > 0)))
            throw new IOException("Invalid media scope");
        if (!text.isEmpty()) {
            try { OutboxPolicy.requireText(text); }
            catch (IllegalArgumentException invalid) { throw new IOException("Invalid media caption", invalid); }
        }
        String mime = resolver.getType(uri);
        String kind;
        int limit;
        if ("image/jpeg".equals(mime) || "image/png".equals(mime) || "image/webp".equals(mime)) {
            kind = "image"; limit = IMAGE_LIMIT;
        } else if ("audio/mp4".equals(mime)) {
            kind = "audio"; limit = AUDIO_LIMIT;
        } else if ("application/pdf".equals(mime)) {
            kind = "file"; limit = PDF_LIMIT;
        } else if ("application/vnd.openxmlformats-officedocument.wordprocessingml.document".equals(mime)
                || "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet".equals(mime)
                || "text/plain".equals(mime)) {
            kind = "file"; limit = PDF_LIMIT;
        } else throw new IOException("Unsupported media type");
        if ("audio".equals(kind) && !"other".equals(documentType))
            throw new IOException("Audio cannot be an invoice");
        if (!"other".equals(documentType) && !"image".equals(kind)
                && !"application/pdf".equals(mime))
            throw new IOException("This file cannot be an invoice");
        String name = displayNameOverride == null ? displayName(resolver, uri, kind)
                : cleanName(displayNameOverride, kind);
        final String uuid = UUID.randomUUID().toString();
        final File finalFile, temporary;
        final String stageScope;
        final long stageGeneration;
        final int copyLimit;
        synchronized (STORE_LOCK) {
            stageScope = stageScope(account);
            if (ACTIVE_STAGE_ACCOUNTS.contains(stageScope))
                throw new IOException("Another media file is being staged for this account");
            cleanupExpiredPartsLocked(account, System.currentTimeMillis());
            requireStageCapacity(account, roomId, membershipId, null, MAX_METADATA_BYTES);
            copyLimit = (int) Math.min(limit, MAX_STAGED_BYTES - scan(account).usedBytes - MAX_METADATA_BYTES);
            if (copyLimit < 1) throw new IOException("Local media staging quota reached");
            finalFile = data(account, uuid);
            temporary = new File(scope(account), uuid + ".part");
            stageGeneration = generation(stageScope);
            ACTIVE_STAGE_ACCOUNTS.add(stageScope);
            ACTIVE_STAGE_PARTS.add(temporary.getAbsolutePath());
        }
        try {
            MessageDigest sha = MessageDigest.getInstance("SHA-256");
            int size;
            try (InputStream input = resolver.openInputStream(uri);
                 FileOutputStream output = new FileOutputStream(temporary)) {
                if (input == null) throw new IOException("The selected file is unavailable");
                size = copyBounded(input, output, sha, copyLimit);
                output.getFD().sync();
            }
            if (size == 0) throw new IOException("The selected file is empty");
            synchronized (STORE_LOCK) {
                if (stageGeneration != generation(stageScope))
                    throw new IOException("Media scope was revoked during staging");
                JSONObject saved = new JSONObject();
                saved.put("account_key", account.key);
                saved.put("room_id", roomId);
                saved.put("company_id", companyId);
                saved.put("membership_id", membershipId);
                saved.put("upload_uuid", uuid);
                saved.put("client_uuid", UUID.randomUUID().toString());
                saved.put("kind", kind);
                saved.put("mime", mime);
                saved.put("name", name);
                saved.put("size", size);
                saved.put("sha256", hex(sha.digest()));
                saved.put("text", text);
                saved.put("reply_to_message_id", replyToMessageId);
                saved.put("document_type", documentType);
                saved.put("policy_version", policyVersion);
                saved.put("invoice_case_id", invoiceCaseId);
                saved.put("media_id", 0);
                requireStageCapacity(account, roomId, membershipId, uuid,
                        saved.toString().getBytes(StandardCharsets.UTF_8).length);
                if (!temporary.renameTo(finalFile)) throw new IOException("Cannot commit selected file");
                writeJson(metadata(account, uuid), saved);
                return read(account, uuid);
            }
        } catch (Exception error) {
            synchronized (STORE_LOCK) {
                temporary.delete();
                finalFile.delete();
                try { new AtomicFile(metadata(account, uuid)).delete(); } catch (IOException ignored) { }
            }
            if (error instanceof IOException) throw (IOException) error;
            throw new IOException("Cannot stage selected file", error);
        } finally {
            synchronized (STORE_LOCK) {
                ACTIVE_STAGE_PARTS.remove(temporary.getAbsolutePath());
                ACTIVE_STAGE_ACCOUNTS.remove(stageScope);
            }
        }
    }

    private Entry readMetadata(AccountScope account, String uuid) throws IOException {
        File json = metadata(account, uuid);
        byte[] bytes;
        try (FileInputStream input = new AtomicFile(json).openRead();
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            int amount;
            while ((amount = input.read(buffer)) != -1) {
                if (amount <= 0) throw new StorageIssue("metadata_unavailable");
                if (amount > MAX_METADATA_BYTES - output.size())
                    throw new StorageIssue("metadata_oversized");
                output.write(buffer, 0, amount);
            }
            bytes = output.toByteArray();
        } catch (StorageIssue issue) { throw issue; }
        catch (IOException unavailable) { throw new StorageIssue("metadata_unavailable", unavailable); }
        try {
            JSONObject object = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            if (!account.key.equals(object.getString("account_key"))
                    || !uuid.equals(object.getString("upload_uuid"))) throw new IOException("Media scope changed");
            return new Entry(object);
        } catch (Exception invalid) {
            throw new StorageIssue("metadata_invalid", invalid);
        }
    }

    private Entry read(AccountScope account, String uuid) throws IOException {
        Entry entry = readMetadata(account, uuid);
        File file = data(account, uuid);
        if (!file.isFile() || file.length() != entry.size) throw new IOException("Staged media changed");
        return entry;
    }

    public Entry pending(AccountScope account, long roomId, long membershipId) throws IOException {
        synchronized (STORE_LOCK) {
            List<Entry> matches = pendingForRoom(account, roomId, membershipId);
            return matches.isEmpty() ? null : matches.get(0);
        }
    }

    /**
     * Lists every durable request for one room.  A lost client ACK can leave several records
     * even though their messages reached Odoo; callers that reconcile authenticated history
     * must see the whole set rather than treating the normal recoverable state as corruption.
     */
    public List<Entry> pendingForRoom(AccountScope account, long roomId, long membershipId)
            throws IOException {
        synchronized (STORE_LOCK) {
            List<Entry> matches = new ArrayList<>();
            for (Entry candidate : scan(account).entries) {
                if (candidate.roomId == roomId && candidate.membershipId == membershipId) {
                    matches.add(candidate);
                }
            }
            Collections.sort(matches, (left, right) -> left.uploadUuid.compareTo(right.uploadUuid));
            return matches;
        }
    }

    public Entry markUploaded(AccountScope account, Entry entry, long mediaId) throws IOException {
        synchronized (STORE_LOCK) {
            if (mediaId <= 0 || entry == null) throw new IOException("Invalid media receipt");
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry) || !current.remoteUploadUuid.equals(entry.remoteUploadUuid)
                    || (current.mediaId != 0 && current.mediaId != mediaId))
                throw new IOException("Media receipt scope changed");
            JSONObject object = current.toJson();
            try { object.put("media_id", mediaId); }
            catch (Exception invalid) { throw new IOException("Invalid media receipt", invalid); }
            writeJson(metadata(account, entry.uploadUuid), object);
            return read(account, entry.uploadUuid);
        }
    }

    /** Rotate only the server upload identity after a verified upload_expired response.
     *  The local filename, message UUID, bytes and digest remain unchanged across process death. */
    public static boolean canRenewExpiredUpload(int statusCode, String code, boolean renewedThisAttempt) {
        return statusCode == 409 && "upload_expired".equals(code) && !renewedThisAttempt;
    }

    public Entry renewExpiredUpload(AccountScope account, Entry entry, String code)
            throws IOException {
        synchronized (STORE_LOCK) {
            if (entry == null || !"upload_expired".equals(code))
                throw new IOException("Only an expired upload can be renewed");
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry) || !current.remoteUploadUuid.equals(entry.remoteUploadUuid)
                    || current.mediaId != entry.mediaId || !current.uploadBlockCode.isEmpty())
                throw new IOException("Expired media request changed");
            JSONObject object = current.toJson();
            try {
                object.put("remote_upload_uuid", UUID.randomUUID().toString());
                object.put("media_id", 0);
            } catch (Exception invalid) { throw new IOException("Cannot renew expired upload", invalid); }
            writeJson(metadata(account, entry.uploadUuid), object);
            return read(account, entry.uploadUuid);
        }
    }

    /** A deterministic upload rejection must not be retried with the same UUID. */
    public Entry markUploadBlocked(AccountScope account, Entry entry, String code) throws IOException {
        synchronized (STORE_LOCK) {
            if (entry == null || code == null || !code.matches("[a-z_]{1,64}"))
                throw new IOException("Invalid upload rejection");
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry) || !current.remoteUploadUuid.equals(entry.remoteUploadUuid)
                    || current.mediaId != 0)
                throw new IOException("Media rejection scope changed");
            JSONObject object = current.toJson();
            try { object.put("upload_block_code", code); }
            catch (Exception invalid) { throw new IOException("Cannot save media rejection", invalid); }
            writeJson(metadata(account, entry.uploadUuid), object);
            return read(account, entry.uploadUuid);
        }
    }

    public void acknowledge(AccountScope account, Entry entry) throws IOException {
        synchronized (STORE_LOCK) {
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry) || !current.remoteUploadUuid.equals(entry.remoteUploadUuid)
                    || current.mediaId != entry.mediaId || entry.mediaId <= 0)
                throw new IOException("Media ACK does not match staged request");
            deleteMetadata(account, entry.uploadUuid);
            data(account, entry.uploadUuid).delete(); // Orphan file is private, never a sent request.
        }
    }

    /** Explicit user decision only; does not retract a possible server-side upload or message. */
    public void discard(AccountScope account, Entry entry) throws IOException {
        synchronized (STORE_LOCK) {
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry) || !current.remoteUploadUuid.equals(entry.remoteUploadUuid)
                    || current.mediaId != entry.mediaId) throw new IOException("Media request changed");
            deleteMetadata(account, entry.uploadUuid);
            data(account, entry.uploadUuid).delete();
        }
    }

    /** Delete this account's staged media after upload permission is revoked. */
    public void purgeAccount(AccountScope account) throws IOException {
        synchronized (STORE_LOCK) {
            String scope = stageScope(account);
            ACCOUNT_GENERATIONS.put(scope, generation(scope) + 1);
            scan(account); // Recover backups before permission-driven deletion.
            for (File file : files(account)) {
                if (recognizedUuid(file) == null
                        || ACTIVE_STAGE_PARTS.contains(file.getAbsolutePath())) continue;
                if (!file.delete()) throw new IOException("Cannot delete revoked media");
            }
        }
    }

    /** Remove staged uploads outside a freshly verified company scope. */
    public void purgeCompaniesNotIn(AccountScope account,
                                                  java.util.Set<Long> allowedCompanies)
            throws IOException {
        synchronized (STORE_LOCK) {
            if (allowedCompanies == null) throw new IOException("Verified companies required");
            String scope = stageScope(account);
            ACCOUNT_GENERATIONS.put(scope, generation(scope) + 1);
            Scan scan = scan(account);
            // Unknown context is never returned by pending/file, so it confers no access.
            // Keep those originals diagnostic-only rather than throwing into a caller's
            // whole-account purge solely because one record is corrupt.
            for (Entry entry : scan.metadata) {
                if (!allowedCompanies.contains(entry.companyId)) {
                    deleteMetadata(account, entry.uploadUuid);
                    data(account, entry.uploadUuid).delete();
                }
            }
            cleanupExpiredPartsLocked(account, System.currentTimeMillis());
        }
    }

    public File file(AccountScope account, Entry entry) throws IOException {
        synchronized (STORE_LOCK) {
            Entry current = read(account, entry.uploadUuid);
            if (!current.sameRequest(entry)) throw new IOException("Media request changed");
            return data(account, entry.uploadUuid);
        }
    }

    private void deleteMetadata(AccountScope account, String uuid) throws IOException {
        File file = metadata(account, uuid);
        new AtomicFile(file).delete();
        if (file.exists() || new File(file.getPath() + ".bak").exists()
                || new File(file.getPath() + ".new").exists())
            throw new IOException("Cannot retire media metadata");
    }

    public static final class Entry {
        public final String accountKey, uploadUuid, remoteUploadUuid, clientUuid, kind, mime, name, sha256, text,
                documentType, uploadBlockCode;
        public final long roomId, companyId, membershipId, replyToMessageId, mediaId, invoiceCaseId;
        public final int size, policyVersion;

        private Entry(JSONObject value) throws Exception {
            accountKey = value.getString("account_key");
            uploadUuid = value.getString("upload_uuid");
            remoteUploadUuid = value.optString("remote_upload_uuid", "");
            clientUuid = value.getString("client_uuid");
            kind = value.getString("kind");
            mime = value.getString("mime");
            name = value.getString("name");
            sha256 = value.getString("sha256");
            text = value.getString("text");
            roomId = value.getLong("room_id");
            companyId = value.getLong("company_id");
            membershipId = value.getLong("membership_id");
            replyToMessageId = value.getLong("reply_to_message_id");
            mediaId = value.getLong("media_id");
            documentType = value.optString("document_type", "other");
            uploadBlockCode = value.optString("upload_block_code", "");
            policyVersion = value.optInt("policy_version", 1);
            invoiceCaseId = value.optLong("invoice_case_id", 0);
            size = value.getInt("size");
            requireUuid(uploadUuid);
            if (!remoteUploadUuid.isEmpty()) requireUuid(remoteUploadUuid);
            requireUuid(clientUuid);
            int limit = "image".equals(kind) ? IMAGE_LIMIT : "audio".equals(kind)
                    ? AUDIO_LIMIT : "file".equals(kind) ? PDF_LIMIT : 0;
            if (limit == 0 || roomId <= 0 || companyId <= 0 || membershipId <= 0
                    || size < 1 || size > limit || mediaId < 0 || replyToMessageId < 0
                    || !sha256.matches("[0-9a-f]{64}") || name.getBytes(StandardCharsets.UTF_8).length > 160
                    || text.getBytes(StandardCharsets.UTF_8).length > 16 * 1024
                    || policyVersion < 1 || !("other".equals(documentType)
                    || "invoice".equals(documentType) || "payment_receipt".equals(documentType))
                    || !uploadBlockCode.matches("[a-z_]{0,64}")
                    || ("payment_receipt".equals(documentType) != (invoiceCaseId > 0))
                    || (!"other".equals(documentType) && !"image".equals(kind)
                    && !"application/pdf".equals(mime))
                    || !("image".equals(kind) ? mime.equals("image/jpeg") || mime.equals("image/png")
                    || mime.equals("image/webp") : "audio".equals(kind) ? mime.equals("audio/mp4")
                    : mime.equals("application/pdf")
                    || mime.equals("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
                    || mime.equals("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                    || mime.equals("text/plain")))
                throw new IOException("Invalid staged media");
            if (!text.isEmpty()) OutboxPolicy.requireText(text);
        }

        private boolean sameRequest(Entry other) {
            return other != null && accountKey.equals(other.accountKey) && uploadUuid.equals(other.uploadUuid)
                    && clientUuid.equals(other.clientUuid) && roomId == other.roomId
                    && companyId == other.companyId && membershipId == other.membershipId
                    && size == other.size && sha256.equals(other.sha256)
                    && kind.equals(other.kind) && mime.equals(other.mime)
                    && name.equals(other.name) && text.equals(other.text)
                    && replyToMessageId == other.replyToMessageId
                    && documentType.equals(other.documentType) && policyVersion == other.policyVersion
                    && invoiceCaseId == other.invoiceCaseId;
        }

        private JSONObject toJson() throws IOException {
            try {
                JSONObject object = new JSONObject();
                object.put("account_key", accountKey);
                object.put("room_id", roomId);
                object.put("company_id", companyId);
                object.put("membership_id", membershipId);
                object.put("upload_uuid", uploadUuid);
                if (!remoteUploadUuid.isEmpty()) object.put("remote_upload_uuid", remoteUploadUuid);
                object.put("client_uuid", clientUuid);
                object.put("kind", kind);
                object.put("mime", mime);
                object.put("name", name);
                object.put("size", size);
                object.put("sha256", sha256);
                object.put("text", text);
                object.put("reply_to_message_id", replyToMessageId);
                object.put("document_type", documentType);
                object.put("policy_version", policyVersion);
                object.put("invoice_case_id", invoiceCaseId);
                object.put("media_id", mediaId);
                object.put("upload_block_code", uploadBlockCode);
                return object;
            } catch (Exception invalid) { throw new IOException("Cannot serialize media request", invalid); }
        }

        public JSONObject uploadMetadata() throws IOException {
            try {
                JSONObject object = new JSONObject();
                object.put("api_version", 2);
                object.put("membership_id", membershipId);
                object.put("upload_uuid", networkUploadUuid());
                object.put("kind", kind);
                object.put("mime", mime);
                object.put("size", size);
                object.put("sha256", sha256);
                object.put("name", name);
                return object;
            } catch (Exception invalid) { throw new IOException("Cannot serialize media upload", invalid); }
        }

        public String networkUploadUuid() {
            return remoteUploadUuid.isEmpty() ? uploadUuid : remoteUploadUuid;
        }
    }
}
