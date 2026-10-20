package com.baseer.bwork.legacy;

import java.io.BufferedInputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.Writer;
import java.io.StringWriter;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InvalidClassException;
import java.io.ObjectInputStream;
import java.io.ObjectOutputStream;
import java.io.ObjectStreamClass;
import java.io.Serializable;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.text.Normalizer;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;
import java.util.UUID;

/**
 * Small offline-only store. All displayed companies and seed conversations are synthetic.
 * There is deliberately no network transport, authenticated account, or last-recipient field.
 *
 * Writes publish bounded immutable records through a checked journal root. The in-memory
 * snapshot changes only after a confirmed commit. Legacy snapshots remain read-only until
 * their exact bytes have been durably archived. The root and media must be app-private.
 */
public final class ChatStore {
    public static final String LOCAL_ONLY = "local-only";
    public static final String DEMO_HISTORY = "demo-history";
    public static final String DELETED_MESSAGE_TEXT = "حُذفت محليًا";
    public static final String INITIAL_COMPANY_ID = "demo-nour";
    public static final int MAX_ATTACHMENTS = 20;
    public static final int MAX_TEXT_LENGTH = 20000;
    public static final int MAX_GROUP_TITLE_LENGTH = 80;
    private static final long MAX_STATE_BYTES = 32L * 1024L * 1024L;
    private static final int FORMAT_VERSION = 3;
    private static final String LOCAL_GROUP_PREFIX = "local-group-";
    private final File stateFile;
    private final File internalRoot;
    private volatile State state;
    private final Object writeLock = new Object();
    private StoreJournal journal;
    private boolean journalFormat;
    private volatile boolean writeDisabled;
    private final Map<Message,String> normalizedMessageCache = new LinkedHashMap<Message,String>(128,0.75f,true) {
        @Override protected boolean removeEldestEntry(Map.Entry<Message,String> e){return size()>512;}
    };
    public boolean requiresReopen(){return writeDisabled;}
    public ChatStore reopen()throws IOException{return new ChatStore(stateFile);}

    public ChatStore(File stateFile) throws IOException {
        if (stateFile == null) throw new IllegalArgumentException("State file is required");
        this.stateFile = stateFile.getCanonicalFile();
        this.internalRoot = this.stateFile.getParentFile();
        if (internalRoot == null) throw new IllegalArgumentException("State file needs a parent");
        if (!internalRoot.isDirectory() && !internalRoot.mkdirs()) {
            throw new IOException("Cannot create internal state directory");
        }
        try {
        journal = new StoreJournal(this.stateFile);
        journalFormat = this.stateFile.exists() && StoreJournal.isJournal(this.stateFile);
        if (this.stateFile.exists()) {
            State loaded = StoreJournal.isJournal(this.stateFile) ? decodeRecords(journal.read()) : readState(this.stateFile);
            validateState(loaded);
            // Older files omitted group membership and/or local undo records. Upgrade only in
            // memory until the next successful write; opening history never replaces its file.
            state = new State(loaded);
        } else {
            State initial = seed();
            persist(initial);
            state = initial;
        }
        } catch (OutOfMemoryError | StackOverflowError unavailable) {
            // Last-resort startup boundary only. It is not a pre-allocation or capacity guarantee.
            // Never turn an existing unreadable history into a fresh seeded database.
            throw new IOException("Local history exceeds available runtime resources; original preserved", unavailable);
        }
    }

    public List<Company> companies() {
        State state = this.state;
        return immutable(state.companies.values());
    }

    public Company company(String companyId) {
        State state = this.state;
        Company company = state.companies.get(companyId);
        if (company == null) throw new IllegalArgumentException("Unknown company");
        return company;
    }

    public List<Conversation> conversations(String companyId) {
        State state = this.state;
        company(companyId);
        List<Conversation> result = new ArrayList<Conversation>();
        for (Conversation conversation : state.conversations.values()) {
            if (companyId.equals(conversation.companyId)) result.add(conversation);
        }
        return immutable(result);
    }

    public Conversation conversation(String companyId, String conversationId) {
        State state = this.state;
        return target(state, companyId, conversationId);
    }

    /**
     * Creates an offline demo group only. Selected members are synthetic person conversations
     * from the explicit company; the current demo user is included implicitly. No invitations
     * or network messages are sent. The new group starts with an empty local history.
     */
    public Conversation createDemoGroup(String companyId, String title,
                                                      List<String> memberConversationIds) throws IOException {
        synchronized (writeLock) {
        Company company = company(companyId);
        String checkedTitle = checkedGroupTitle(title);
        List<String> members = checkedGroupMembers(state, companyId, memberConversationIds);
        String id;
        do { id = LOCAL_GROUP_PREFIX + UUID.randomUUID().toString(); }
        while (state.conversations.containsKey(id));
        Conversation conversation = new Conversation(id, companyId, checkedTitle,
                groupSubtitle(members.size()), "group", 0, company.avatarHue);
        State candidate = new State(state);
        candidate.conversations.put(id, conversation);
        candidate.messages.put(id, new ArrayList<Message>());
        candidate.demoGroupMembers.put(id, members);
        commit(candidate);
        return conversation;

        }
    }

    /** Selected person IDs for a locally created group, excluding the implicit current user. */
    public List<String> groupMemberConversationIds(String companyId, String conversationId) {
        State state = this.state;
        target(state, companyId, conversationId);
        List<String> members = state.demoGroupMembers.get(conversationId);
        // Seed conversations have no selected-membership metadata.
        return members == null ? Collections.<String>emptyList() : immutable(members);
    }

    /** Search remains cross-company; each result carries its own explicit company identity. */
    public List<Recipient> searchRecipients(String query) {
        State state = this.state;
        String normalized = normalize(query == null ? "" : query).trim();
        String[] terms = normalized.isEmpty() ? new String[0] : normalized.split("\\s+");
        List<Recipient> results = new ArrayList<Recipient>();
        for (Conversation conversation : state.conversations.values()) {
            Company company = state.companies.get(conversation.companyId);
            String haystack = normalize(company.name + " " + company.subtitle + " "
                    + conversation.title + " " + conversation.subtitle);
            boolean matches = true;
            for (String term : terms) if (!haystack.contains(term)) matches = false;
            if (matches) results.add(new Recipient(company, conversation));
        }
        return immutable(results);
    }

    public Draft draft(String companyId, String conversationId) {
        State state = this.state;
        target(state, companyId, conversationId);
        Draft draft = state.drafts.get(key(companyId, conversationId));
        return draft == null ? new Draft("", Collections.<Attachment>emptyList(), null) : draft;
    }

    public void setDraft(String companyId, String conversationId, String text,List<Attachment> attachments)throws IOException {
        synchronized(writeLock){setDraft(companyId,conversationId,text,attachments,draft(companyId,conversationId).replyToMessageId);}
    }

    /** Changing or clearing a reply selection never changes this conversation's text or files. */
    public void setReplyTarget(String companyId, String conversationId,
                                             String messageIdOrNull) throws IOException {
        synchronized (writeLock) {
        target(state, companyId, conversationId);
        String replyId = messageIdOrNull == null ? null
                : targetMessage(state, companyId, conversationId, messageIdOrNull).id;
        Draft previous = draft(companyId, conversationId);
        Draft draft = new Draft(previous.text, previous.attachments, replyId);
        State candidate = new State(state);
        String key = key(companyId, conversationId);
        if (empty(draft.text, draft.attachments) && replyId == null) candidate.drafts.remove(key);
        else candidate.drafts.put(key, draft);
        commit(candidate);

        }
    }

    /** A message lookup must include the exact company and conversation that own it. */
    public Message message(String companyId, String conversationId, String messageId) {
        State state = this.state;
        return targetMessage(state, companyId, conversationId, messageId);
    }

    /** Only this demo user's locally created messages can be deleted. Invalid scopes/IDs throw. */
    public boolean canDeleteMessage(String companyId, String conversationId, String messageId) {
        State state = this.state;
        Message message = targetMessage(state, companyId, conversationId, messageId);
        return message.mine && LOCAL_ONLY.equals(message.status) && !message.deleted;
    }

    /**
     * Call only after explicit local-delete confirmation. Replaces the public payload with a
     * tombstone in the same position; the app-private undo record is never returned by reads.
     * Repeating the same delete is a no-op. This does not delete any file, including exported files.
     */
    public Message deleteMessageLocally(String companyId, String conversationId,
                                                      String messageId) throws IOException {
        synchronized (writeLock) {
        Message original = targetMessage(state, companyId, conversationId, messageId);
        requireLocalOwnership(original);
        if (original.deleted) return original;
        Message tombstone = new Message(original.id, original.companyId, original.conversationId,
                "", Collections.<Attachment>emptyList(), original.mine, original.senderName,
                original.createdAt, original.status, original.sourceShareId, null, true);
        State candidate = replacingMessage(tombstone);
        candidate.deletedMessages.put(original.id, original);
        commit(candidate);
        return tombstone;

        }
    }

