package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Modifier;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/** DEV163 production Index/roomKey on actual JVM files. Context/Looper/AtomicFile/JSON
 * and deterministic fault injection are declared adapters, not Android/auth/Store/Host. */
public final class RebindCases {
    private static final String S = repeat('a', 64), OTHER = repeat('b', 64);
    private static final String A = "00000000-0000-4000-8000-000000000099", B = "00000000-0000-4000-8000-000000000098";
    private static final String T1 = "00000000-0000-4000-8000-000000000001", T2 = "00000000-0000-4000-8000-000000000002";
    private static File root;
    private static int checks, groups, serial;
    private interface Action { void run() throws Exception; }
    private static void check(boolean value, String label) { ++checks; if (!value) throw new AssertionError(label); }
    private static void group(String name, Action action) throws Exception {
        int start = checks; action.run(); ++groups; System.out.println("GROUP " + name + " assertions=" + (checks - start));
    }
    private static Context context() throws Exception {
        File directory = new File(root, "fixture-" + (++serial)); Files.createDirectory(directory.toPath()); return new Context(directory);
    }
    private static File base(Context context) { return new File(new File(context.getFilesDir(), "bchat-room-mute-index"), S + ".json"); }
    private static String key(String account, long room) { return NotificationPresentation.roomKey(account, 1, room, room + 1000); }
    private static BChatRoomMuteIndex.RebindRoom room(long room, boolean required) { return new BChatRoomMuteIndex.RebindRoom(1, room, room + 1000, required); }
    private static BChatRoomMuteIndex index(Context c, String route) { return new BChatRoomMuteIndex(c, S, route); }
    private static String repeat(char c, int count) { char[] value = new char[count]; Arrays.fill(value, c); return new String(value); }
    private static byte[] envelope(String route, long revision, Map<String, String> floors) {
        StringBuilder raw = new StringBuilder("{\"format_version\":1,\"scope_key\":\"").append(S).append("\",\"account_uuid\":\"").append(route)
                .append("\",\"revision\":").append(revision).append(",\"entries\":["); boolean first = true;
        for (Map.Entry<String, String> item : new TreeMap<>(floors).entrySet()) {
            if (!first) raw.append(','); first = false;
            raw.append("{\"room_key\":\"").append(item.getKey()).append("\",\"token\":\"").append(item.getValue()).append("\"}");
        }
        return raw.append("]}").toString().getBytes(StandardCharsets.UTF_8);
    }
    private static void write(File file, byte[] bytes) throws Exception { Files.createDirectories(file.getParentFile().toPath()); Files.write(file.toPath(), bytes); }
    private static void seed(Context c, String route, long revision, Map<String, String> floors) throws Exception { write(base(c), envelope(route, revision, floors)); }
    private static String sha(byte[] raw) throws Exception {
        StringBuilder result = new StringBuilder(); for (byte value : MessageDigest.getInstance("SHA-256").digest(raw)) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255)); return result.toString();
    }
    private static Map<String, String> slots(Context c) throws Exception {
        Map<String, String> result = new TreeMap<>(); File base = base(c);
        for (String suffix : new String[]{"", ".bak", ".new"}) {
            File file = new File(base + suffix); result.put(suffix.isEmpty() ? "base" : suffix.substring(1), file.exists() ? sha(Files.readAllBytes(file.toPath())) : "ABSENT");
        }
        return result;
    }
    private static BChatRoomMuteIndex.ForeignEvidence evidence(BChatRoomMuteIndex index) {
        BChatRoomMuteIndex.ForeignResult result = index.inspectForeignWorker(); check(result.kind == BChatRoomMuteIndex.Kind.FOREIGN && result.evidence != null, "complete foreign evidence"); return result.evidence;
    }
    private static final class Faults implements BChatRoomMuteIndex.AtomicFiles {
        String mode = "ok"; int creates, opens, starts, finishes;
        @Override public AtomicFile create(File file) {
            ++creates;
            return new AtomicFile(file) {
                @Override public FileOutputStream startWrite() throws IOException {
                    ++starts;
                    if (mode.equals("start")) throw new IOException("test before startWrite mutation");
                    if (mode.equals("sync")) return new FileOutputStream(file + ".new") {
                        @Override public void write(byte[] raw) throws IOException { super.write(raw); super.close(); }
                    }; // Actual subsequent getFD().sync fails on the closed descriptor.
                    return super.startWrite();
                }
                @Override public void finishWrite(FileOutputStream stream) {
                    ++finishes;
                    if (mode.equals("silent")) { try { stream.close(); } catch (IOException ignored) { } return; }
                    super.finishWrite(stream);
                    if (mode.equals("corrupt")) try { Files.write(file.toPath(), new byte[]{'{'}); } catch (IOException failure) { throw new IllegalStateException(failure); }
                    if (mode.equals("changed")) try { Files.write(file.toPath(), envelope(B, 99, Collections.emptyMap())); } catch (IOException failure) { throw new IllegalStateException(failure); }
                }
                @Override public FileInputStream openRead() throws IOException {
                    ++opens; if (mode.equals("readback") && finishes > 0) throw new IOException("test post-finish readback refusal"); return super.openRead();
                }
            };
        }
    }
    private static void rejectInspect(Context c, BChatRoomMuteIndex.Kind expected) throws Exception {
        Faults f = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, f); Map<String, String> before = slots(c);
        BChatRoomMuteIndex.ForeignResult result = value.inspectForeignWorker();
        check(result.kind == expected && result.evidence == null, "inspection kind/no evidence " + expected);
        check(f.creates == 0 && f.opens == 0 && f.starts == 0, "inspection never constructs AtomicFile or recovers"); check(before.equals(slots(c)), "inspection leaves all slot bytes/presence unchanged");
    }
    private static void rejectPlan(Context c, BChatRoomMuteIndex value, BChatRoomMuteIndex.ForeignEvidence proof,
            List<BChatRoomMuteIndex.RebindRoom> rooms, BChatRoomMuteIndex.Kind expected) throws Exception {
        Map<String, String> before = slots(c); BChatRoomMuteIndex.Result result = value.rebindForeignExact(proof, rooms);
        check(result.kind == expected && result.state == null && !result.readable(), "plan refusal kind/no foreign State " + expected);
        check(before.equals(slots(c)), "plan refusal leaves all slots unchanged");
    }
    private static void invalid(Action action) throws Exception { boolean refused = false; try { action.run(); } catch (IllegalArgumentException expected) { refused = true; } check(refused, "invalid typed IDs refused"); }
    private static void immutable(Action action) throws Exception { boolean refused = false; try { action.run(); } catch (UnsupportedOperationException expected) { refused = true; } check(refused, "immutable evidence/state"); }

    public static void main(String[] args) throws Exception {
        root = new File(args[0]);
        group("worker-and-evidence-boundaries", () -> {
            Context c = context(); Faults f = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, f);
            check(c.fileLookups == 0, "constructor has no disk lookup"); Looper.mainForTest(true);
            try {
                boolean blocked = false; try { value.inspectForeignWorker(); } catch (IllegalStateException expected) { blocked = true; }
                check(blocked && c.fileLookups == 0, "inspection MAIN refused before disk");
                blocked = false; try { value.rebindForeignExact(null, Collections.emptyList()); } catch (IllegalStateException expected) { blocked = true; }
                check(blocked && c.fileLookups == 0, "rebind MAIN refused before disk");
            } finally { Looper.mainForTest(false); }
            check(value.inspectForeignWorker().kind == BChatRoomMuteIndex.Kind.ABSENT, "absent inspection");
            check(!new File(c.getFilesDir(), "bchat-room-mute-index").exists(), "absent inspection no mkdir");
            seed(c, A, 9, Collections.singletonMap(key(A, 1), T1)); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
            check(proof.scopeKey.equals(S) && proof.oldAccountUuid.equals(A) && proof.newAccountUuid.equals(B) && proof.revision == 9, "evidence exact route/revision");
            check(proof.sourceSlot.equals("base") && proof.bytesSha256.equals(slots(c).get("base")), "source slot/bytes SHA");
            check(proof.slots.size() == 3 && proof.slots.get("base").present && !proof.slots.get("bak").present && proof.slots.get("new").sha256 == null, "all-slot presence/SHA evidence");
            immutable(() -> proof.floors.put(key(A, 2), T2)); immutable(() -> proof.slots.clear());
            for (Constructor<?> ctor : BChatRoomMuteIndex.ForeignEvidence.class.getDeclaredConstructors()) check(Modifier.isPrivate(ctor.getModifiers()), "evidence constructor private");
            int modifiers = BChatRoomMuteIndex.RebindRoom.class.getDeclaredField("candidateFloorToken").getModifiers();
            check(Modifier.isPrivate(modifiers) && Modifier.isFinal(modifiers), "candidate token private final");
            check(f.creates == 0, "foreign inspection did not invoke AtomicFile");
            rejectPlan(c, index(c, B), proof, Collections.emptyList(), BChatRoomMuteIndex.Kind.INVALID);
            check(!value.load().readable() && value.load().kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH, "ordinary load never accepts FOREIGN");
        });
        group("token-preserving-mapping-no-false-clear-no-gc", () -> {
            Context c = context(); BChatRoomMuteIndex old = index(c, A);
            check(old.put(key(A, 1), T1).kind == BChatRoomMuteIndex.Kind.COMMITTED, "seed via actual ordinary put");
            check(old.put(key(A, 2), T2).kind == BChatRoomMuteIndex.Kind.COMMITTED, "second floor via ordinary put");
            check(old.put(repeat('c', 64), T2).kind == BChatRoomMuteIndex.Kind.COMMITTED, "unmatched opaque floor");
            BChatRoomMuteIndex value = index(c, B); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
            BChatRoomMuteIndex.Result result = value.rebindForeignExact(proof, Arrays.asList(room(1, true), room(2, false), room(3, true), room(4, false)));
            check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && !result.readable(), "only COMMITTED and strict readable unchanged");
            check(result.state.revision == proof.revision + 1 && result.state.floors.size() == 4, "one revision and bounded mapping");
            check(T1.equals(result.state.token(key(B, 1))) && T2.equals(result.state.token(key(B, 2))), "matched tokens preserved even GET false");
            check(BChatRoomMuteIndex.uuid(result.state.token(key(B, 3))) && result.state.token(key(B, 4)) == null, "requiresFloor only adds when absent");
            check(T2.equals(result.state.token(repeat('c', 64))) && result.state.token(key(A, 1)) == null && result.state.token(key(A, 2)) == null, "opaque kept; matched old keys moved");
            immutable(() -> result.state.floors.clear());
            check(value.load().kind == BChatRoomMuteIndex.Kind.LOADED && value.load().state.floors.equals(result.state.floors), "exact current reload");
            check(Arrays.equals(Files.readAllBytes(base(c).toPath()), envelope(B, proof.revision + 1, result.state.floors)), "canonical exact saved bytes");
            check(value.inspectForeignWorker().kind == BChatRoomMuteIndex.Kind.NO_MATCH && value.inspectForeignWorker().evidence == null, "current UUID grants no foreign evidence");
            Map<String, String> after = slots(c);
            check(old.load().kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH && old.put(key(A, 1), T2).kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH
                    && old.clear(key(A, 1), T1).kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH, "late old route strict load/put/clear refused");
            check(after.equals(slots(c)), "late old operations no mutation");
        });
        group("typed-plan-bounds-and-duplicates", () -> {
            invalid(() -> room(0, false)); invalid(() -> room((long) Integer.MAX_VALUE + 1, false));
            invalid(() -> new BChatRoomMuteIndex.RebindRoom(0, 1, 1, false)); invalid(() -> new BChatRoomMuteIndex.RebindRoom(1, 1, -1, true));
            Context c = context(); seed(c, A, 2, Collections.singletonMap(key(A, 1), T1)); BChatRoomMuteIndex value = index(c, B); BChatRoomMuteIndex.ForeignEvidence p = evidence(value);
            rejectPlan(c, value, null, Collections.emptyList(), BChatRoomMuteIndex.Kind.INVALID);
            rejectPlan(c, value, p, null, BChatRoomMuteIndex.Kind.INVALID);
            rejectPlan(c, value, p, Collections.singletonList(null), BChatRoomMuteIndex.Kind.INVALID);
            rejectPlan(c, value, p, Arrays.asList(room(1, false), room(1, true)), BChatRoomMuteIndex.Kind.INVALID);
            rejectPlan(c, value, p, Arrays.asList(new BChatRoomMuteIndex.RebindRoom(1, 1, 7, false), new BChatRoomMuteIndex.RebindRoom(1, 2, 7, true)), BChatRoomMuteIndex.Kind.INVALID);
            List<BChatRoomMuteIndex.RebindRoom> many = new ArrayList<>(); for (int i = 1; i <= 101; ++i) many.add(room(i, false));
            rejectPlan(c, value, p, many, BChatRoomMuteIndex.Kind.INVALID);
        });
        group("real-destination-overlap-policy", () -> {
            for (boolean same : new boolean[]{true, false}) {
                Context c = context(); Map<String, String> floors = new TreeMap<>(); floors.put(key(A, 1), T1); floors.put(key(B, 1), same ? T1 : T2);
                seed(c, A, 4, floors); BChatRoomMuteIndex value = index(c, B); BChatRoomMuteIndex.ForeignEvidence p = evidence(value);
                if (same) {
                    BChatRoomMuteIndex.Result result = value.rebindForeignExact(p, Collections.singletonList(room(1, true)));
                    check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && result.state.floors.size() == 1 && T1.equals(result.state.token(key(B, 1))), "same destination token dedup without candidate replacement");
                } else rejectPlan(c, value, p, Collections.singletonList(room(1, true)), BChatRoomMuteIndex.Kind.INVALID);
            }
            Context c = context(); seed(c, A, 8, Collections.singletonMap(key(B, 2), T2)); BChatRoomMuteIndex value = index(c, B);
            BChatRoomMuteIndex.Result result = value.rebindForeignExact(evidence(value), Collections.singletonList(room(2, true)));
            check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && T2.equals(result.state.token(key(B, 2))), "existing destination floor never replaced by candidate");
        });
        group("same-objects-reorder-and-safe-retry", () -> {
            BChatRoomMuteIndex.RebindRoom first = room(1, true), second = room(2, true), third = room(3, false);
            List<BChatRoomMuteIndex.RebindRoom> order = new ArrayList<>(Arrays.asList(first, second, third)); byte[] saved = null;
            for (int pass = 0; pass < 2; ++pass) {
                Context c = context(); seed(c, A, 7, Collections.singletonMap(key(A, 3), T1)); Faults faults = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, faults);
                BChatRoomMuteIndex.ForeignEvidence proof = evidence(value); Map<String, String> prior = slots(c); faults.mode = "start";
                check(value.rebindForeignExact(proof, order).kind == BChatRoomMuteIndex.Kind.UNCERTAIN, "start exception is UNCERTAIN not fake rollback");
                check(prior.equals(slots(c)), "this injected pre-mutation failure actually retained evidence slots"); faults.mode = "ok";
                BChatRoomMuteIndex.Result result = value.rebindForeignExact(proof, order);
                check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && result.state.revision == 8 && T1.equals(result.state.token(key(B, 3))), "same evidence retry commits once");
                byte[] bytes = Files.readAllBytes(base(c).toPath());
                if (saved == null) saved = bytes; else check(Arrays.equals(saved, bytes), "reordered same immutable objects yield exact same canonical bytes/tokens");
                order.clear(); check(result.state.floors.size() == 3, "caller list mutation cannot alter committed snapshot"); order.addAll(Arrays.asList(second, third, first));
            }
        });
        group("inspection-refusal-kinds-and-slots", () -> {
            byte[] valid = envelope(A, 3, Collections.singletonMap(key(A, 1), T1));
            List<byte[]> invalids = Arrays.asList(new byte[]{(byte) 0xc3, (byte) 0x28}, new byte[]{'{'},
                    (" " + new String(valid, StandardCharsets.UTF_8)).getBytes(StandardCharsets.UTF_8),
                    new String(valid, StandardCharsets.UTF_8).replace("\"revision\":3", "\"revision\":0").getBytes(StandardCharsets.UTF_8),
                    new String(valid, StandardCharsets.UTF_8).replace("\"revision\":3", "\"revision\":3.0").getBytes(StandardCharsets.UTF_8),
                    new String(valid, StandardCharsets.UTF_8).replace("\"format_version\":1", "\"extra\":1,\"format_version\":1").getBytes(StandardCharsets.UTF_8),
                    new String(valid, StandardCharsets.UTF_8).replace(A, "invalid-uuid").getBytes(StandardCharsets.UTF_8));
            for (byte[] raw : invalids) { Context c = context(); write(base(c), raw); rejectInspect(c, BChatRoomMuteIndex.Kind.CORRUPT); }
            Context unsupported = context(); write(base(unsupported), new String(valid, StandardCharsets.UTF_8).replace("format_version\":1", "format_version\":2").getBytes(StandardCharsets.UTF_8)); rejectInspect(unsupported, BChatRoomMuteIndex.Kind.UNSUPPORTED);
            Context wrongScope = context(); write(base(wrongScope), new String(valid, StandardCharsets.UTF_8).replace(S, OTHER).getBytes(StandardCharsets.UTF_8)); rejectInspect(wrongScope, BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
            Context tooLarge = context(); write(base(tooLarge), new byte[BChatRoomMuteIndex.MAX_BYTES + 1]); rejectInspect(tooLarge, BChatRoomMuteIndex.Kind.TOO_LARGE);
            Context orphan = context(); write(new File(base(orphan) + ".new"), valid); rejectInspect(orphan, BChatRoomMuteIndex.Kind.CORRUPT);
            Context partial = context(); write(base(partial), valid); write(new File(base(partial) + ".new"), new byte[]{'{'}); rejectInspect(partial, BChatRoomMuteIndex.Kind.CORRUPT);
            Context mixed = context(); seed(mixed, B, 4, Collections.singletonMap(key(B, 1), T1)); write(new File(base(mixed) + ".bak"), valid); rejectInspect(mixed, BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
            Context mixedNew = context(); write(base(mixedNew), valid); write(new File(base(mixedNew) + ".new"), envelope(B, 4, Collections.emptyMap())); rejectInspect(mixedNew, BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
            Context current = context(); seed(current, B, 4, Collections.emptyMap()); rejectInspect(current, BChatRoomMuteIndex.Kind.NO_MATCH);
        });
        group("complete-new-slot-base-source-and-stale-new-cas", () -> {
            for (boolean remove : new boolean[]{true, false}) {
                Context c = context(); seed(c, A, 5, Collections.singletonMap(key(A, 1), T1));
                write(new File(base(c) + ".new"), envelope(A, 6, Collections.singletonMap(key(A, 2), T2)));
                Faults faults = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, faults); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
                check(proof.sourceSlot.equals("base") && proof.revision == 5 && proof.slots.get("new").present, "homogeneous complete new is evidence only, base source unchanged");
                if (remove) Files.delete(new File(base(c) + ".new").toPath());
                else write(new File(base(c) + ".new"), envelope(A, 7, Collections.singletonMap(key(A, 3), T2)));
                rejectPlan(c, value, proof, Collections.singletonList(room(1, false)), BChatRoomMuteIndex.Kind.NO_MATCH);
                check(faults.creates == 0, "existing-new removal/byte-change stale before recovery");
            }
            Context c = context(); seed(c, A, 5, Collections.singletonMap(key(A, 1), T1));
            write(new File(base(c) + ".new"), envelope(A, 6, Collections.singletonMap(key(A, 2), T2)));
            BChatRoomMuteIndex value = index(c, B); BChatRoomMuteIndex.Result result = value.rebindForeignExact(evidence(value), Collections.singletonList(room(1, false)));
            check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && result.state.revision == 6 && T1.equals(result.state.token(key(B, 1))) && result.state.floors.size() == 1,
                    "homogeneous base/new exact CAS commits chosen base, not new uncommitted state");
        });
        group("homogeneous-backup-priority-and-cas-recovery", () -> {
            for (boolean basePresent : new boolean[]{true, false}) {
                Context c = context(); if (basePresent) seed(c, A, 20, Collections.singletonMap(key(A, 2), T2));
                write(new File(base(c) + ".bak"), envelope(A, 10, Collections.singletonMap(key(A, 1), T1)));
                write(new File(base(c) + ".new"), envelope(A, 30, Collections.singletonMap(key(A, 3), T2)));
                Faults faults = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, faults); Map<String, String> before = slots(c);
                BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
                check(proof.sourceSlot.equals("bak") && proof.revision == 10 && proof.bytesSha256.equals(before.get("bak")), "bak source chosen without recovering");
                check(before.equals(slots(c)) && faults.creates == 0, "complete homogeneous inspection untouched");
                BChatRoomMuteIndex.Result result = value.rebindForeignExact(proof, Collections.singletonList(room(1, false)));
                check(result.kind == BChatRoomMuteIndex.Kind.COMMITTED && result.state.revision == 11 && T1.equals(result.state.token(key(B, 1))), "recovery after exact all-slot CAS uses chosen backup state");
                check(result.state.floors.size() == 1 && !new File(base(c) + ".bak").exists() && !new File(base(c) + ".new").exists(), "single current commit/reload, no merge of non-source slots");
                check(faults.starts == 1 && faults.finishes == 1, "one sync/finish write only");
            }
        });
        group("all-slot-bytes-presence-source-cas", () -> {
            for (int mutation = 0; mutation < 8; ++mutation) {
                Context c = context(); seed(c, A, 5, Collections.singletonMap(key(A, 1), T1));
                if (mutation >= 4) write(new File(base(c) + ".bak"), envelope(A, 4, Collections.singletonMap(key(A, 2), T2)));
                Faults faults = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, faults); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
                File b = base(c);
                switch (mutation) {
                    case 0: seed(c, A, 6, Collections.singletonMap(key(A, 1), T1)); break;
                    case 1: write(new File(b + ".new"), envelope(A, 5, Collections.emptyMap())); break;
                    case 2: write(new File(b + ".bak"), Files.readAllBytes(b.toPath())); break;
                    case 3: Files.move(b.toPath(), new File(b + ".bak").toPath()); break;
                    case 4: Files.delete(new File(b + ".bak").toPath()); break;
                    case 5: seed(c, A, 5, Collections.singletonMap(key(A, 3), T1)); break;
                    case 6: write(new File(b + ".bak"), envelope(A, 7, Collections.emptyMap())); break;
                    default: write(new File(b + ".new"), envelope(A, 6, Collections.emptyMap()));
                }
                rejectPlan(c, value, proof, Collections.singletonList(room(1, true)), BChatRoomMuteIndex.Kind.NO_MATCH);
                check(faults.creates == 0 && faults.starts == 0, "stale all-slot CAS never invokes AtomicFile");
            }
        });
        group("uncertain-boundaries-no-rollback-or-false-commit", () -> {
            for (String mode : new String[]{"sync", "silent", "readback", "corrupt", "changed"}) {
                Context c = context(); seed(c, A, 6, Collections.singletonMap(key(A, 1), T1)); Faults faults = new Faults(); faults.mode = mode;
                BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, B, faults); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
                BChatRoomMuteIndex.Result result = value.rebindForeignExact(proof, Collections.singletonList(room(1, false)));
                check(result.kind == BChatRoomMuteIndex.Kind.UNCERTAIN && result.state == null, mode + " not COMMITTED/foreign RAM");
                if (mode.equals("readback")) {
                    check(index(c, B).load().kind == BChatRoomMuteIndex.Kind.LOADED && T1.equals(index(c, B).load().state.token(key(B, 1))), "readback failure can have committed exact current bytes; not rollback");
                    rejectPlan(c, value, proof, Collections.singletonList(room(1, false)), BChatRoomMuteIndex.Kind.NO_MATCH);
                } else if (mode.equals("sync")) {
                    check(!new File(base(c) + ".new").exists() && index(c, A).load().kind == BChatRoomMuteIndex.Kind.LOADED, "pre-finish actual sync failure calls failWrite for this adapter");
                } else if (mode.equals("silent")) {
                    check(new File(base(c) + ".new").exists(), "silent finish leaves unknown durable new slot; no assumed repair");
                    rejectInspect(c, BChatRoomMuteIndex.Kind.ROUTE_MISMATCH);
                } else if (mode.equals("changed")) check(index(c, B).load().state.revision == 99, "valid current readback with wrong exact revision/bytes never COMMITTED");
                else check(index(c, B).load().kind == BChatRoomMuteIndex.Kind.CORRUPT, "post-finish corruption not hidden");
            }
        });
        group("capacity-revision-and-no-gc", () -> {
            Context c = context(); Map<String, String> full = new TreeMap<>(); for (int i = 1; i <= 100; ++i) full.put(key(A, i), T1);
            seed(c, A, 5, full); BChatRoomMuteIndex value = index(c, B); BChatRoomMuteIndex.ForeignEvidence proof = evidence(value);
            rejectPlan(c, value, proof, Collections.singletonList(room(101, true)), BChatRoomMuteIndex.Kind.CAPACITY);
            BChatRoomMuteIndex.Result moved = value.rebindForeignExact(proof, Collections.singletonList(room(1, true)));
            check(moved.kind == BChatRoomMuteIndex.Kind.COMMITTED && moved.state.floors.size() == 100 && T1.equals(moved.state.token(key(A, 100))), "move at capacity keeps 99 opaque floors; no eviction");
            Context all = context(); seed(all, A, 5, full); BChatRoomMuteIndex allIndex = index(all, B); List<BChatRoomMuteIndex.RebindRoom> allRooms = new ArrayList<>();
            for (int i = 1; i <= 100; ++i) allRooms.add(room(i, true));
            BChatRoomMuteIndex.Result allResult = allIndex.rebindForeignExact(evidence(allIndex), allRooms);
            check(allResult.kind == BChatRoomMuteIndex.Kind.COMMITTED && allResult.state.floors.size() == 100 && T1.equals(allResult.state.token(key(B, 100)))
                    && allResult.state.token(key(A, 100)) == null && base(all).length() <= BChatRoomMuteIndex.MAX_BYTES, "100 current full rooms bounded plan, same tokens/quota/schema");
            Context exhausted = context(); seed(exhausted, A, Long.MAX_VALUE, Collections.singletonMap(key(A, 1), T1)); BChatRoomMuteIndex ex = index(exhausted, B);
            rejectPlan(exhausted, ex, evidence(ex), Collections.singletonList(room(1, false)), BChatRoomMuteIndex.Kind.EXHAUSTED);
            Context empty = context(); seed(empty, A, 11, Collections.singletonMap(key(A, 1), T1)); BChatRoomMuteIndex unbound = index(empty, B);
            BChatRoomMuteIndex.Result opaque = unbound.rebindForeignExact(evidence(unbound), Collections.emptyList());
            check(opaque.kind == BChatRoomMuteIndex.Kind.COMMITTED && T1.equals(opaque.state.token(key(A, 1))) && opaque.state.revision == 12, "empty trusted plan changes route only, never clears opaque state");
        });
        group("mixed-route-late-writer-read-guard-and-backup-compatibility", () -> {
            Context c = context(); seed(c, B, 8, Collections.singletonMap(key(B, 1), T2)); write(new File(base(c) + ".bak"), envelope(A, 7, Collections.singletonMap(key(A, 1), T1)));
            for (String route : new String[]{A, B}) {
                Faults faults = new Faults(); BChatRoomMuteIndex value = new BChatRoomMuteIndex(c, S, route, faults);
                Map<String, String> before = slots(c);
                check(value.load().kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH, "mixed-route strict load " + route);
                check(before.equals(slots(c)), "load no AtomicFile recovery mutation");
                check(value.put(key(route, 1), T1).kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH, "mixed-route strict put");
                check(before.equals(slots(c)), "put all slot SHA/presence unchanged");
                check(value.clear(key(route, 1), T1).kind == BChatRoomMuteIndex.Kind.ROUTE_MISMATCH, "mixed-route strict clear");
                check(before.equals(slots(c)) && faults.creates == 0, "clear all slots untouched; no openRead");
            }
            Context corrupt = context(); write(base(corrupt), new byte[]{'{'}); write(new File(base(corrupt) + ".bak"), envelope(A, 7, Collections.singletonMap(key(A, 1), T1)));
            BChatRoomMuteIndex.Result restored = index(corrupt, A).load();
            check(restored.kind == BChatRoomMuteIndex.Kind.LOADED && restored.state.revision == 7 && T1.equals(restored.state.token(key(A, 1))), "corrupt base + valid same-route backup still recovers");
            check(!new File(base(corrupt) + ".bak").exists(), "existing recovery consumes backup only after same-route validation");
        });
        System.out.println("POLICY complete-all-slots canonical-V1 homogeneous-foreign bak-then-base; no inspect-openRead; partial/orphan/mixed refuse; source-destination SHA overlap source-reviewed-not-forced");
        System.out.println("PASS " + checks + " production room mute component assertions; DEV163 groups=" + groups + "; no old suite/auth/Store/Host/Android-runtime claim");
    }
}
