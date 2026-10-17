# Connected media store behavioral fixtures

`tools/test-connected-media-store.py` compiles the production `BChatConnectedMediaStore`,
`AccountScope` and `OutboxPolicy`, then exercises real files in a newly created temporary
directory. Nothing is connected to QA, a phone, a database or the network.

The Android `Context`, `ContentResolver`, `Uri`, `Cursor` and `OpenableColumns` surfaces are
explicit test adapters reused from `tests/jvm-media`. `android.util.AtomicFile` here models
the old backup protocol and current `.new` protocol, including backup recovery on `openRead`.
This is a deterministic protocol simulation, not Android instrumentation. The JSONObject
adapter uses an already installed Gradle Gson jar for ordinary flat metadata JSON. It is a
test-only dependency and is never part of the application or downloaded by this command.
Use `--gson-jar` or `BCHAT_TEST_GSON_JAR` if its installed location is not detected.

Run with the existing JDK on PATH:

```text
python tools/test-connected-media-store.py
python tools/test-connected-media-store.py --baseline-ref 5e061ac97eaf2e6a5cba7019895ae383f1216d49
```

The baseline mode runs the same original public API isolation scenario against the
pre-C01 production source and requires the corrupt-A/healthy-B IOException to reproduce.
The current suite tests corruption containment and bounded diagnostics, missing base plus
backup, metadata bounds, missing media, account/membership/company isolation, actual quota,
20 requests, old/fresh/active `.part` cleanup, provider-copy concurrency, permission revocation
during that copy, cross-helper receipt/scan serialization and exact acknowledgement retirement.

No claim is made about real Android filesystem/OEM crash behavior, FPS, heap peak, ANRs or
phone acceptance. Those remain candidate acceptance tests on the actual runtime.