    /** Restores the same local message/position from its persisted undo record; retries are no-ops. */
    public Message undoLocalDeletion(String companyId, String conversationId,
                                                  String messageId) throws IOException {
        synchronized (writeLock) {
        Message current = targetMessage(state, companyId, conversationId, messageId);
        requireLocalOwnership(current);
        if (!current.deleted) return current;
        Message original = state.deletedMessages.get(current.id);
        if (original == null) throw new IllegalStateException("Missing local deletion undo record");
        State candidate = replacingMessage(original);
        candidate.deletedMessages.remove(current.id);
        commit(candidate);
        return original;

        }
    }

    private static void requireLocalOwnership(Message message) {
        if (!message.mine || !LOCAL_ONLY.equals(message.status)) {
            throw new IllegalArgumentException("Only your local messages can be deleted or restored");
        }
    }

    private State replacingMessage(Message replacement) {
        State candidate = new State(state);
        List<Message> messages = new ArrayList<Message>(state.messages.get(replacement.conversationId));
        for (int i = 0; i < messages.size(); i++) {
            if (messages.get(i).id.equals(replacement.id)) {
                messages.set(i, replacement);
                candidate.messages.put(replacement.conversationId, messages);
                return candidate;
            }
        }
        throw new IllegalArgumentException("Message does not belong to selected conversation");
    }

    /** Full persisted-history search, independent of the currently loaded UI page. */
    public List<Message> searchMessages(String companyId, String conversationId, String query) {
        State state = this.state;
        target(state, companyId, conversationId);
        String normalized = normalize(query == null ? "" : query).trim();
        String[] terms = normalized.isEmpty() ? new String[0] : normalized.split("\\s+");
        List<Message> result = new ArrayList<Message>();
        for (Message message : state.messages.get(conversationId)) {
            StringBuilder searchable = new StringBuilder(message.text);
            for (Attachment attachment : message.attachments) searchable.append(' ').append(attachment.name);
            String haystack = normalize(searchable.toString());
            boolean matches = true;
            for (String term : terms) if (!haystack.contains(term)) matches = false;
            if (matches) result.add(message);
        }
        Collections.sort(result, new Comparator<Message>() {
            @Override public int compare(Message first, Message second) {
                return Long.compare(first.createdAt, second.createdAt);
            }
        });
        return immutable(result);
    }

    /**
     * Plain-text export for an explicit UI copy action. Includes this conversation's persisted
     * messages only, not drafts, pending shares, private attachment paths, or binary content.
     */
    public String conversationTranscript(String companyId, String conversationId) {
        State state = this.state;
        Conversation conversation = target(state, companyId, conversationId);
        SimpleDateFormat timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss 'UTC'", Locale.ROOT);
        timestamp.setTimeZone(TimeZone.getTimeZone("UTC"));
        StringBuilder transcript = new StringBuilder("سجل محادثة محلي تجريبي\nالشركة: ")
                .append(state.companies.get(companyId).name).append("\nالمحادثة: ")
                .append(conversation.title).append('\n');
        for (Message message : searchMessages(companyId, conversationId, "")) {
            transcript.append('\n').append('[').append(timestamp.format(new Date(message.createdAt)))
                    .append("] ").append(message.senderName).append('\n');
            if (message.deleted) {
                transcript.append(DELETED_MESSAGE_TEXT).append('\n');
                continue;
            }
            if (message.replyToMessageId != null) {
                Message quoted = targetMessage(state, companyId, conversationId, message.replyToMessageId);
                transcript.append("رد على ").append(quoted.senderName).append(": ")
                        .append(replyPreview(quoted)).append('\n');
            }
            if (!message.text.isEmpty()) transcript.append(message.text).append('\n');
            for (Attachment attachment : message.attachments) {
                transcript.append("مرفق: ").append(attachment.name).append('\n');
            }
        }
        return transcript.toString();
    }

    public Message send(String companyId, String conversationId) throws IOException {
        synchronized (writeLock) {
        return send(companyId, conversationId, UUID.randomUUID().toString());

        }
    }

    /** A retry with the same UUID returns the original message and does not clear a newer draft. */
    public Message send(String companyId, String conversationId,
                                     String clientUuid) throws IOException {
        synchronized (writeLock) {
        target(state, companyId, conversationId);
        String id = checkedUuid(clientUuid);
        Message duplicate = findMessage(id);
        if (duplicate != null) return checkedDuplicate(duplicate, companyId, conversationId, null);
        Draft draft = draft(companyId, conversationId);
        requireContent(draft.text, draft.attachments);
        Message message = localMessage(id, companyId, conversationId, draft.text,
                checkedAttachments(draft.attachments), null, draft.replyToMessageId);
        State candidate = withMessage(message);
        candidate.drafts.remove(key(companyId, conversationId));
        commit(candidate);
        return message;

        }
    }

    /** Newest page when beforeMessageId is null; pages are returned oldest-to-newest. */
    public Page page(String companyId, String conversationId,
                                   String beforeMessageId, int limit) {
        State state = this.state;
        target(state, companyId, conversationId);
        if (limit < 1 || limit > 200) throw new IllegalArgumentException("Page limit must be 1–200");
        List<Message> all = state.messages.get(conversationId);
        int end = all.size();
        if (beforeMessageId != null) {
            end = -1;
            for (int i = 0; i < all.size(); i++) {
                if (beforeMessageId.equals(all.get(i).id)) { end = i; break; }
            }
            if (end < 0) throw new IllegalArgumentException("Cursor does not belong to this conversation");
        }
        int start = Math.max(0, end - limit);
        List<Message> messages = immutable(all.subList(start, end));
        boolean hasMore = start > 0;
        return new Page(messages, hasMore, hasMore ? all.get(start).id : null);
    }

    public int messageCount(String companyId, String conversationId) {
        State state = this.state;
        target(state, companyId, conversationId);
        return state.messages.get(conversationId).size();
    }

    public Message lastMessage(String companyId, String conversationId) {
        State state = this.state;
        target(state, companyId, conversationId);
        List<Message> messages = state.messages.get(conversationId);
        return messages.isEmpty() ? null : messages.get(messages.size() - 1);
    }

    public PendingShare pendingShare() {
        State state = this.state; return state.pendingShare; }

    /** Cleanup references only: includes private undo files; never use this collection for display/export. */
    public Set<String> attachmentPaths() {
        State state = this.state;
        Set<String> paths = new HashSet<String>();
        for (List<Message> messages : state.messages.values()) {
            for (Message message : messages) for (Attachment a : message.attachments) paths.add(a.path);
        }
        for (Message original : state.deletedMessages.values()) {
            for (Attachment a : original.attachments) paths.add(a.path);
        }
        for (Draft draft : state.drafts.values()) for (Attachment a : draft.attachments) paths.add(a.path);
        if (state.pendingShare != null) for (Attachment a : state.pendingShare.attachments) paths.add(a.path);
        return Collections.unmodifiableSet(paths);
    }


    /** An existing unassigned import must be sent or explicitly canceled before another begins. */
    public PendingShare stagePendingShare(String text,
                                                        List<Attachment> attachments) throws IOException {
        synchronized (writeLock) {
        if (state.pendingShare != null) throw new IllegalStateException("An unassigned share is already pending");
        String checked = checkedText(text);
        List<Attachment> checkedFiles = checkedAttachments(attachments);
        requireContent(checked, checkedFiles);
        PendingShare pending = new PendingShare(UUID.randomUUID().toString(), checked, checkedFiles);
        State candidate = new State(state);
        candidate.pendingShare = pending;
        commit(candidate);
        return pending;

        }
    }

    /** Cancellation never reads or changes any conversation's draft. Idempotent after cancel. */
    public void cancelPendingShare(String shareId) throws IOException {
        synchronized (writeLock) {
        String checkedShareId = checkedUuid(shareId);
        if (state.pendingShare == null) return;
        if (!state.pendingShare.id.equals(checkedShareId)) throw new IllegalArgumentException("Stale share id");
        State candidate = new State(state);
        candidate.pendingShare = null;
        candidate.resolvedShares.put(checkedShareId, "resolved");
        commit(candidate);

        }
    }

