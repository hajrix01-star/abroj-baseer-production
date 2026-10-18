package com.baseer.freshchat;

import android.content.Context;
import android.os.Looper;
import android.util.AtomicFile;
import com.baseer.freshchat.sync.AccountScope;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;

/** Nine focused component families. Actual production Owner/Port/Index and JVM private files;
 * explicit existing Context/Looper/AtomicFile/Gson-JSON adapters, deterministic queue, and
 * reflection ONLY to construct the Controller-private restriction-ticket test fixture.
 * No authentication, wire JSON parser, Android runtime, transport or notification effect.
 */
public final class OwnerCases {
    private static int checks, next;
    private static File root;
    private static final String ACCOUNT = "00000000-0000-4000-8000-000000000099";
    private static final String OTHER = "00000000-0000-4000-8000-000000000098";
    private static final String REQUEST = "00000000-0000-4000-8000-000000000001";
    private static final String TOKEN = "00000000-0000-4000-8000-000000000002";
    private static final Map<String, Integer> families = new LinkedHashMap<>();
    private static synchronized void check(boolean condition, String name) {
        ++checks; if (!condition) throw new AssertionError("Owner check " + checks + ": " + name);
    }
    interface Action { void run() throws Exception; }
    private static void family(String name, Action work) throws Exception {
        int start = checks; work.run(); families.put(name, checks - start);
        System.out.println("FAMILY " + name + " PASS " + (checks - start));
    }
    static final class Gate implements BChatRoomMutePort.Gate {
        private final ThreadLocal<Integer> depth = ThreadLocal.withInitial(() -> 0);
        int maxDepth;
        Runnable beforeNext, nested;
        boolean held() { return depth.get() != 0; }
        public <T> T run(BChatRoomMutePort.Value<T> value) {
            Runnable before = beforeNext; beforeNext = null;
            if (before != null) before.run(); // Explicit test pause immediately before CAS.
            synchronized (this) {
                int prior = depth.get(); depth.set(prior + 1); maxDepth = Math.max(maxDepth, prior + 1);
                try {
                    Runnable hook = prior == 1 ? nested : null;
                    if (hook != null) { nested = null; hook.run(); }
                    return value.get();
                } finally { depth.set(prior); }
            }
        }
    }
    static final class Queue implements RoomPreferencesController.Scheduler {
        final Gate gate;
        final ArrayDeque<Runnable> worker = new ArrayDeque<>(), main = new ArrayDeque<>();
        Queue(Gate gate) { this.gate = gate; }
        public void worker(Runnable value) { check(!gate.held(), "No worker scheduling under gate"); worker.add(value); }
        public void main(Runnable value) { check(!gate.held(), "No MAIN scheduling under gate"); main.add(value); }
        public boolean isMain() { check(!gate.held(), "No scheduler callback under gate"); return Looper.myLooper() == Looper.getMainLooper(); }
        void drain() {
            int bound = 100;
            while (!worker.isEmpty() || !main.isEmpty()) {
                check(--bound > 0, "Bounded queue");
                if (!main.isEmpty()) { Looper.mainForTest(true); main.remove().run(); }
                else { Looper.mainForTest(false); try { worker.remove().run(); } finally { Looper.mainForTest(true); } }
            }
        }
    }
    static final class Env {
        final File files;
        final Gate gate = new Gate();
        final Queue queue = new Queue(gate);
        final Context context;
        final AccountScope account = new AccountScope("https://owner.invalid", "owner-fixture", 11);
        final Object identity = new Object(), session = new Object();
        final BChatRoomMuteIndex index;
        final BChatRoomPreferencesOwner owner;
        int creates, writes;
        Runnable onRead;
        Env() throws Exception {
            files = new File(root, "private-" + (++next)); Files.createDirectory(files.toPath());
            context = new Context(files) {
                public File getFilesDir() { check(!gate.held(), "No Context disk lookup under gate"); return super.getFilesDir(); }
            };
            index = new BChatRoomMuteIndex(context, account.key, ACCOUNT, base -> {
                check(!gate.held(), "No AtomicFile construction under gate"); ++creates;
                return new AtomicFile(base) {
                    public FileInputStream openRead() throws IOException {
                        check(!gate.held(), "No read under gate");
                        FileInputStream stream = super.openRead();
                        Runnable hook = onRead; onRead = null; if (hook != null) hook.run(); return stream;
                    }
                    public void finishWrite(FileOutputStream stream) {
                        check(!gate.held(), "No sync/finish under gate"); ++writes; super.finishWrite(stream);
                    }
                };
            });
            owner = new BChatRoomPreferencesOwner(index, gate, queue);
        }
        BChatRoomPreferencesOwner.VerifiedRoutes data() { return OwnerCases.data(account, identity, session, 1, 2, 1, 7, 17, 23); }
        BChatRoomPreferencesOwner.PublishResult publish() { return owner.publishVerifiedRoutes(owner.snapshot(), data()); }
        RoomPreferencesController.Binding binding() { return owner.snapshot().routes.get(17L).binding; }
        String key(long company, long room, long member) { return NotificationPresentation.roomKey(ACCOUNT, company, room, member); }
        String key() { return key(7, 17, 23); }
        boolean blocks(String key) { return owner.blocks(owner.snapshot(), account.key, ACCOUNT, key); }
        BChatRoomPreferencesOwner.LoadResult load() {
            Looper.mainForTest(false); try { return owner.loadColdWorker(owner.snapshot()); } finally { Looper.mainForTest(true); }
        }
        BChatRoomMuteIndex.Result disk() {
            Looper.mainForTest(false); try { return index.load(); } finally { Looper.mainForTest(true); }
        }
        void seed() {
            Looper.mainForTest(false);
            try { check(index.put(key(), TOKEN).kind == BChatRoomMuteIndex.Kind.COMMITTED, "Actual private-file seed committed"); }
            finally { Looper.mainForTest(true); }
        }
        File base() { return new File(files, "bchat-room-mute-index/" + account.key + ".json"); }
    }
    private static BChatRoomPreferencesOwner.RoomSpec spec(long company, long room, long member) {
        return new BChatRoomPreferencesOwner.RoomSpec(company, room, member);
    }
    private static BChatRoomPreferencesOwner.VerifiedRoutes data(AccountScope account, Object identity, Object session,
            long global, long repository, int version, long company, long room, long member) {
        return new BChatRoomPreferencesOwner.VerifiedRoutes(account, identity, session, global, repository, version,
                Arrays.asList(company), Arrays.asList(spec(company, room, member)));
    }
    private static void invalid(Env env, BChatRoomPreferencesOwner.VerifiedRoutes data, BChatRoomPreferencesOwner.Kind kind) {
        BChatRoomPreferencesOwner.Frame before = env.owner.snapshot();
        BChatRoomPreferencesOwner.PublishResult result = env.owner.publishVerifiedRoutes(before, data);
        check(result.kind == kind && result.frame != before && result.frame == env.owner.snapshot(), "Invalid current rotates exactly one Frame");
        check(result.frame.routes.isEmpty() && !result.frame.scopedAvailable, "No partial routes or bare notification allowance");
        for (BChatRoomMutePort.Route old : before.routes.values()) check(!old.binding.authority.valid(), "Old Authority revoked before invalid publication");
        check(env.blocks(env.key()), "Invalid current fail-closed even with a healthy index");
    }
    private static void constructorCopy() throws Exception {
        Env env = new Env();
        check(env.context.fileLookups == 0 && env.creates == 0 && env.queue.worker.isEmpty() && env.queue.main.isEmpty(), "Constructor is RAM-only, no disk/queue");
        check(!new File(env.files, "bchat-room-mute-index").exists(), "Constructor creates no directory");
        BChatRoomPreferencesOwner.Frame first = env.owner.snapshot();
        check(first.routes.isEmpty() && !first.revoked && env.owner.current(null) == null, "Cold frame has no invented Binding");
        try { first.routes.put(1L, null); check(false, "Frame mutable"); } catch (UnsupportedOperationException expected) { check(true, "Immutable Frame map"); }
        List<Long> companies = new ArrayList<>(Arrays.asList(7L));
        List<BChatRoomPreferencesOwner.RoomSpec> rooms = new ArrayList<>(Arrays.asList(spec(7, 17, 23)));
        BChatRoomPreferencesOwner.VerifiedRoutes data = new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 1, 2, 1, companies, rooms);
        companies.clear(); rooms.clear();
        try { data.rooms.clear(); check(false, "DTO mutable"); } catch (UnsupportedOperationException expected) { check(true, "Immutable defensive DTO copy"); }
        BChatRoomMutePort port = env.owner.port;
        check(env.owner.publishVerifiedRoutes(first, data).frame.routes.size() == 1, "Original-list mutation cannot change published inputs");
        check(env.owner.port == port && env.owner.current(env.binding()).companyId == 7, "One stable shared Port and current route");
        check(env.context.fileLookups == 0 && env.queue.worker.isEmpty() && env.queue.main.isEmpty(), "RAM publication performs no disk/queue");
        try { new BChatRoomPreferencesOwner(null, env.gate, env.queue); check(false, "Null index accepted"); }
        catch (IllegalArgumentException expected) { check(true, "Fixed index required"); }
    }
    private static void limits() throws Exception {
        Env env = new Env(); env.load();
        List<BChatRoomPreferencesOwner.RoomSpec> rooms = new ArrayList<>();
        for (int id = 1; id <= 100; ++id) rooms.add(spec(7, id, id + 100));
        BChatRoomPreferencesOwner.VerifiedRoutes hundred = new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, Long.MAX_VALUE, 1, Arrays.asList(7L), rooms);
        check(env.owner.publishVerifiedRoutes(env.owner.snapshot(), hundred).frame.routes.size() == 100, "100 full-account routes admitted");
        rooms.add(spec(7, 101, 201));
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, Arrays.asList(7L), rooms), BChatRoomPreferencesOwner.Kind.INVALID);
        for (long bad : new long[]{-1, 0, 2147483648L, Long.MAX_VALUE}) {
            invalid(env, data(env.account, env.identity, env.session, 0, 0, 1, bad, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
            invalid(env, data(env.account, env.identity, env.session, 0, 0, 1, 7, bad, 23), BChatRoomPreferencesOwner.Kind.INVALID);
            invalid(env, data(env.account, env.identity, env.session, 0, 0, 1, 7, 17, bad), BChatRoomPreferencesOwner.Kind.INVALID);
        }
        check(env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(env.account, env.identity, env.session, 0, 0, 1,
                Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE)).kind == BChatRoomPreferencesOwner.Kind.PUBLISHED, "MAX_INT company/room/member admitted");
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, Arrays.asList(7L, 8L),
                Arrays.asList(spec(7, 17, 23), spec(8, 17, 24))), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, Arrays.asList(7L, 7L),
                Arrays.asList(spec(7, 17, 23))), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, Arrays.asList(8L),
                Arrays.asList(spec(7, 17, 23))), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, Arrays.asList(7L),
                Arrays.asList((BChatRoomPreferencesOwner.RoomSpec) null)), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 0, 0, 1, null, null), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, data(env.account, env.identity, env.session, -1, 0, 1, 7, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, data(env.account, env.identity, env.session, 0, -1, 1, 7, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, data(env.account, null, env.session, 0, 0, 1, 7, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, data(env.account, env.identity, null, 0, 0, 1, 7, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
        invalid(env, data(new AccountScope("https://other.invalid", "other", 1), env.identity, env.session, 0, 0, 1, 7, 17, 23), BChatRoomPreferencesOwner.Kind.INVALID);
        for (int version : new int[]{0, 2, -1}) invalid(env, data(env.account, env.identity, env.session, 0, 0, version, 7, 17, 23), BChatRoomPreferencesOwner.Kind.UNSUPPORTED);
    }
    private static void generations() throws Exception {
        Env env = new Env(), foreign = new Env(); env.load();
        BChatRoomPreferencesOwner.Frame initial = env.owner.snapshot(), first = env.publish().frame;
        RoomPreferencesController.Binding binding = env.binding();
        BChatRoomPreferencesOwner.Frame second = env.publish().frame;
        check(first != second && binding == env.binding(), "Accepted unchanged publication rotates Frame but retains Binding");
        check(env.owner.publishVerifiedRoutes(initial, null).kind == BChatRoomPreferencesOwner.Kind.STALE, "Invalid stale publish is strict no-op");
        check(env.owner.publishVerifiedRoutes(foreign.owner.snapshot(), null).kind == BChatRoomPreferencesOwner.Kind.STALE, "Invalid foreign publish is strict no-op");
        check(env.owner.snapshot() == second && binding.authority.valid(), "Stale/foreign never revoke current");
        check(env.owner.invalidateBindings(first, null) == second && !env.owner.revokeRoute(first), "Stale invalidation/revoke no-op");
        check(env.owner.invalidateBindings(foreign.owner.snapshot(), BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED) == second, "Foreign invalidation no-op");
        invalid(env, null, BChatRoomPreferencesOwner.Kind.INVALID);
        BChatRoomPreferencesOwner.Frame empty = env.owner.snapshot(); invalid(env, null, BChatRoomPreferencesOwner.Kind.INVALID);
        check(empty != env.owner.snapshot() && !binding.authority.valid(), "Repeated accepted invalid current rotates even empty frame");
        check(env.publish().kind == BChatRoomPreferencesOwner.Kind.PUBLISHED && !env.blocks(env.key()), "Explicit valid current publication can recover scope projection");
        check(env.owner.blocks(first, env.account.key, ACCOUNT, env.key()), "Old generation never permits scoped presentation");
    }
    private static void sessionAba() throws Exception {
        Env env = new Env(); BChatRoomPreferencesOwner.Frame requestA = env.publish().frame;
        RoomPreferencesController.Binding old = env.binding();
        BChatRoomPreferencesOwner.Frame afterInvalidation = env.owner.invalidateBindings(requestA, BChatRoomPreferencesOwner.Reason.IDENTITY_CHANGED);
        check(afterInvalidation != requestA && !old.authority.valid(), "Invalidate before identity publication");
        Object sessionB = new Object();
        env.owner.publishVerifiedRoutes(afterInvalidation, data(env.account, env.identity, sessionB, 1, 2, 1, 7, 17, 23));
        RoomPreferencesController.Binding b = env.binding();
        check(env.owner.publishVerifiedRoutes(requestA, env.data()).kind == BChatRoomPreferencesOwner.Kind.STALE && env.binding() == b, "Old session response cannot revive A");
        env.publish();
        check(env.binding() != old && env.binding().authority != old.authority && !b.authority.valid(), "Same session token returning cannot revive revoked Authority");
        BChatRoomPreferencesOwner.Frame expected = env.owner.snapshot();
        env.gate.beforeNext = () -> env.owner.invalidateBindings(expected, BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED);
        check(env.owner.publishVerifiedRoutes(expected, env.data()).kind == BChatRoomPreferencesOwner.Kind.STALE, "Final CAS rejects invalidation between validation and publication");
        check(env.owner.snapshot().routes.isEmpty(), "Race does not partially restore routes");
    }
    private static void exactRetention() throws Exception {
        Env env = new Env(); env.publish();
        RoomPreferencesController.Binding old = env.binding();
        env.publish(); check(env.binding() == old && env.owner.current(old) != null, "Exact complete tuple retains Authority");
        Object[] identities = {new Object(), env.identity, env.identity, env.identity, env.identity, env.identity};
        Object[] sessions = {env.session, new Object(), env.session, env.session, env.session, env.session};
        for (int step = 0; step < identities.length; ++step) {
            env.publish(); old = env.binding();
            AccountScope scope = step == 2 ? new AccountScope(env.account.origin, env.account.database, env.account.userId) : env.account;
            long global = step == 3 ? 2 : 1, repo = step == 4 ? 3 : 2, member = step == 5 ? 24 : 23;
            env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(scope, identities[step], sessions[step], global, repo, 1, 7, 17, member));
            check(!old.authority.valid() && env.owner.current(old) == null && env.binding() != old, "Changed tuple component revokes old: " + step);
        }
        env.publish(); old = env.binding();
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(env.account, env.identity, env.session, 1, 2, 1, 8, 17, 23));
        check(!old.authority.valid() && env.owner.current(old) == null && env.owner.current(env.binding()).companyId == 8, "Company change revokes despite same Binding fields");
        old = env.binding(); old.authority.invalidate();
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(env.account, env.identity, env.session, 1, 2, 1, 8, 17, 23));
        check(env.binding() != old && env.binding().authority.valid(), "Invalid Authority is never retained or rearmed");
        old = env.binding();
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 1, 2, 1,
                Arrays.asList(7L, 8L), Arrays.asList(spec(8, 17, 23), spec(7, 18, 24))));
        check(env.binding() == old && env.owner.snapshot().routes.size() == 2, "Full account projection, not a company filter");
        RoomPreferencesController.Binding removed = env.owner.snapshot().routes.get(18L).binding;
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(env.account, env.identity, env.session, 1, 2, 1, 8, 17, 23));
        check(env.binding() == old && !removed.authority.valid(), "Only removed route revoked in complete replacement");
        RoomPreferencesController.Binding forged = new RoomPreferencesController.Binding(env.account, env.identity, env.session,
                new RoomPreferencesController.Authority(), 1, 2, 17, 23, 1);
        check(env.owner.current(forged) == null, "Caller cannot supply an Authority to match Owner");
        invalid(env, data(env.account, env.identity, env.session, 1, 2, 2, 8, 17, 23), BChatRoomPreferencesOwner.Kind.UNSUPPORTED);
    }
    private static void rejoinFloor() throws Exception {
        Env env = new Env(); env.publish(); env.seed();
        check(env.load().storageKind == BChatRoomMuteIndex.Kind.LOADED && env.blocks(env.key()), "Durable old member floor restored");
        RoomPreferencesController.Binding old = env.binding();
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), data(env.account, env.identity, env.session, 1, 2, 1, 7, 17, 24));
        String joined = env.key(7, 17, 24);
        check(!old.authority.valid() && env.owner.port.health(old).status == BChatRoomMutePort.HealthStatus.UNKNOWN, "Rejoin revokes old binding; no false health");
        check(env.blocks(env.key()) && !env.blocks(joined), "Old exact floor persists without inheritance to new member");
        check(TOKEN.equals(env.disk().state.token(env.key())) && env.disk().state.token(joined) == null, "No GC or new-member floor on disk");
        env.owner.publishVerifiedRoutes(env.owner.snapshot(), new BChatRoomPreferencesOwner.VerifiedRoutes(env.account, env.identity, env.session, 1, 2, 1,
                Collections.emptyList(), Collections.emptyList()));
        check(env.owner.snapshot().routes.isEmpty() && TOKEN.equals(env.disk().state.token(env.key())), "Removal preserves old durable metadata");
        env.publish(); check(env.blocks(env.key()), "Old exact member key returning still has conservative floor");
    }
    private static void coldFiles() throws Exception {
        Env absent = new Env(); BChatRoomPreferencesOwner.Frame first = absent.owner.snapshot();
        check(absent.blocks(absent.key()), "Cold unknown blocks before worker load");
        check(absent.owner.port.health(null).status == BChatRoomMutePort.HealthStatus.UNKNOWN, "No missing-binding READY before cold load");
        try { absent.owner.loadColdWorker(first); check(false, "MAIN load accepted"); }
        catch (IllegalStateException expected) { check(absent.context.fileLookups == 0, "MAIN rejected before disk"); }
        BChatRoomPreferencesOwner.LoadResult loaded = absent.load();
        check(loaded.kind == BChatRoomPreferencesOwner.Kind.COLD_LOADED && loaded.storageKind == BChatRoomMuteIndex.Kind.ABSENT, "ABSENT is healthy scoped index absence only");
        check(first == loaded.frame && first.routes.isEmpty() && !absent.blocks(absent.key()), "Cold load neither creates Binding nor rotates Frame");
        RoomPreferencesController.Binding invented = new RoomPreferencesController.Binding(absent.account, absent.identity, absent.session,
                new RoomPreferencesController.Authority(), 1, 2, 17, 23, 1);
        check(absent.owner.current(invented) == null && absent.owner.port.health(invented).status == BChatRoomMutePort.HealthStatus.UNKNOWN, "Valid bare index never authenticates invented Binding");
        for (int corruption = 0; corruption < 5; ++corruption) {
            Env env = new Env(); env.seed();
            byte[] bytes = Files.readAllBytes(env.base().toPath());
            if (corruption == 0) Files.write(env.base().toPath(), new byte[0]);
            if (corruption == 1) Files.write(env.base().toPath(), new byte[]{(byte) 0xc3, (byte) 0x28});
            if (corruption == 2) Files.write(env.base().toPath(), Arrays.copyOf(bytes, 15));
            if (corruption == 3) Files.write(env.base().toPath(), new String(bytes, StandardCharsets.UTF_8).replace(ACCOUNT, OTHER).getBytes(StandardCharsets.UTF_8));
            if (corruption == 4) { Files.move(env.base().toPath(), new File(env.base() + ".new").toPath()); }
            BChatRoomPreferencesOwner.LoadResult result = env.load();
            check(result.kind == BChatRoomPreferencesOwner.Kind.COLD_UNAVAILABLE && env.blocks(env.key()), "Invalid cold file stays blocked: " + corruption);
            check(result.storageKind == (corruption == 3 ? BChatRoomMuteIndex.Kind.ROUTE_MISMATCH : BChatRoomMuteIndex.Kind.CORRUPT), "Precise cold failure class: " + corruption);
            check(env.owner.snapshot().routes.isEmpty(), "No partial cold Binding restoration");
        }
    }
    private static void lifetime() throws Exception {
        Env env = new Env(); env.publish(); env.seed(); env.load();
        byte[] before = Files.readAllBytes(env.base().toPath()); int disk = env.context.fileLookups, writes = env.writes;
        for (BChatRoomPreferencesOwner.Reason reason : BChatRoomPreferencesOwner.Reason.values()) {
            RoomPreferencesController.Binding old = env.binding();
            BChatRoomPreferencesOwner.Frame prior = env.owner.snapshot();
            BChatRoomPreferencesOwner.Frame nextFrame = env.owner.invalidateBindings(prior, reason);
            check(nextFrame != prior && !old.authority.valid() && env.blocks(env.key()), "Invalidation blocks and rotates without clearing floor: " + reason);
            env.publish(); check(env.blocks(env.key()), "Same route floor survives republish: " + reason);
        }
        check(env.context.fileLookups == disk && env.writes == writes && Arrays.equals(before, Files.readAllBytes(env.base().toPath())), "All binding invalidations/publishes are RAM-only; durable bytes unchanged");
        BChatRoomPreferencesOwner.Frame current = env.owner.snapshot(); RoomPreferencesController.Binding old = env.binding();
        check(env.owner.revokeRoute(current), "Terminal current revocation admitted");
        BChatRoomPreferencesOwner.Frame terminal = env.owner.snapshot();
        check(terminal != current && terminal.revoked && !old.authority.valid(), "Terminal mutation rotates and revokes Authority");
        check(env.owner.publishVerifiedRoutes(terminal, env.data()).kind == BChatRoomPreferencesOwner.Kind.REVOKED && env.owner.snapshot() == terminal, "Terminal Owner cannot be rearmed");
        check(!env.owner.revokeRoute(terminal) && env.owner.invalidateBindings(terminal, null) == terminal, "Repeated terminal mutation not accepted");
        check(env.load().kind == BChatRoomPreferencesOwner.Kind.REVOKED && env.context.fileLookups == disk, "Terminal cold load does no I/O");
        check(env.blocks(env.key()) && env.owner.blocks(current, env.account.key, ACCOUNT, env.key()), "Revoked/current-old scoped predicates blocked");
        check(env.owner.blocks(terminal, "bad", ACCOUNT, env.key()) && env.owner.blocks(terminal, env.account.key, OTHER, env.key()), "Wrong scope/UUID blocked");
        Env healthy = new Env(); healthy.load();
        check(healthy.owner.blocks(healthy.owner.snapshot(), "bad", ACCOUNT, healthy.key()), "Healthy mirror rejects foreign scope");
        check(healthy.owner.blocks(healthy.owner.snapshot(), healthy.account.key, OTHER, healthy.key()), "Healthy mirror rejects foreign registered UUID");
        check(healthy.blocks("bad") && healthy.blocks(null), "Malformed room hash blocked without guessing");
    }
    private static RoomPreferencesController.RestrictionTicket restriction(RoomPreferencesController.Binding binding, RoomPreferencesProtocol.Pending pending) throws Exception {
        Class<?> ticket = Class.forName("com.baseer.freshchat.RoomPreferencesController$Ticket");
        Constructor<?> first = ticket.getDeclaredConstructor(RoomPreferencesController.Binding.class, long.class); first.setAccessible(true);
        Constructor<?> second = RoomPreferencesController.RestrictionTicket.class.getDeclaredConstructor(ticket, RoomPreferencesProtocol.Pending.class, RoomPreferencesController.RestrictionReason.class);
        second.setAccessible(true);
        return (RoomPreferencesController.RestrictionTicket) second.newInstance(first.newInstance(binding, 1L), pending, RoomPreferencesController.RestrictionReason.USER_INTENT);
    }
    private static RoomPreferencesProtocol.Pending pending(RoomPreferencesController.Binding binding) throws Exception {
        JSONObject body = new JSONObject().put("api_version", 2).put("room_id", binding.roomId).put("membership_id", binding.membershipId)
                .put("revision", 1).put("muted_until", JSONObject.NULL).put("mute_forever", false).put("muted", false)
                .put("pinned", false).put("pinned_at", JSONObject.NULL).put("archived", false);
        return RoomPreferencesProtocol.newPending(RoomPreferencesProtocol.freshSnapshot(body, binding.account, binding.roomId, binding.membershipId), REQUEST, null, true, false, false);
    }
    private static void racesAndPort() throws Exception {
        Env env = new Env(); env.publish(); env.load();
        RoomPreferencesController.Binding binding = env.binding(); RoomPreferencesProtocol.Pending pending = pending(binding);
        Object admission = env.owner.port.prepare(restriction(binding, pending));
        check(admission != null && env.blocks(env.key()) && env.disk().kind == BChatRoomMuteIndex.Kind.ABSENT, "Atomic RAM floor before queued actual-file commit");
        check(!env.owner.port.currentDurable(admission, binding, pending), "Not durable before index commit");
        env.queue.drain();
        check(env.owner.port.currentDurable(admission, binding, pending) && env.disk().state.token(env.key()) != null, "Delegated Port admits only after exact durable index");
        check(env.gate.maxDepth >= 2, "Final Owner + Port predicate uses same reentrant gate");
        env.owner.invalidateBindings(env.owner.snapshot(), BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED);
        check(!env.owner.port.currentDurable(admission, binding, pending), "Old admission revoked with binding");

        Env late = new Env(); late.seed(); BChatRoomPreferencesOwner.Frame expected = late.owner.snapshot();
        late.onRead = () -> late.owner.invalidateBindings(expected, BChatRoomPreferencesOwner.Reason.TOKEN_ROTATED);
        Looper.mainForTest(false); BChatRoomPreferencesOwner.LoadResult stale;
        try { stale = late.owner.loadColdWorker(expected); } finally { Looper.mainForTest(true); }
        check(stale.kind == BChatRoomPreferencesOwner.Kind.STALE && stale.storageKind == BChatRoomMuteIndex.Kind.LOADED, "Late cold file result cannot revive invalidated Frame");
        check(late.owner.snapshot().routes.isEmpty() && late.blocks(late.key(7, 18, 24)), "Late known index does not rearm invalidated scoped presentation");

        Env race = new Env(); race.publish(); race.load(); BChatRoomPreferencesOwner.Frame frame = race.owner.snapshot();
        CountDownLatch attempted = new CountDownLatch(1); AtomicBoolean invalidated = new AtomicBoolean();
        AtomicReference<Throwable> error = new AtomicReference<>();
        Thread invalidator = new Thread(() -> {
            try { attempted.countDown(); race.owner.invalidateBindings(frame, BChatRoomPreferencesOwner.Reason.RIGHTS_CHANGED); invalidated.set(true); }
            catch (Throwable failure) { error.set(failure); }
        }, "owner-fixture-invalidation");
        race.gate.nested = () -> {
            invalidator.start();
            try { check(attempted.await(3, TimeUnit.SECONDS), "Concurrent invalidation reached gate"); }
            catch (InterruptedException failure) { throw new AssertionError(failure); }
            check(!invalidated.get(), "No gap between Owner check and delegated Port.blocks");
        };
        boolean decision = race.owner.blocks(frame, race.account.key, ACCOUNT, race.key());
        invalidator.join(3000);
        check(!invalidator.isAlive() && error.get() == null && invalidated.get(), "Contending mutation completes after scoped decision");
        check(!decision && race.owner.blocks(frame, race.account.key, ACCOUNT, race.key()) && race.blocks(race.key()), "Decision linearized before invalidation; all subsequent checks fail closed");
    }
    public static void main(String[] args) throws Exception {
        root = new File(args[0]); Looper.mainForTest(true);
        family("constructor-copy", OwnerCases::constructorCopy);
        family("limits-validation", OwnerCases::limits);
        family("generation-stale-invalid", OwnerCases::generations);
        family("session-aba-publication-cas", OwnerCases::sessionAba);
        family("exact-authority-retention", OwnerCases::exactRetention);
        family("rejoin-floor-preservation", OwnerCases::rejoinFloor);
        family("cold-files-missing-binding", OwnerCases::coldFiles);
        family("token-terminal-route-lifetime", OwnerCases::lifetime);
        family("port-durable-and-ram-races", OwnerCases::racesAndPort);
        JSONObject familyCounts = new JSONObject();
        for (Map.Entry<String, Integer> family : families.entrySet()) familyCounts.put(family.getKey(), family.getValue());
        JSONObject result = new JSONObject().put("schema", 1).put("assertions", checks).put("families", familyCounts)
                .put("scope", "Production RAM Owner/Port/Index; actual JVM private files; explicit Android/AtomicFile/Gson-JSON/queue/reflection fixtures; SDK35 compile only, no Android/HTTP/auth/FCM/power-loss");
        Files.write(new File(root, "owner-results.json").toPath(), result.toString().getBytes(StandardCharsets.UTF_8));
        System.out.println("PASS " + checks + " production room preferences Owner assertions; 9 focused families");
    }
}
