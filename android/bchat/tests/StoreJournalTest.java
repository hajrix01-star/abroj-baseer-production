import com.baseer.freshchat.StoreJournal;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.ObjectOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/** Normal-input functional coverage only; no malformed or resource-exhaustion fixtures. */
public final class StoreJournalTest {
    private static int passed;
    private interface Test { void run() throws Exception; }
    public static void main(String[] args) throws Exception {
        run("initial empty journal survives reopen", StoreJournalTest::emptyJournal);
        run("ordered update delete and reinsert survive reopen", StoreJournalTest::orderedRecords);
        run("unicode keys and binary payloads round trip", StoreJournalTest::unicodeBinary);
        run("record construction and reads isolate value buffers", StoreJournalTest::isolatedBuffers);
        run("stale writer fails while new instance commits normally", StoreJournalTest::staleWriter);
        run("legacy bytes preserved exactly before first migration", StoreJournalTest::legacyPreservation);
        run("last-good preview and explicit recovery preserve both states", StoreJournalTest::recovery);
        run("recovery preview token rejects a newer successful commit", StoreJournalTest::staleRecovery);
        run("unreferenced valid segment does not join committed history", StoreJournalTest::uncommittedIgnored);
        run("normal message-sized batch and metadata survive repeated commits", StoreJournalTest::normalBatch);
        System.out.println("PASS: " + passed + " normal-input StoreJournal tests");
    }
    private static void run(String name, Test test) throws Exception {
        test.run(); passed++; System.out.println("PASS " + name);
    }
    private static File fresh() throws IOException {
        return new File(Files.createTempDirectory("bchat-journal-normal-").toFile(), "chat-state.bin");
    }
    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private static StoreJournal.Record record(String key, String value) {
        return new StoreJournal.Record(key, value == null ? null : bytes(value));
    }
    private static void check(boolean truth, String message) { if (!truth) throw new AssertionError(message); }
    private static void equal(byte[] expected, byte[] actual) { check(Arrays.equals(expected, actual), "Different bytes"); }
    private static void equal(Object expected, Object actual) { check(expected.equals(actual), expected + " != " + actual); }
    private static void expectIo(Test action) throws Exception {
        try { action.run(); throw new AssertionError("Expected IOException"); } catch (IOException expected) { }
    }
    private static void emptyJournal() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        check(store.read().isEmpty(), "Absent storage should be empty");
        check(!StoreJournal.inspect(file).available, "Absent metadata");
        store.commit(Collections.<StoreJournal.Record>emptyList());
        check(StoreJournal.isJournal(file), "BCH4 root");
        check(new StoreJournal(file).read().isEmpty(), "Empty reopened state");
        byte[] prior = Files.readAllBytes(file.toPath());
        store.commit(Collections.<StoreJournal.Record>emptyList());
        equal(prior, Files.readAllBytes(file.toPath()));
        check(Files.size(file.toPath()) < 256, "Small root");
    }
    private static void orderedRecords() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        store.commit(Arrays.asList(record("a", "one"), record("b", "two"), record("c", "three")));
        store.commit(Arrays.asList(record("b", "updated"), record("a", null)));
        store.commit(Arrays.asList(record("a", "new"), record("d", "four")));
        Map<String, byte[]> state = new StoreJournal(file).read();
        equal(Arrays.asList("b", "c", "a", "d"), new ArrayList<String>(state.keySet()));
        equal(bytes("updated"), state.get("b")); equal(bytes("new"), state.get("a"));
    }
    private static void unicodeBinary() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        byte[] data = new byte[]{0, 1, -1, 42, 0};
        store.commit(Arrays.asList(new StoreJournal.Record("رسالة/🌱", data), new StoreJournal.Record("empty", new byte[0])));
        Map<String, byte[]> state = StoreJournal.readFile(file);
        equal(data, state.get("رسالة/🌱")); equal(new byte[0], state.get("empty"));
    }
    private static void isolatedBuffers() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        byte[] value = bytes("saved"); StoreJournal.Record record = new StoreJournal.Record("key", value);
        value[0] = 0; byte[] copy = record.value(); copy[0] = 0;
        store.commit(Collections.singletonList(record));
        store.read().get("key")[0] = 0;
        equal(bytes("saved"), store.read().get("key"));
    }
    private static void staleWriter() throws Exception {
        File file = fresh(); StoreJournal first = new StoreJournal(file), old = new StoreJournal(file);
        first.commit(Collections.singletonList(record("first", "kept")));
        expectIo(() -> old.commit(Collections.singletonList(record("stale", "ignored"))));
        StoreJournal next = new StoreJournal(file);
        next.commit(Collections.singletonList(record("second", "kept")));
        check(next.read().size() == 2, "New writer succeeds without losing first record");
        expectIo(first::read);
    }
    private static void legacyPreservation() throws Exception {
        File file = fresh(); ByteArrayOutputStream raw = new ByteArrayOutputStream();
        try (ObjectOutputStream out = new ObjectOutputStream(raw)) { out.writeObject("normal legacy example"); }
        byte[] legacy = raw.toByteArray(); Files.write(file.toPath(), legacy);
        StoreJournal store = new StoreJournal(file);
        equal(legacy, Files.readAllBytes(file.toPath()));
        check(StoreJournal.inspect(file).legacy, "Legacy metadata");
        expectIo(store::read);
        store.commit(Arrays.asList(record("old-message", "preserved domain value"), record("draft", "draft text")));
        equal(legacy, Files.readAllBytes(StoreJournal.lastGoodFile(file).toPath()));
        String hash = hex(MessageDigest.getInstance("SHA-256").digest(legacy));
        File archive = new File(file.getPath() + ".legacy-" + hash);
        equal(legacy, Files.readAllBytes(archive.toPath()));
        check(new StoreJournal(file).read().size() == 2, "Full migrated state");
    }
    private static void recovery() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        store.commit(Collections.singletonList(record("message", "first")));
        byte[] first = Files.readAllBytes(file.toPath());
        store.commit(Collections.singletonList(record("message", "second")));
        byte[] second = Files.readAllBytes(file.toPath());
        equal(first, Files.readAllBytes(StoreJournal.lastGoodFile(file).toPath()));
        equal(bytes("first"), StoreJournal.readLastGood(file).get("message"));
        StoreJournal.Metadata backup = StoreJournal.inspect(StoreJournal.lastGoodFile(file));
        check(backup.available && backup.journal && backup.savedAt > 0 && backup.generation == 1, "Valid backup metadata");
        StoreJournal.recover(file, StoreJournal.inspect(file).rootHash);
        equal(first, Files.readAllBytes(file.toPath()));
        equal(bytes("first"), new StoreJournal(file).read().get("message"));
        String secondHash = hex(MessageDigest.getInstance("SHA-256").digest(second));
        equal(second, Files.readAllBytes(new File(file.getPath() + ".preserved-" + secondHash).toPath()));
        equal(first, Files.readAllBytes(StoreJournal.lastGoodFile(file).toPath()));
    }
    private static void staleRecovery() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        store.commit(Collections.singletonList(record("a", "one")));
        String oldHash = StoreJournal.inspect(file).rootHash;
        store.commit(Collections.singletonList(record("b", "two")));
        expectIo(() -> StoreJournal.recover(file, oldHash));
        check(new StoreJournal(file).read().size() == 2, "Newer commit retained");
    }
    private static void uncommittedIgnored() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        store.commit(Collections.singletonList(record("committed", "yes")));
        File unrelated = fresh(); new StoreJournal(unrelated).commit(Collections.singletonList(record("uncommitted", "no")));
        File[] siblings = unrelated.getParentFile().listFiles(); check(siblings != null, "Temp files available");
        for (File sibling : siblings) if (sibling.getName().startsWith("bch4-") && sibling.getName().endsWith(".segment"))
            Files.copy(sibling.toPath(), new File(file.getParentFile(), sibling.getName()).toPath());
        Map<String, byte[]> state = new StoreJournal(file).read();
        check(state.size() == 1 && state.containsKey("committed"), "Only root-referenced records load");
    }
    private static void normalBatch() throws Exception {
        File file = fresh(); StoreJournal store = new StoreJournal(file);
        List<StoreJournal.Record> records = new ArrayList<StoreJournal.Record>();
        for (int i = 0; i < 260; i++) records.add(record("message/" + i, "Normal local message " + i));
        store.commit(records);
        for (int i = 0; i < 3; i++) store.commit(Collections.singletonList(record("draft", "Revision " + i)));
        Map<String, byte[]> state = new StoreJournal(file).read();
        check(state.size() == 261, "All normal history records retained");
        equal(bytes("Normal local message 0"), state.get("message/0"));
        equal(bytes("Normal local message 259"), state.get("message/259"));
        equal(bytes("Revision 2"), state.get("draft"));
        StoreJournal.Metadata metadata = StoreJournal.inspect(file);
        check(metadata.generation == 4 && metadata.rootHash.length() == 64, "Commit metadata");
    }
    private static String hex(byte[] bytes) {
        StringBuilder out = new StringBuilder(); for (byte b : bytes) out.append(String.format("%02x", b & 255)); return out.toString();
    }
}