    /**
     * Called only after the user explicitly confirms the selected company and conversation.
     * Picker/preview state belongs to the UI. It never contaminates a conversation draft.
     * Null overrides retain the original share text/files; empty overrides remove that part.
     */
    public Message sendPendingShare(String shareId, String companyId,
                                                  String conversationId, String textOverride,
                                                  List<Attachment> attachmentsOverride,
                                                  String clientUuid) throws IOException {
        synchronized (writeLock) {
        target(state, companyId, conversationId);
        String checkedShareId = checkedUuid(shareId);
        String id = checkedUuid(clientUuid);
        Message duplicate = findMessage(id);
        if (duplicate != null) return checkedDuplicate(duplicate, companyId, conversationId, checkedShareId);
        PendingShare pending = state.pendingShare;
        if (pending == null || !pending.id.equals(checkedShareId)) {
            throw new IllegalArgumentException("Share is no longer pending");
        }
        String text = checkedText(textOverride == null ? pending.text : textOverride);
        List<Attachment> attachments = checkedAttachments(attachmentsOverride == null
                ? pending.attachments : attachmentsOverride);
        requireContent(text, attachments);
        Message message = localMessage(id, companyId, conversationId, text, attachments, checkedShareId, null);
        State candidate = withMessage(message);
        candidate.pendingShare = null;
        candidate.resolvedShares.put(checkedShareId, "resolved");
        commit(candidate);
        return message;

        }
    }

    private State withMessage(Message message) {
        State candidate = new State(state);
        List<Message> messages = new ArrayList<Message>(state.messages.get(message.conversationId));
        messages.add(message);
        candidate.messages.put(message.conversationId, messages);
        return candidate;
    }

    private Message localMessage(String id, String companyId, String conversationId, String text,
                                 List<Attachment> attachments, String sourceShareId, String replyToMessageId) {
        return new Message(id, companyId, conversationId, text, attachments, true,
                "أنت", System.currentTimeMillis(), LOCAL_ONLY, sourceShareId, replyToMessageId);
    }

    private Message findMessage(String id) {
        for (List<Message> messages : state.messages.values()) {
            for (Message message : messages) if (id.equals(message.id)) return message;
        }
        return null;
    }

    private static Message checkedDuplicate(Message existing, String companyId,
                                             String conversationId, String sourceShareId) {
        boolean sameSource = sourceShareId == null ? existing.sourceShareId == null
                : sourceShareId.equals(existing.sourceShareId);
        if (!existing.companyId.equals(companyId) || !existing.conversationId.equals(conversationId)
                || !LOCAL_ONLY.equals(existing.status) || !sameSource) {
            throw new IllegalArgumentException("Message UUID is already used by a different action");
        }
        return existing;
    }

    private void commit(State candidate) throws IOException {
        persist(candidate);
        state = candidate;
    }

    private void persist(State candidate) throws IOException {
        if (writeDisabled) throw new IOException("Storage must be reopened before retrying an uncertain commit");
        List<StoreJournal.Record> changes = encodeChanges(journalFormat ? state : null, candidate);
        if (!changes.isEmpty()) {
            try { journal.commit(changes); journalFormat = true; }
            catch (StoreJournal.CommitUncertainException failure) { writeDisabled = true; throw failure; }
        }
    }

    private State readState(File file) throws IOException {
        if (!file.isFile() || file.length() <= 0 || file.length() > MAX_STATE_BYTES) throw new IOException("Invalid local history file");
        try {
            // Preflight and ObjectInputStream consume the same bounded immutable bytes.
            // Never reopen an unchecked second version of a changing legacy root.
            ByteArrayOutputStream bytes=new ByteArrayOutputStream((int)Math.min(file.length(),65536));
            try(FileInputStream in=new FileInputStream(file)) {
                byte[] block=new byte[32768];int n;long count=0;
                while((n=in.read(block))!=-1){count+=n;if(count>MAX_STATE_BYTES)throw new IOException("Legacy snapshot exceeds bound");bytes.write(block,0,n);}
            }
            byte[] snapshot=bytes.toByteArray();LegacyPreflight.validate(snapshot);
            try(ObjectInputStream input=new SafeObjectInputStream(new ByteArrayInputStream(snapshot))) {
                Object loaded=input.readObject();if(!(loaded instanceof State))throw new IOException("Unsupported local history object");
                if(input.read()!=-1)throw new IOException("Unexpected trailing snapshot bytes");return (State)loaded;
            }
        } catch(ClassNotFoundException e) {throw new IOException("Unsupported local history format",e);}
        catch(OutOfMemoryError | StackOverflowError e) {throw new IOException("Local history could not be safely loaded; original preserved",e);}
    }

    /** Rejects unexpected classes; this private snapshot is never imported from share intents. */
    private static final class SafeObjectInputStream extends ObjectInputStream {
        private static final Set<String> ALLOWED = new HashSet<String>(Arrays.asList(
                State.class.getName(), Company.class.getName(), Conversation.class.getName(),
                Attachment.class.getName(), Draft.class.getName(), Message.class.getName(),
                PendingShare.class.getName(), "java.util.LinkedHashMap", "java.util.HashMap",
                "java.util.ArrayList", "java.util.Collections$UnmodifiableRandomAccessList",
                "java.util.Collections$UnmodifiableList", "java.util.Collections$UnmodifiableCollection",
                "java.lang.String", "[Ljava.lang.Object;"));
        SafeObjectInputStream(java.io.InputStream stream) throws IOException { super(stream); }
        @Override protected Class<?> resolveClass(ObjectStreamClass descriptor)
                throws IOException, ClassNotFoundException {
            String name=com.baseer.bwork.legacy.compat.LegacyIdentity.canonicalClass(descriptor.getName());
            if (!ALLOWED.contains(name)) {
                throw new InvalidClassException("Unexpected class in local history", descriptor.getName());
            }
            // Package-only alias for the seven preflight-validated historical DTOs.
            // Keep incoming field descriptors/UIDs intact; never rewrite source bytes.
            if (!name.equals(descriptor.getName())) return Class.forName(name, false, ChatStore.class.getClassLoader());
            return super.resolveClass(descriptor);
        }
        @Override protected Class<?> resolveProxyClass(String[] interfaces) throws IOException {
            throw new InvalidClassException("Proxy objects are not a local history format");
        }
    }

