package com.baseer.freshchat;
import android.content.Context;
import android.os.Looper;
import java.io.File;
import java.nio.file.Files;
/** Real JVM files; Context/Looper/AtomicFile/JSON remain explicit test adapters. */
public final class StoreJvm {
    public static void main(String[] args) throws Exception {
        File root = new File(args[0]); Files.createDirectories(root.toPath());
        StoreCases.Host host = new StoreCases.Host() {
            public Context context(String name) throws Exception { File path = new File(root, name); Files.createDirectories(path.toPath()); return new Context(path); }
            public File files(Context context) { try {
                java.lang.reflect.Field field = Context.class.getDeclaredField("files"); field.setAccessible(true); return (File) field.get(context);
            } catch (Exception error) { throw new AssertionError(error); } }
            public int lookups(Context context) { return context.fileLookups; }
            public void main(Runnable action) { Looper.mainForTest(true); try { action.run(); } finally { Looper.mainForTest(false); } }
        };
        int checks = args.length > 1 && args[1].equals("ambiguous-epoch") ? StoreCases.ambiguousEpoch(host)
                : args.length > 1 && args[1].equals("recovery") ? StoreRecoveryCases.run(host)
                : args.length > 1 && args[1].equals("membership-snapshot") ? StoreMembershipSnapshotCases.run(host)
                : StoreCases.run(host) + StoreRecoveryCases.run(host);
        System.out.println("PASS " + checks + " production RoomPreferencesStore checks on actual JVM files with explicit Context/Looper/AtomicFile/Gson-JSON adapters; no Android/process-restart/HTTP");
    }
}
