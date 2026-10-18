# C13 receipt durability acceptance — isolated Android tests

This APK is **not BChat**. It has a distinct `com.baseer.freshchat.receipts.test`
package and no permissions, network client, product account or UI Activity.
The builder uses only the existing JDK17 / Android SDK35 and downloads nothing.

## Executed evidence (2026-10-18)

- `all`: **69** assertions using Android35's real SQLite and `org.json`.
  Additive v1→v2 preserves cached content; legacy cache alone cannot create a
  read intent. References survive reopening, canonical+pin+intent commit together,
  read settles delivery too, exact membership/account purge cannot resurrect an
  old callback. Tests cover the combined1000-key admission boundary and an
  injected1MiB accounting boundary,500 pinned room rows, rollback on the501st,
  pin-aware retention, oversized UTF-8 canonical refusal and an actual SQLite
  trigger failure between canonical insertion and intent insertion.
- `seed-ref`, `canonical`, `settle`, `verify-settled`: **12** assertions across
  four separate instrumentation processes, force-stopping only this test package
  between invocations. This demonstrates durable references, committed canonical
  intent and settled proof across process lifetimes, not hardware power loss.
- `coordinator`: **1746** assertions in eleven journeys. The builder extracts the
  actual receipt coordinator methods and canonical validator from
  `OdooIdentityActivity.java`, checking the source hash before/after extraction.
  SQLite, JSON and `BChatStorageRepository`'s disk lane are production code;
  transport, room/view state, lifecycle host and unsupported-media fixture are
  explicit adapters. Journeys cover one failed reference alongside a good one,
  successful ACK after room navigation, lost-ACK retry of the same intent,
  failed canonical+intent transaction with no POST, missing/wrong epoch refusal,
  read-host gating, unsupported contract without offline labeling, and550
  delivered canonical messages drained while the bounded cache retains only
  rows51–550. Independent review added retained-room resumption after an unrelated
  revocation with pending disk work/repository invalidation; late ACK cannot clear
  a newer pass; an overlapping old Activity cannot borrow a new generation;
  and an already-delivered forward-cache row101 requests canonical revalidation
  before a read, with no read if its viewport moved meanwhile.

Two explicit negative extracted-code mutations reproduce the independent-review
failures: `--simulate-old-invalidation` omits the new purge reset and fails
`Coordinator assertion2`; `--simulate-old-read-proof` omits the missing-proof
revalidation and times out waiting for canonical GET101. These are negative
fixtures, **not historical full-source builds**. The first negative run's cleanup
wait obscured the primary assertion; the harness now always releases its gate
before checking it. The corrected negative logs retain the intended failures.

Subsequent independent review found a separate stale-room-snapshot ownership gap:
`mayRebind=false` prevented pump re-arm but still allowed `cache.reconcile` itself.
A new real shared-SQLite journey failed on the unmodified previous helper
(`Coordinator assertion3`, Activity`aae699fe…`), proving a late old Activity could
erase a newer same-account epoch's or another account's canonical refs/cache.
Admission, worker and callback now all require ownership of the current accepted
generation or its matching locally owned rebind target. The focused
`room-ownership` phase passed **15** assertions for both identity cases; the
existing legitimate local room-revocation/re-arm phase passed **14** assertions
again. The unchanged550-message journey, cache69 and restart12 suites were not
rerun for this narrow helper-only guard.

Current focused fix source:

- Activity SHA256: `f340515fea7b94d0f20ea260130a9504dc7632de404812e27bb848f86e5111c6`
- Extracted bodies SHA256: `3db673ca2f1280ba9b10c4ae7ce268fcd21e3c50e39df16fa0188ef50b5d97a9`
- Logs: `C13-room-ownership-RED-build.log`, `C13-room-ownership-RED.log`,
  `C13-room-ownership-GREEN-build.log`, `C13-room-ownership-GREEN.log`,
  `C13-room-invalidation-GREEN.log`.

The failed date negative initially exposed `DateTimeParseException` rather than
the protocol's intended `IllegalArgumentException`; the malformed date was
already refused. The public protocol now consistently wraps that parse error.
The69-assertion run then passed.

Logs: `artifacts/test-results/C13-receipts-android-all.log`,
`C13-receipts-process-restart-final.log`, `C13-receipts-build.log`,
`C13-receipts-coordinator.log`, `C13-old-invalidation-RED.log`,
`C13-old-read-proof-RED.log`.

For the1746-assertion earlier unmodified-source run (before the narrow ownership fix above):

- Activity SHA256: `aae699fe2118db791626594cbf30f0d2e784b1382e4807afa0006e42c30bdf96`
- Extracted method bodies SHA256: `658df1e3d7cdbc5d7ad02b70355f937b7d54e7a357863e404c7302a739595bf1`
- Cache SHA256: `b43f51d952616a4d70f7211c52123690e3ebe69f0d0123fee441ff697283217b`
- Protocol SHA256: `31432f1a6221f8837096da79ea80127d878fa5d33514f19ee59e7c12529692fe`
- Isolated test manifest SHA256: `624131c27613b51986fc3bd3925a4b8a9cf1849abb0768cfe65ffb3f8bcc1f86`

## Reproduce

1. Reserve the already authorized disposable emulator serial with the root agent;
   do not run parallel test Activities on the same emulator.
2. Run `python tools/build-receipt-tests.py` using the installed JDK17.
3. Sign only this disposable test APK with the already documented test signer.
   Never print or copy a password into a command or source file.
4. Install `artifacts/BChat-Receipt-Tests.apk` on the reserved emulator only.
5. Execute `adb -s <reserved-serial> shell am instrument -w -e phase all
   com.baseer.freshchat.receipts.test/com.baseer.freshchat.sync.test.ReceiptInstrumentation`.
6. Repeat with `-e phase coordinator`. For restart evidence invoke the four phase
   names above in order, with `am force-stop com.baseer.freshchat.receipts.test`
   between invocations. Do not uninstall or clear its database between those four.

## Limits

These tests do not establish HTTP correctness, real authentication, actual
viewport/focus/lock-screen behavior, the full product Activity, two physical
devices, FCM delivery, OEM background behavior, FPS, latency/SLA or complete C13
product acceptance. Sender-detail UI and the isolated Odoo HTTP/ORM evidence are
separate work. No product APK, deployment or version bump is produced here.