    private void validateState(State loaded) throws IOException {
        try {
            if ((loaded.version < 1 || loaded.version > FORMAT_VERSION) || loaded.companies == null
                    || loaded.conversations == null || loaded.messages == null || loaded.drafts == null
                    || loaded.companies.size() != 3 || loaded.conversations.size() < 15
                    || (loaded.version >= 2 && loaded.demoGroupMembers == null)
                    || (loaded.version == FORMAT_VERSION && loaded.deletedMessages == null)
                    || (loaded.version < 3 && loaded.deletedMessages != null && !loaded.deletedMessages.isEmpty())
                    || (loaded.version == 1 && (loaded.conversations.size() != 15
                        || (loaded.demoGroupMembers != null && !loaded.demoGroupMembers.isEmpty())))) {
                throw new IllegalArgumentException("Invalid snapshot structure");
            }
            State expected = seed();
            if (!expected.companies.keySet().equals(loaded.companies.keySet())
                    || !loaded.conversations.keySet().containsAll(expected.conversations.keySet())
                    || !loaded.conversations.keySet().equals(loaded.messages.keySet())) {
                throw new IllegalArgumentException("Unknown synthetic identities");
            }
            for (Map.Entry<String, Company> entry : loaded.companies.entrySet()) {
                Company company = entry.getValue();
                Company reference = expected.companies.get(entry.getKey());
                if (company == null || !entry.getKey().equals(company.id)
                        || !reference.name.equals(company.name) || !reference.subtitle.equals(company.subtitle)
                        || reference.avatarHue != company.avatarHue) {
                    throw new IllegalArgumentException("Invalid company identity");
                }
            }
            Set<String> localGroupIds = new HashSet<String>();
            for (Map.Entry<String, Conversation> entry : loaded.conversations.entrySet()) {
                Conversation conversation = entry.getValue();
                Conversation reference = expected.conversations.get(entry.getKey());
                if (conversation == null || !entry.getKey().equals(conversation.id)) {
                    throw new IllegalArgumentException("Invalid conversation identity");
                }
                if (reference != null) {
                    if (!reference.companyId.equals(conversation.companyId)
                            || !reference.title.equals(conversation.title)
                            || !reference.subtitle.equals(conversation.subtitle)
                            || !reference.kind.equals(conversation.kind)
                            || reference.unread != conversation.unread
                            || reference.avatarHue != conversation.avatarHue) {
                        throw new IllegalArgumentException("Invalid synthetic conversation identity");
                    }
                } else {
                    if (loaded.version < 2 || !conversation.id.startsWith(LOCAL_GROUP_PREFIX)
                            || !checkedUuid(conversation.id.substring(LOCAL_GROUP_PREFIX.length()))
                                .equals(conversation.id.substring(LOCAL_GROUP_PREFIX.length()))
                            || !"group".equals(conversation.kind) || conversation.unread != 0
                            || !checkedGroupTitle(conversation.title).equals(conversation.title)) {
                        throw new IllegalArgumentException("Invalid local group identity");
                    }
                    List<String> members = checkedGroupMembers(loaded, conversation.companyId,
                            loaded.demoGroupMembers.get(conversation.id));
                    if (!groupSubtitle(members.size()).equals(conversation.subtitle)
                            || conversation.avatarHue != loaded.companies.get(conversation.companyId).avatarHue) {
                        throw new IllegalArgumentException("Invalid local group metadata");
                    }
                    localGroupIds.add(conversation.id);
                }
            }
            if (loaded.demoGroupMembers != null && !localGroupIds.equals(loaded.demoGroupMembers.keySet())) {
                throw new IllegalArgumentException("Orphan or missing local group membership");
            }
            Set<String> ids = new HashSet<String>();
            Set<String> deletedIds = new HashSet<String>();
            for (Map.Entry<String, List<Message>> entry : loaded.messages.entrySet()) {
                if (entry.getValue() == null) throw new IllegalArgumentException("Missing message collection");
                Set<String> previousMessageIds = new HashSet<String>();
                for (Message message : entry.getValue()) {
                    if (message == null || !entry.getKey().equals(message.conversationId)) {
                        throw new IllegalArgumentException("Message in wrong conversation");
                    }
                    target(loaded, message.companyId, message.conversationId);
                    if (!checkedUuid(message.id).equals(message.id) || !ids.add(message.id)) {
                        throw new IllegalArgumentException("Duplicate or noncanonical UUID");
                    }
                    checkedText(message.text);
                    checkedAttachments(message.attachments);
                    if (message.senderName == null || message.createdAt < 0
                            || (!LOCAL_ONLY.equals(message.status) && !DEMO_HISTORY.equals(message.status))
                            || (LOCAL_ONLY.equals(message.status) && !message.mine)
                            || (localGroupIds.contains(message.conversationId) && !LOCAL_ONLY.equals(message.status))) {
                        throw new IllegalArgumentException("Invalid local message");
                    }
                    if (message.sourceShareId != null && !checkedUuid(message.sourceShareId).equals(message.sourceShareId)) {
                        throw new IllegalArgumentException("Invalid source share UUID");
                    }
                    validateReply(message, previousMessageIds);
                    if (message.deleted) {
                        if (loaded.version < 3 || !message.mine || !LOCAL_ONLY.equals(message.status)
                                || !message.text.isEmpty() || !message.attachments.isEmpty()
                                || message.replyToMessageId != null) {
                            throw new IllegalArgumentException("Invalid local message tombstone");
                        }
                        Message original = loaded.deletedMessages.get(message.id);
                        if (original == null || original.deleted || !original.mine
                                || !message.id.equals(original.id)
                                || !message.companyId.equals(original.companyId)
                                || !message.conversationId.equals(original.conversationId)
                                || !message.senderName.equals(original.senderName)
                                || !message.status.equals(original.status)
                                || message.createdAt != original.createdAt
                                || !sameNullable(message.sourceShareId, original.sourceShareId)) {
                            throw new IllegalArgumentException("Invalid local deletion undo identity");
                        }
                        checkedText(original.text);
                        checkedAttachments(original.attachments);
                        requireContent(original.text, original.attachments);
                        validateReply(original, previousMessageIds);
                        deletedIds.add(message.id);
                    }
                    previousMessageIds.add(message.id);
                }
            }
            if (loaded.deletedMessages != null && !deletedIds.equals(loaded.deletedMessages.keySet())) {
                throw new IllegalArgumentException("Orphan or missing local deletion undo record");
            }
            for (Map.Entry<String, Draft> entry : loaded.drafts.entrySet()) {
                Conversation found = null;
                for (Conversation conversation : loaded.conversations.values()) {
                    if (key(conversation.companyId, conversation.id).equals(entry.getKey())) found = conversation;
                }
                if (found == null || entry.getValue() == null) throw new IllegalArgumentException("Orphan draft");
                checkedText(entry.getValue().text);
                checkedAttachments(entry.getValue().attachments);
                if (entry.getValue().replyToMessageId != null) {
                    targetMessage(loaded, found.companyId, found.id, entry.getValue().replyToMessageId);
                }
            }
            if (loaded.readMarkers != null) for (Map.Entry<String,String> e:loaded.readMarkers.entrySet()) {
                boolean found=false;
                for(Conversation c:loaded.conversations.values()) if(key(c.companyId,c.id).equals(e.getKey())) {
                    if(e.getValue()==null)throw new IllegalArgumentException("Invalid read marker");
                    if(!e.getValue().isEmpty())targetMessage(loaded,c.companyId,c.id,e.getValue());found=true;break;
                }
                if(!found)throw new IllegalArgumentException("Read marker has no conversation");
            }
            if (loaded.resolvedShares != null) for(Map.Entry<String,String> e:loaded.resolvedShares.entrySet()) {
                checkedUuid(e.getKey());if(!"resolved".equals(e.getValue()))throw new IllegalArgumentException("Invalid terminal share state");
            }
            if (loaded.pendingShare != null) {
                checkedUuid(loaded.pendingShare.id);
                checkedText(loaded.pendingShare.text);
                checkedAttachments(loaded.pendingShare.attachments);
                if (!loaded.pendingShare.previewEdited) requireContent(loaded.pendingShare.text, loaded.pendingShare.attachments);
            }
        } catch (RuntimeException e) {
            throw new IOException("Local history is damaged or incompatible; existing file was preserved", e);
        }
    }

    private static boolean sameNullable(String first, String second) {
        return first == null ? second == null : first.equals(second);
    }

    private static void validateReply(Message message, Set<String> previousMessageIds) {
        if (message.replyToMessageId != null && (!LOCAL_ONLY.equals(message.status)
                || message.sourceShareId != null
                || !checkedUuid(message.replyToMessageId).equals(message.replyToMessageId)
                || !previousMessageIds.contains(message.replyToMessageId))) {
            throw new IllegalArgumentException("Reply must reference an earlier message in the same conversation");
        }
    }

    private List<Attachment> checkedAttachments(List<Attachment> attachments) throws IOException {
        if (attachments == null) throw new IllegalArgumentException("Attachment list is required");
        if (attachments.size() > MAX_ATTACHMENTS) throw new IllegalArgumentException("Too many attachments");
        Set<String> ids = new HashSet<String>();
        for (Attachment attachment : attachments) {
            if (attachment == null) throw new IllegalArgumentException("Null attachment");
            validateAttachment(attachment);
            if (!ids.add(attachment.id)) throw new IllegalArgumentException("Duplicate attachment id");
            File local = new File(attachment.path).getCanonicalFile();
            String rootPrefix = internalRoot.getPath() + File.separator;
            if (!local.getPath().startsWith(rootPrefix) || local.equals(stateFile)) {
                throw new IllegalArgumentException("Attachment must be imported into private local storage");
            }
        }
        return immutable(attachments);
    }

    private static void validateAttachment(Attachment attachment) {
        checkedUuid(attachment.id);
        if (attachment.path == null || !new File(attachment.path).isAbsolute()
                || attachment.name == null || attachment.name.trim().isEmpty()
                || attachment.name.length() > 255 || attachment.name.contains("/") || attachment.name.contains("\\")
                || attachment.mime == null || attachment.mime.trim().isEmpty() || attachment.mime.length() > 200
                || attachment.size < 0 || (attachment.sha256 != null && !attachment.sha256.matches("[a-f0-9]{64}"))) {
            throw new IllegalArgumentException("Invalid local attachment metadata");
        }
    }

    private static Conversation target(State state, String companyId, String conversationId) {
        if (companyId == null || conversationId == null || !state.companies.containsKey(companyId)) {
            throw new IllegalArgumentException("Unknown company");
        }
        Conversation conversation = state.conversations.get(conversationId);
        if (conversation == null || !companyId.equals(conversation.companyId)) {
            throw new IllegalArgumentException("Conversation does not belong to selected company");
        }
        return conversation;
    }

    private static Message targetMessage(State state, String companyId, String conversationId, String messageId) {
        target(state, companyId, conversationId);
        String checkedId = checkedUuid(messageId);
        for (Message message : state.messages.get(conversationId)) if (checkedId.equals(message.id)) return message;
        throw new IllegalArgumentException("Message does not belong to selected conversation");
    }

    private static String replyPreview(Message message) {
        if (message.deleted) return DELETED_MESSAGE_TEXT;
        String preview = message.text;
        if (preview.trim().isEmpty()) {
            StringBuilder files = new StringBuilder();
            for (Attachment attachment : message.attachments) {
                if (files.length() > 0) files.append(", ");
                files.append(attachment.name);
            }
            preview = files.toString();
        }
        preview = preview.replace('\n', ' ').replace('\r', ' ').trim();
        return preview.length() <= 200 ? preview : preview.substring(0, 200) + "…";
    }

