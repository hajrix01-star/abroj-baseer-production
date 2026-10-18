package com.baseer.freshchat;

import android.content.Context;
import android.util.AtomicFile;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;

/** Shared production-index cases; platform execution is identified by the owning harness. */
final class IndexCases {
    interface Host {
        Context context(String name) throws Exception;
        File files(Context context);
        int lookups(Context context);
        void main(Runnable action);
    }
    static final String SCOPE = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    static final String ACCOUNT = "00000000-0000-4000-8000-000000000099";
    static final String OTHER = "00000000-0000-4000-8000-000000000098";
    private static int checks;
    static void check(boolean value, String message) { ++checks; if (!value) throw new AssertionError("Index check " + checks + ": " + message); }
    static String room(int value) { return String.format(Locale.US, "%064x", value); }
    static String token(int value) { return String.format(Locale.US, "00000000-0000-4000-8000-%012d", value); }
    static File base(Host host, Context context) { return new File(new File(host.files(context), "bchat-room-mute-index"), SCOPE + ".json"); }
    static byte[] bytes(File file) throws Exception { return Files.readAllBytes(file.toPath()); }
    static String text(File file) throws Exception { return new String(bytes(file), StandardCharsets.UTF_8); }
    static void write(File file, byte[] value) throws Exception { Files.createDirectories(file.getParentFile().toPath()); Files.write(file.toPath(), value); }
    static void write(File file, String value) throws Exception { write(file, value.getBytes(StandardCharsets.UTF_8)); }
    static BChatRoomMuteIndex.Kind kind(BChatRoomMuteIndex.Result result, BChatRoomMuteIndex.Kind kind) {
        check(result.kind == kind, "Expected " + kind + ", got " + result.kind); return result.kind;
    }
    static int run(Host host) throws Exception {
        checks = 0;
        Context context = host.context("basic"); BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, SCOPE, ACCOUNT);
        check(host.lookups(context) == 0, "Constructor no private file lookup");
        for (Runnable action : new Runnable[]{index::load, () -> index.put(room(1), token(1)), () -> index.clear(room(1), token(1))}) {
            host.main(() -> {
                try { action.run(); throw new AssertionError("Index accepted MAIN"); }
                catch (IllegalStateException expected) { check(host.lookups(context) == 0, "MAIN rejected before files lookup"); }
            });
        }
        kind(index.load(), BChatRoomMuteIndex.Kind.ABSENT);
        check(!new File(host.files(context), "bchat-room-mute-index").exists(), "Read absent never mkdir");
        kind(index.put(room(1), token(1)), BChatRoomMuteIndex.Kind.COMMITTED);
        byte[] original = bytes(base(host, context));
        kind(index.put(room(1), token(1)), BChatRoomMuteIndex.Kind.UNCHANGED);
        kind(index.clear(room(1), token(2)), BChatRoomMuteIndex.Kind.NO_MATCH);
        check(Arrays.equals(original, bytes(base(host, context))), "Noop/mismatch no write");
        BChatRoomMuteIndex.State loaded = index.load().state;
        try { loaded.floors.put(room(2), token(2)); throw new AssertionError("Mutable index snapshot"); }
        catch (UnsupportedOperationException expected) { ++checks; }
        kind(index.clear(room(1), token(1)), BChatRoomMuteIndex.Kind.COMMITTED);
        check(index.load().state.floors.isEmpty() && index.load().state.revision == 2, "Clear retained exact empty canonical envelope");
        kind(index.clear(room(1), token(1)), BChatRoomMuteIndex.Kind.NO_MATCH);
        BChatRoomMuteIndex wrongRoute = new BChatRoomMuteIndex(context, SCOPE, OTHER);
        kind(wrongRoute.load(), BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
        kind(wrongRoute.put(room(3), token(3)), BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
        Context fullContext = host.context("capacity"); BChatRoomMuteIndex full = new BChatRoomMuteIndex(fullContext, SCOPE, ACCOUNT);
        for (int value = 1; value <= 100; value++) kind(full.put(room(value), token(value)), BChatRoomMuteIndex.Kind.COMMITTED);
        byte[] fullBytes = bytes(base(host, fullContext)); kind(full.put(room(101), token(101)), BChatRoomMuteIndex.Kind.CAPACITY);
        check(Arrays.equals(fullBytes, bytes(base(host, fullContext))) && full.load().state.floors.size() == 100, "No active floor eviction");
        kind(full.put(room(1), token(200)), BChatRoomMuteIndex.Kind.COMMITTED);
        String valid = text(base(host, fullContext));
        String exhausted = valid.replace("\"revision\":101", "\"revision\":9223372036854775807");
        check(!exhausted.equals(valid), "Overflow fixture exact revision replacement"); write(base(host, fullContext), exhausted);
        kind(full.put(room(1), token(201)), BChatRoomMuteIndex.Kind.EXHAUSTED);
        malformed(host, valid); recovery(host); faults(host);
        return checks;
    }
    private static void malformed(Host host, String valid) throws Exception {
        List<byte[]> bad = Arrays.asList(new byte[0], "{".getBytes(StandardCharsets.UTF_8), (valid + " ").getBytes(StandardCharsets.UTF_8),
                valid.replace("\"format_version\":1", "\"format_version\":1.0").getBytes(StandardCharsets.UTF_8),
                valid.replace("\"revision\":101", "\"revision\":0").getBytes(StandardCharsets.UTF_8),
                valid.replace("\"entries\":[", "\"extra\":true,\"entries\":[").getBytes(StandardCharsets.UTF_8),
                new byte[]{(byte) 0xc3, 0x28}, new byte[BChatRoomMuteIndex.MAX_BYTES + 1]);
        int item = 0;
        for (byte[] bytes : bad) {
            Context context = host.context("bad-" + item++); File base = base(host, context); write(base, bytes);
            BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, SCOPE, ACCOUNT);
            check(!index.load().readable(), "Malformed never ABSENT/partial state");
            check(index.put(room(999), token(999)).kind != BChatRoomMuteIndex.Kind.COMMITTED, "Malformed blocks mutation");
            check(Arrays.equals(bytes, bytes(base)), "Malformed bytes not reset");
        }
        Context context = host.context("unsupported"); File base = base(host, context);
        write(base, valid.replace("\"format_version\":1", "\"format_version\":2"));
        kind(new BChatRoomMuteIndex(context, SCOPE, ACCOUNT).load(), BChatRoomMuteIndex.Kind.UNSUPPORTED);
    }
    private static void recovery(Host host) throws Exception {
        Context context = host.context("backup"); File base = base(host, context);
        BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, SCOPE, ACCOUNT);
        kind(index.put(room(1), token(1)), BChatRoomMuteIndex.Kind.COMMITTED); byte[] old = bytes(base);
        kind(index.put(room(2), token(2)), BChatRoomMuteIndex.Kind.COMMITTED); byte[] newer = bytes(base);
        File backup = new File(base + ".bak"), next = new File(base + ".new");
        write(backup, "{invalid backup");
        kind(index.load(), BChatRoomMuteIndex.Kind.CORRUPT);
        check(Arrays.equals(newer, bytes(base)) && backup.exists(), "Invalid backup cannot overwrite valid base");
        write(backup, old); kind(index.load(), BChatRoomMuteIndex.Kind.LOADED);
        check(Arrays.equals(old, bytes(base)) && index.load().state.floors.size() == 1, "Valid backup rollback priority");
        write(next, "{partial"); kind(index.load(), BChatRoomMuteIndex.Kind.LOADED);
        check(Arrays.equals(old, bytes(base)), "Valid base plus partial new recovers old state");
        Context orphan = host.context("orphan"); File orphanNext = new File(base(host, orphan) + ".new"); write(orphanNext, old);
        kind(new BChatRoomMuteIndex(orphan, SCOPE, ACCOUNT).load(), BChatRoomMuteIndex.Kind.CORRUPT);
        check(Arrays.equals(old, bytes(orphanNext)), "Orphan new is preserved, never treated as absent");
    }
    private static void faults(Host host) throws Exception {
        for (boolean closedBeforeSync : new boolean[]{false, true}) {
            Context context = host.context("fault-" + closedBeforeSync);
            BChatRoomMuteIndex index = new BChatRoomMuteIndex(context, SCOPE, ACCOUNT, base -> new AtomicFile(base) {
                @Override public FileOutputStream startWrite() throws IOException {
                    FileOutputStream stream = super.startWrite();
                    if (!closedBeforeSync) return stream;
                    stream.close();
                    return new FileOutputStream(new File(base + ".new")) {
                        @Override public void write(byte[] bytes) throws IOException { super.write(bytes); close(); }
                    };
                }
                @Override public void finishWrite(FileOutputStream stream) {
                    try { stream.close(); } catch (IOException ignored) { }
                }
            });
            kind(index.put(room(1), token(1)), BChatRoomMuteIndex.Kind.UNCERTAIN);
            check(index.load().kind != BChatRoomMuteIndex.Kind.LOADED, "Explicit sync/silent finish fault never dispatch proof");
        }
    }
}