    private static String key(String companyId, String conversationId) { return companyId + ":" + conversationId; }
    private static String groupSubtitle(int selectedMembers) {
        return "مجموعة محلية تجريبية · " + (selectedMembers + 1) + " أعضاء";
    }
    private static String checkedGroupTitle(String title) {
        if (title == null) throw new IllegalArgumentException("Group title is required");
        String result = title.replaceAll("^[\\s\\p{Z}]+|[\\s\\p{Z}]+$", "");
        if (result.isEmpty() || result.length() > MAX_GROUP_TITLE_LENGTH) {
            throw new IllegalArgumentException("Group title must contain 1–80 characters");
        }
        boolean visible = false;
        for (int offset = 0; offset < result.length();) {
            int point = result.codePointAt(offset);
            int type = Character.getType(point);
            if (Character.isISOControl(point) || type == Character.LINE_SEPARATOR
                    || type == Character.PARAGRAPH_SEPARATOR || type == Character.SURROGATE
                    || point == 0x061c || point == 0x200e || point == 0x200f
                    || (point >= 0x202a && point <= 0x202e) || (point >= 0x2066 && point <= 0x2069)) {
                throw new IllegalArgumentException("Group title must be a single readable line");
            }
            if (!Character.isWhitespace(point) && !Character.isSpaceChar(point)
                    && type != Character.FORMAT && type != Character.NON_SPACING_MARK
                    && type != Character.COMBINING_SPACING_MARK && type != Character.ENCLOSING_MARK) visible = true;
            offset += Character.charCount(point);
        }
        if (!visible) throw new IllegalArgumentException("Group title must contain visible text");
        return result;
    }
    private static List<String> checkedGroupMembers(State source, String companyId, List<String> members) {
        if (!source.companies.containsKey(companyId) || members == null || members.isEmpty()) {
            throw new IllegalArgumentException("Select a company and at least one person");
        }
        Set<String> distinct = new HashSet<String>();
        for (String id : members) {
            Conversation person = target(source, companyId, id);
            if (!"person".equals(person.kind) || !distinct.add(id)) {
                throw new IllegalArgumentException("Group members must be distinct people from the selected company");
            }
        }
        return immutable(members);
    }
    private static String checkedText(String text) {
        if (text == null || text.length() > MAX_TEXT_LENGTH) throw new IllegalArgumentException("Invalid message text");
        return text;
    }
    private static String checkedUuid(String value) {
        if (value == null || value.length() != 36) throw new IllegalArgumentException("A full UUID is required");
        String normalized = UUID.fromString(value).toString();
        if (!normalized.equals(value.toLowerCase(Locale.ROOT))) throw new IllegalArgumentException("Invalid UUID");
        return normalized;
    }
    private static boolean empty(String text, List<Attachment> attachments) {
        return text.trim().isEmpty() && attachments.isEmpty();
    }
    private static void requireContent(String text, List<Attachment> attachments) {
        if (empty(text, attachments)) throw new IllegalArgumentException("Cannot store an empty message");
    }
    private static <T> List<T> immutable(java.util.Collection<T> values) {
        return Collections.unmodifiableList(new ArrayList<T>(values));
    }
    private static String normalize(String text) {
        return Normalizer.normalize(text, Normalizer.Form.NFD).replaceAll("\\p{M}+", "")
                .replace('أ', 'ا').replace('إ', 'ا').replace('آ', 'ا').replace('ى', 'ي')
                .replace("ـ", "").toLowerCase(Locale.ROOT);
    }

    private static State seed() {
        State state = new State();
        Company[] companies = {
                new Company("demo-nour", "شركة النور التجريبية", "بيئة عرض · بيانات وهمية", 205),
                new Company("demo-madar", "شركة مدار التجريبية", "بيئة عرض · بيانات وهمية", 276),
                new Company("demo-ofuq", "شركة الأفق التجريبية", "بيئة عرض · بيانات وهمية", 160)
        };
        String[] suffixes = {"ops", "sara", "omar", "design", "updates"};
        String[] titles = {"فريق العمليات", "سارة التجريبية", "عمر التجريبي", "فريق التصميم", "تحديثات المشروع"};
        String[] subtitles = {"مجموعة تجريبية · ٦ أعضاء", "شخص تجريبي · العمليات", "شخص تجريبي · التصميم",
                "مجموعة تجريبية · ٤ أعضاء", "محادثة تجريبية · فريق المشروع"};
        String[] kinds = {"group", "person", "person", "group", "chat"};
        String[] sample = {
                "صباح الخير، هل نراجع ترتيب المهام اليوم؟",
                "أكيد، جهزت ملاحظات الاجتماع في المسودة.",
                "يعطيكم العافية، نبدأ بمراجعة التصميم.",
                "ألوان الواجهة الجديدة واضحة ومريحة.",
                "سأشارككم الملف التجريبي بعد قليل.",
                "ممتاز، نتأكد من المرفقات قبل الإرسال.",
                "رتّبت الملاحظات حسب أولوية العمل.",
                "شكرًا لكم، نكمل المراجعة هنا."
        };
        long base = 1790809200000L; // Fixed synthetic timeline, 2026-10-01 UTC.
        for (int c = 0; c < companies.length; c++) {
            Company company = companies[c];
            state.companies.put(company.id, company);
            for (int t = 0; t < suffixes.length; t++) {
                String id = company.id + "-" + suffixes[t];
                Conversation conversation = new Conversation(id, company.id, titles[t], subtitles[t],
                        kinds[t], t == 0 ? 3 : (t == 1 ? 1 : 0), (company.avatarHue + t * 31) % 360);
                state.conversations.put(id, conversation);
                List<Message> messages = new ArrayList<Message>();
                int count = c == 0 && t == 0 ? 260 : 12 + t * 4;
                for (int m = 0; m < count; m++) {
                    boolean mine = m % 4 == 2;
                    String uuid = UUID.nameUUIDFromBytes((id + ":seed:" + m).getBytes(StandardCharsets.UTF_8)).toString();
                    String sender = mine ? "أنت (تجريبي)" : (t == 2 ? "عمر التجريبي" : "سارة التجريبية");
                    messages.add(new Message(uuid, company.id, id, sample[m % sample.length],
                            Collections.<Attachment>emptyList(), mine, sender, base + m * 180000L + t * 60000L,
                            DEMO_HISTORY, null));
                }
                state.messages.put(id, messages);
            }
        }
        return state;
    }

    /** Persisted local read marker; never a server receipt. */
    public int unreadCount(String companyId,String conversationId) {
        State snapshot=state; Conversation c=target(snapshot,companyId,conversationId);
        String marker=snapshot.readMarkers.get(key(companyId,conversationId));
        if(marker==null)return c.unread;
        List<Message> all=snapshot.messages.get(conversationId);boolean after=marker.isEmpty();int count=0;
        for(Message m:all){if(after&&!m.mine)count++;if(m.id.equals(marker))after=true;}
        return count;
    }
    public void markRead(String companyId,String conversationId)throws IOException {
        synchronized(writeLock){target(state,companyId,conversationId);List<Message> all=state.messages.get(conversationId);
            String marker=all.isEmpty()?"":all.get(all.size()-1).id;String k=key(companyId,conversationId);
            if(marker.equals(state.readMarkers.get(k)))return;State candidate=new State(state);candidate.readMarkers.put(k,marker);commit(candidate);}
    }
    public void setDraft(String companyId,String conversationId,String text,List<Attachment> attachments,String replyId)throws IOException {
        synchronized(writeLock){target(state,companyId,conversationId);if(replyId!=null)targetMessage(state,companyId,conversationId,replyId);
            Draft next=new Draft(checkedText(text),checkedAttachments(attachments),replyId);Draft old=draft(companyId,conversationId);
            if(sameDraft(old,next))return;State candidate=new State(state);String k=key(companyId,conversationId);
            if(empty(next.text,next.attachments)&&replyId==null)candidate.drafts.remove(k);else candidate.drafts.put(k,next);commit(candidate);}
    }
    public Message sendDraftSnapshot(String companyId,String conversationId,String text,List<Attachment> attachments,String replyId,String clientUuid)throws IOException {
        synchronized(writeLock){target(state,companyId,conversationId);String id=checkedUuid(clientUuid);Message found=findMessage(id);
            if(found!=null)return checkedDuplicate(found,companyId,conversationId,null);
            String checked=checkedText(text);List<Attachment> files=checkedAttachments(attachments);requireContent(checked,files);
            if(replyId!=null)targetMessage(state,companyId,conversationId,replyId);
            Message sent=localMessage(id,companyId,conversationId,checked,files,null,replyId);State candidate=withMessage(sent);
            candidate.drafts.remove(key(companyId,conversationId));commit(candidate);return sent;}
    }
    public Message findMessageByClientId(String companyId,String conversationId,String clientUuid){return findMessageByClientId(companyId,conversationId,clientUuid,null);}
    public Message findMessageByClientId(String companyId,String conversationId,String clientUuid,String sourceShareId){
        State snapshot=state;target(snapshot,companyId,conversationId);String id=checkedUuid(clientUuid);
        for(Message m:snapshot.messages.get(conversationId))if(id.equals(m.id))return checkedDuplicate(m,companyId,conversationId,sourceShareId);return null;
    }
    public boolean isPendingShareResolved(String shareId){return state.resolvedShares.containsKey(checkedUuid(shareId));}
    public void updatePendingSharePreview(String shareId,String text,List<Attachment> files)throws IOException {
        synchronized(writeLock){String id=checkedUuid(shareId);PendingShare p=state.pendingShare;
            if(p==null||!id.equals(p.id))throw new IllegalArgumentException("Share is no longer pending");
            PendingShare next=new PendingShare(id,checkedText(text),checkedAttachments(files),true);
            if(p.previewEdited&&p.text.equals(next.text)&&sameAttachments(p.attachments,next.attachments))return;
            State candidate=new State(state);candidate.pendingShare=next;commit(candidate);}
    }
    private static boolean sameDraft(Draft a,Draft b){return a.text.equals(b.text)&&sameNullable(a.replyToMessageId,b.replyToMessageId)&&sameAttachments(a.attachments,b.attachments);}
    private static boolean sameAttachments(List<Attachment>a,List<Attachment>b){if(a.size()!=b.size())return false;for(int i=0;i<a.size();i++){Attachment x=a.get(i),y=b.get(i);if(!x.id.equals(y.id)||!x.path.equals(y.path)||!x.name.equals(y.name)||!x.mime.equals(y.mime)||x.size!=y.size||!sameNullable(x.sha256,y.sha256))return false;}return true;}
    public Page pageAfter(String companyId,String conversationId,String afterMessageId,int limit){
        State snapshot=state;target(snapshot,companyId,conversationId);checkLimit(limit);List<Message> all=snapshot.messages.get(conversationId);int start=0;
        if(afterMessageId!=null){start=-1;for(int i=0;i<all.size();i++)if(afterMessageId.equals(all.get(i).id)){start=i+1;break;}if(start<0)throw new IllegalArgumentException("Unknown page cursor");}
        int end=Math.min(all.size(),start+limit);boolean more=end<all.size();return new Page(all.subList(start,end),more,more?all.get(end-1).id:null);
    }
    private static void checkLimit(int limit){if(limit<1||limit>200)throw new IllegalArgumentException("Limit must be1–200");}
    public SearchPage searchMessagePage(String companyId,String conversationId,String query,String afterId,int limit){return searchPage(companyId,conversationId,query,afterId,limit,false);}
    public SearchPage searchMessagePageBefore(String companyId,String conversationId,String query,String beforeId,int limit){return searchPage(companyId,conversationId,query,beforeId,limit,true);}
    private SearchPage searchPage(String companyId,String conversationId,String query,String cursor,int limit,boolean backwards){
        State snapshot=state;target(snapshot,companyId,conversationId);checkLimit(limit);List<Message> all=snapshot.messages.get(conversationId);
        String normalized=normalize(query==null?"":query).trim();if(normalized.isEmpty())return new SearchPage(Collections.<Message>emptyList(),false,null);
        String[] terms=normalized.split("\\s+");int start=backwards?all.size()-1:0;
        if(cursor!=null){int index=-1;for(int i=0;i<all.size();i++)if(cursor.equals(all.get(i).id)){index=i;break;}if(index<0)throw new IllegalArgumentException("Unknown search cursor");start=index+(backwards?-1:1);}
        List<Message> result=new ArrayList<Message>();boolean more=false;
        for(int i=start;i>=0&&i<all.size();i+=backwards?-1:1){if(Thread.currentThread().isInterrupted())break;Message m=all.get(i);if(m.deleted)continue;
            String hay=normalizedMessage(m);boolean match=true;for(String term:terms)if(!hay.contains(term)){match=false;break;}
            if(match){if(result.size()==limit){more=true;break;}result.add(m);}}
        String next=result.isEmpty()?null:result.get(result.size()-1).id;if(backwards)Collections.reverse(result);return new SearchPage(result,more,next);
    }
    private String normalizedMessage(Message message){
        synchronized(normalizedMessageCache){String found=normalizedMessageCache.get(message);if(found!=null)return found;}
        StringBuilder text=new StringBuilder(message.text);for(Attachment a:message.attachments)text.append(' ').append(a.name);
        String value=normalize(text.toString());synchronized(normalizedMessageCache){normalizedMessageCache.put(message,value);}return value;
    }
    public static final class SearchPage {public final List<Message> messages;public final boolean hasMore;public final String nextAfterId;private SearchPage(List<Message>m,boolean more,String next){messages=immutable(m);hasMore=more;nextAfterId=next;}}
    public interface TranscriptLabels {String header(Company company,Conversation conversation);String deleted();String reply(Message quoted);String attachment(Attachment attachment);}
    public void writeConversationTranscript(String companyId,String conversationId,Writer out)throws IOException {
        writeConversationTranscript(companyId,conversationId,out,new TranscriptLabels(){public String header(Company c,Conversation v){return "سجل محادثة محلي تجريبي\nالشركة: "+c.name+"\nالمحادثة: "+v.title+"\n";}public String deleted(){return DELETED_MESSAGE_TEXT;}public String reply(Message m){return "رد على "+m.senderName+": "+replyPreview(m);}public String attachment(Attachment a){return "مرفق: "+a.name;}});
    }
    public void writeConversationTranscript(String companyId,String conversationId,Writer out,TranscriptLabels labels)throws IOException {
        State snapshot=state;Conversation cv=target(snapshot,companyId,conversationId);SimpleDateFormat time=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss 'UTC'",Locale.ROOT);time.setTimeZone(TimeZone.getTimeZone("UTC"));
        out.write(labels.header(snapshot.companies.get(companyId),cv));
        for(Message m:snapshot.messages.get(conversationId)){if(Thread.currentThread().isInterrupted())throw new IOException("Export interrupted");out.write("\n["+time.format(new Date(m.createdAt))+"] "+m.senderName+"\n");
            if(m.deleted){out.write(labels.deleted()+"\n");continue;}if(m.replyToMessageId!=null)out.write(labels.reply(targetMessage(snapshot,companyId,conversationId,m.replyToMessageId))+"\n");
            if(!m.text.isEmpty())out.write(m.text+"\n");for(Attachment a:m.attachments)out.write(labels.attachment(a)+"\n");}
    }
    public static final class RecoveryInfo {
        public final boolean available;public final long savedAt;public final int messageCount;
        public final String expectedRootHash;private final String rootPath;
        private RecoveryInfo(boolean a,long t,int n,String hash,String path){available=a;savedAt=t;messageCount=n;expectedRootHash=hash;rootPath=path;}
    }
    public static RecoveryInfo inspectRecovery(File root)throws IOException {
        File canonical=root.getCanonicalFile();String expected=hashFileOrNull(canonical);File backup=StoreJournal.lastGoodFile(canonical);StoreJournal.Metadata m=StoreJournal.inspect(backup);
        if(!m.available)return new RecoveryInfo(false,0,0,expected,canonical.getPath());
        ChatStore checked=new ChatStore(backup);int count=0;for(List<Message> messages:checked.state.messages.values())count+=messages.size();
        return new RecoveryInfo(true,m.savedAt,count,expected,canonical.getPath());
    }
    public static ChatStore restoreLastGood(File root)throws IOException {return restoreLastGood(root,inspectRecovery(root));}
    public static ChatStore restoreLastGood(File root,RecoveryInfo preview)throws IOException {
        if(preview==null||!preview.available||!root.getCanonicalPath().equals(preview.rootPath))throw new IOException("No validated prior save is selected");
        StoreJournal.recover(root,preview.expectedRootHash);return new ChatStore(root);
    }
    private static String hashFileOrNull(File file)throws IOException {
        if(!file.exists())return null;if(!file.isFile())throw new IOException("History root is not a file");
        try{java.security.MessageDigest digest=java.security.MessageDigest.getInstance("SHA-256");try(FileInputStream in=new FileInputStream(file)){byte[] bytes=new byte[8192];int n;while((n=in.read(bytes))!=-1)digest.update(bytes,0,n);}
            StringBuilder hex=new StringBuilder();for(byte value:digest.digest())hex.append(String.format(Locale.ROOT,"%02x",value&255));return hex.toString();
        }catch(java.security.NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
    public static final class StorageStats {public final long totalPrivateBytes,attachmentBytes,journalBytes,legacyBytes,recoverableTempBytes,usableBytes,metadataBytes;public final int attachmentFiles;StorageStats(long total,long a,long j,long l,long t,long free,int files){totalPrivateBytes=total;attachmentBytes=a;journalBytes=j;legacyBytes=l;recoverableTempBytes=t;usableBytes=free;metadataBytes=total-a;attachmentFiles=files;}}
    public StorageStats storageStats()throws IOException {
        Set<String> refs=new HashSet<String>();for(String path:attachmentPaths())refs.add(new File(path).getCanonicalPath());long[] n=new long[6];scanBytes(internalRoot,refs,n,new HashSet<String>());return new StorageStats(n[0],n[1],n[2],n[3],n[4],internalRoot.getUsableSpace(),(int)n[5]);
    }
    private void scanBytes(File file,Set<String> refs,long[] n,Set<String> seen)throws IOException {
        String path=file.getCanonicalPath();if(!path.equals(internalRoot.getPath())&&!path.startsWith(internalRoot.getPath()+File.separator))return;if(!seen.add(path))return;
        if(file.isDirectory()){File[] children=file.listFiles();if(children!=null)for(File c:children)scanBytes(c,refs,n,seen);return;}if(!file.isFile())return;long size=file.length();n[0]+=size;
        if(refs.contains(path)||path.startsWith(new File(internalRoot,"attachments").getCanonicalPath()+File.separator)){n[1]+=size;n[5]++;}if(file.getName().startsWith("bch4-")&&file.getName().endsWith(".segment"))n[2]+=size;if(file.getName().contains(".legacy-"))n[3]+=size;if(file.getName().contains("-staged-")||file.getName().endsWith(".tmp"))n[4]+=size;
    }

    // Each immutable domain record is independently bounded; no serialized whole-history writes.
    private interface Encoder {void write(DataOutputStream out)throws IOException;}
    private static byte[] record(Encoder encoder)throws IOException{ByteArrayOutputStream bytes=new ByteArrayOutputStream();DataOutputStream out=new DataOutputStream(bytes);out.writeInt(1);encoder.write(out);out.flush();if(bytes.size()>1024*1024)throw new IOException("Individual record exceeds safe bound");return bytes.toByteArray();}
    private static void text(DataOutputStream out,String value)throws IOException {if(value==null){out.writeInt(-1);return;}if(value.length()>262144)throw new IOException("Field exceeds safe bound");out.writeInt(value.length());for(int i=0;i<value.length();i++)out.writeChar(value.charAt(i));}
    private static String text(DataInputStream in)throws IOException {int length=in.readInt();if(length==-1)return null;if(length<0||length>262144||length>in.available()/2)throw new IOException("Invalid string length");char[] value=new char[length];for(int i=0;i<length;i++)value[i]=in.readChar();return new String(value);}
    private static String required(DataInputStream in)throws IOException{String value=text(in);if(value==null)throw new IOException("Missing required field");return value;}
    private static int count(DataInputStream in,int max)throws IOException{int n=in.readInt();if(n<0||n>max)throw new IOException("Invalid collection count");return n;}
    private static void attachments(DataOutputStream out,List<Attachment> files)throws IOException {out.writeInt(files.size());for(Attachment a:files){text(out,a.id);text(out,a.path);text(out,a.name);text(out,a.mime);out.writeLong(a.size);text(out,a.sha256);}}
    private static List<Attachment> attachments(DataInputStream in)throws IOException {int n=count(in,MAX_ATTACHMENTS);List<Attachment> files=new ArrayList<Attachment>(n);for(int i=0;i<n;i++)files.add(new Attachment(required(in),required(in),required(in),required(in),in.readLong(),text(in)));return files;}
    private static void message(DataOutputStream out,Message m)throws IOException{text(out,m.id);text(out,m.companyId);text(out,m.conversationId);text(out,m.text);attachments(out,m.attachments);out.writeBoolean(m.mine);text(out,m.senderName);out.writeLong(m.createdAt);text(out,m.status);text(out,m.sourceShareId);text(out,m.replyToMessageId);out.writeBoolean(m.deleted);}
    private static Message message(DataInputStream in)throws IOException{return new Message(required(in),required(in),required(in),required(in),attachments(in),in.readBoolean(),required(in),in.readLong(),required(in),text(in),text(in),in.readBoolean());}
    private static void add(List<StoreJournal.Record> result,String key,Encoder encoder)throws IOException{result.add(new StoreJournal.Record(key,encoder==null?null:record(encoder)));}
    private List<StoreJournal.Record> encodeChanges(State before,State after)throws IOException {
        List<StoreJournal.Record> result=new ArrayList<StoreJournal.Record>();
        for(final Company c:after.companies.values())if(before==null||before.companies.get(c.id)!=c)add(result,"C/"+c.id,new Encoder(){public void write(DataOutputStream out)throws IOException{text(out,c.id);text(out,c.name);text(out,c.subtitle);out.writeInt(c.avatarHue);}});
        for(final Conversation c:after.conversations.values())if(before==null||before.conversations.get(c.id)!=c)add(result,"V/"+c.id,new Encoder(){public void write(DataOutputStream out)throws IOException{text(out,c.id);text(out,c.companyId);text(out,c.title);text(out,c.subtitle);text(out,c.kind);out.writeInt(c.unread);out.writeInt(c.avatarHue);}});
        for(final Map.Entry<String,List<String>> e:after.demoGroupMembers.entrySet())if(before==null||before.demoGroupMembers.get(e.getKey())!=e.getValue())add(result,"G/"+e.getKey(),new Encoder(){public void write(DataOutputStream out)throws IOException{out.writeInt(e.getValue().size());for(String v:e.getValue())text(out,v);}});
        for(Map.Entry<String,List<Message>> e:after.messages.entrySet()){
            List<Message> old=before==null?null:before.messages.get(e.getKey());if(old==e.getValue())continue;Map<String,Message> previous=new LinkedHashMap<String,Message>();if(old!=null)for(Message m:old)previous.put(m.id,m);
            for(final Message m:e.getValue())if(previous.remove(m.id)!=m)add(result,"M/"+m.id,new Encoder(){public void write(DataOutputStream out)throws IOException{message(out,m);}});
            if(!previous.isEmpty())throw new IOException("Permanent message removal is not supported");
        }
        for(final Map.Entry<String,Draft> e:after.drafts.entrySet())if(before==null||before.drafts.get(e.getKey())!=e.getValue())add(result,"D/"+e.getKey(),new Encoder(){public void write(DataOutputStream out)throws IOException{Draft d=e.getValue();text(out,d.text);attachments(out,d.attachments);text(out,d.replyToMessageId);}});
        if(before!=null)for(String k:before.drafts.keySet())if(!after.drafts.containsKey(k))add(result,"D/"+k,null);
        for(final Map.Entry<String,Message> e:after.deletedMessages.entrySet())if(before==null||before.deletedMessages.get(e.getKey())!=e.getValue())add(result,"U/"+e.getKey(),new Encoder(){public void write(DataOutputStream out)throws IOException{message(out,e.getValue());}});
        if(before!=null)for(String k:before.deletedMessages.keySet())if(!after.deletedMessages.containsKey(k))add(result,"U/"+k,null);
        if(before==null||before.pendingShare!=after.pendingShare){final PendingShare p=after.pendingShare;add(result,"P",p==null?null:new Encoder(){public void write(DataOutputStream out)throws IOException{text(out,p.id);text(out,p.text);attachments(out,p.attachments);out.writeBoolean(p.previewEdited);}});}
        for(final Map.Entry<String,String> e:after.readMarkers.entrySet())if(before==null||!e.getValue().equals(before.readMarkers.get(e.getKey())))add(result,"R/"+e.getKey(),new Encoder(){public void write(DataOutputStream out)throws IOException{text(out,e.getValue());}});
        for(final Map.Entry<String,String> e:after.resolvedShares.entrySet())if(before==null||!e.getValue().equals(before.resolvedShares.get(e.getKey())))add(result,"S/"+e.getKey(),new Encoder(){public void write(DataOutputStream out)throws IOException{text(out,e.getValue());}});
        return result;
    }
    private State decodeRecords(Map<String,byte[]> records)throws IOException {
        State result=new State();List<Message> messages=new ArrayList<Message>();
        try{for(Map.Entry<String,byte[]> e:records.entrySet()){
            byte[] data=e.getValue();if(data==null||data.length>1024*1024)throw new IOException("Invalid stored record");DataInputStream in=new DataInputStream(new ByteArrayInputStream(data));if(in.readInt()!=1)throw new IOException("Unsupported record version");String k=e.getKey();
            if(k.startsWith("C/")){Company c=new Company(required(in),required(in),required(in),in.readInt());if(!k.equals("C/"+c.id))throw new IOException("Company record identity mismatch");result.companies.put(c.id,c);}
            else if(k.startsWith("V/")){Conversation c=new Conversation(required(in),required(in),required(in),required(in),required(in),in.readInt(),in.readInt());if(!k.equals("V/"+c.id))throw new IOException("Conversation record identity mismatch");result.conversations.put(c.id,c);result.messages.put(c.id,new ArrayList<Message>());}
            else if(k.startsWith("G/")){int n=count(in,200);List<String> ids=new ArrayList<String>(n);for(int i=0;i<n;i++)ids.add(required(in));result.demoGroupMembers.put(k.substring(2),immutable(ids));}
            else if(k.startsWith("M/")){Message m=message(in);if(!k.equals("M/"+m.id))throw new IOException("Message record identity mismatch");messages.add(m);}
            else if(k.startsWith("U/")){Message m=message(in);if(!k.equals("U/"+m.id))throw new IOException("Undo record identity mismatch");result.deletedMessages.put(m.id,m);}
            else if(k.startsWith("D/"))result.drafts.put(k.substring(2),new Draft(required(in),attachments(in),text(in)));
            else if(k.equals("P"))result.pendingShare=new PendingShare(required(in),required(in),attachments(in),in.readBoolean());
            else if(k.startsWith("R/"))result.readMarkers.put(k.substring(2),required(in));
            else if(k.startsWith("S/")){checkedUuid(k.substring(2));result.resolvedShares.put(k.substring(2),required(in));}
            else throw new IOException("Unsupported record type");if(in.available()!=0)throw new IOException("Trailing record bytes");
        }
        for(Message m:messages){List<Message> list=result.messages.get(m.conversationId);if(list==null)throw new IOException("Message has no conversation");list.add(m);}
        for(Map.Entry<String,String> e:result.readMarkers.entrySet()){boolean found=false;for(Conversation c:result.conversations.values())if(key(c.companyId,c.id).equals(e.getKey())){if(!e.getValue().isEmpty())targetMessage(result,c.companyId,c.id,e.getValue());found=true;break;}if(!found)throw new IOException("Read marker has no conversation");}
        return result;
        }catch(RuntimeException failure){throw new IOException("Local records invalid; originals preserved",failure);}
    }

    private static final class State implements Serializable {
        private static final long serialVersionUID = 1L;
        final int version;
        final LinkedHashMap<String, Company> companies;
        final LinkedHashMap<String, Conversation> conversations;
        final LinkedHashMap<String, List<Message>> messages;
        final LinkedHashMap<String, Draft> drafts;
        final LinkedHashMap<String, List<String>> demoGroupMembers;
        // Originals are private undo payloads only, never public message/search/page snapshots.
        final LinkedHashMap<String, Message> deletedMessages;
        final LinkedHashMap<String,String> readMarkers;
        final LinkedHashMap<String,String> resolvedShares;
        PendingShare pendingShare;
        State() {
            version = FORMAT_VERSION;
            companies = new LinkedHashMap<String, Company>();
            conversations = new LinkedHashMap<String, Conversation>();
            messages = new LinkedHashMap<String, List<Message>>();
            drafts = new LinkedHashMap<String, Draft>();
            demoGroupMembers = new LinkedHashMap<String, List<String>>();
            deletedMessages = new LinkedHashMap<String, Message>();
            readMarkers = new LinkedHashMap<String,String>();
            resolvedShares = new LinkedHashMap<String,String>();
        }
        State(State source) {
            version = FORMAT_VERSION;
            companies = new LinkedHashMap<String, Company>(source.companies);
            conversations = new LinkedHashMap<String, Conversation>(source.conversations);
            messages = new LinkedHashMap<String, List<Message>>(source.messages);
            drafts = new LinkedHashMap<String, Draft>(source.drafts);
            demoGroupMembers = source.demoGroupMembers == null
                    ? new LinkedHashMap<String, List<String>>()
                    : new LinkedHashMap<String, List<String>>(source.demoGroupMembers);
            deletedMessages = source.deletedMessages == null
                    ? new LinkedHashMap<String, Message>()
                    : new LinkedHashMap<String, Message>(source.deletedMessages);
            readMarkers = source.readMarkers == null ? new LinkedHashMap<String,String>() : new LinkedHashMap<String,String>(source.readMarkers);
            resolvedShares = source.resolvedShares == null ? new LinkedHashMap<String,String>() : new LinkedHashMap<String,String>(source.resolvedShares);
            pendingShare = source.pendingShare;
        }
    }

    public static final class Company implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String id, name, subtitle;
        public final int avatarHue;
        private Company(String id, String name, String subtitle, int avatarHue) {
            this.id = id; this.name = name; this.subtitle = subtitle; this.avatarHue = avatarHue;
        }
    }
    public static final class Conversation implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String id, companyId, title, subtitle, kind;
        public final int unread, avatarHue;
        private Conversation(String id, String companyId, String title, String subtitle,
                             String kind, int unread, int avatarHue) {
            this.id = id; this.companyId = companyId; this.title = title; this.subtitle = subtitle;
            this.kind = kind; this.unread = unread; this.avatarHue = avatarHue;
        }
    }
    public static final class Recipient {
        public final Company company;
        public final Conversation conversation;
        private Recipient(Company company, Conversation conversation) {
            this.company = company; this.conversation = conversation;
        }
    }
    public static final class Attachment implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String id, path, name, mime, sha256;
        public final long size;
        public Attachment(String path, String name, String mime, long size) {
            this(UUID.randomUUID().toString(), path, name, mime, size);
        }
        public Attachment(String id, String path, String name, String mime, long size) {
            this(id,path,name,mime,size,null);
        }
        public Attachment(String id, String path, String name, String mime, long size, String sha256) {
            this.id = checkedUuid(id); this.path = path; this.name = name; this.mime = mime; this.size = size; this.sha256 = sha256;
            validateAttachment(this);
        }
    }
    public static final class Draft implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String text;
        public final String replyToMessageId;
        public final List<Attachment> attachments;
        private Draft(String text, List<Attachment> attachments, String replyToMessageId) {
            this.text = text; this.attachments = immutable(attachments); this.replyToMessageId = replyToMessageId;
        }
    }
    public static final class PendingShare implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String id, text;
        public final boolean previewEdited;
        public final List<Attachment> attachments;
        private PendingShare(String id, String text, List<Attachment> attachments) {
            this(id,text,attachments,false);
        }
        private PendingShare(String id,String text,List<Attachment> attachments,boolean edited) {
            this.id=id; this.text=text; this.attachments=immutable(attachments); this.previewEdited=edited;
        }
    }
    public static final class Message implements Serializable {
        private static final long serialVersionUID = 1L;
        public final String id, companyId, conversationId, text, senderName, status, sourceShareId;
        public final String replyToMessageId;
        public final List<Attachment> attachments;
        public final boolean mine, deleted;
        public final long createdAt;
        private Message(String id, String companyId, String conversationId, String text,
                        List<Attachment> attachments, boolean mine, String senderName,
                        long createdAt, String status, String sourceShareId) {
            this(id, companyId, conversationId, text, attachments, mine, senderName, createdAt,
                    status, sourceShareId, null);
        }
        private Message(String id, String companyId, String conversationId, String text,
                        List<Attachment> attachments, boolean mine, String senderName,
                        long createdAt, String status, String sourceShareId, String replyToMessageId) {
            this(id, companyId, conversationId, text, attachments, mine, senderName, createdAt,
                    status, sourceShareId, replyToMessageId, false);
        }
        private Message(String id, String companyId, String conversationId, String text,
                        List<Attachment> attachments, boolean mine, String senderName,
                        long createdAt, String status, String sourceShareId, String replyToMessageId,
                        boolean deleted) {
            this.id = id; this.companyId = companyId; this.conversationId = conversationId;
            this.text = text; this.attachments = immutable(attachments); this.mine = mine;
            this.senderName = senderName; this.createdAt = createdAt; this.status = status;
            this.sourceShareId = sourceShareId;
            this.replyToMessageId = replyToMessageId;
            this.deleted = deleted;
        }
    }
    public static final class Page {
        public final List<Message> messages;
        public final boolean hasMore;
        public final String nextBeforeId;
        private Page(List<Message> messages, boolean hasMore, String nextBeforeId) {
            this.messages = immutable(messages); this.hasMore = hasMore; this.nextBeforeId = nextBeforeId;
        }
    }
}
