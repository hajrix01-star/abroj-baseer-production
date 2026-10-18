# C09 targeted acceptance

The standalone test APK is **not the product APK**. It uses only package
`com.baseer.freshchat.transfer.test` and the explicitly selected disposable emulator.
No Odoo, QA, Firebase, cookie or real upload capability is used.

`tools/build-transfer-tests.py` compiles the production sync store/SQLite queue,
transfer coordinator and services. Only `BChatNativeMediaUploader` is replaced by
the explicitly named HTTP test double in this directory. Android35 UIDT scheduling,
JobService, notification publication and synthetic Activity replacement are real.
`TransferFallbackProbe.java.in` extracts the exact FGS service body and supplies
declared platform/coordinator fakes for API26–33 branch/promotion-denial checks;
this is not evidence of execution on those Android releases.

Build with the existing JDK/SDK/Python:

```powershell
python android/bchat/tools/build-transfer-tests.py
python android/bchat/tools/build-transfer-tests.py --draft-only --before-draft-fix
python android/bchat/tools/build-transfer-tests.py --draft-only
python android/bchat/tools/build-transfer-tests.py --guards-only --before-guards-fix
python android/bchat/tools/build-transfer-tests.py --guards-only
```

These commands only produce unsigned isolated test artifacts. Signing/installing
requires the established test signing workflow and an explicit emulator target.
After installation, the focused instrumentation names are:

- `com.baseer.freshchat.TransferInstrumentation`: UIDT + cancellation/ownership;
- `com.baseer.freshchat.DraftRevisionInstrumentation`: SQLite/store with a gated
  synthetic SAF ContentProvider, edit→restore-identical and exact consumption;
- `com.baseer.freshchat.TransferAdmissionInstrumentation`, with `-e case scope`,
  `-e case ack`, or `-e case quota`: scope binding, durable ACK and all-ticket cap.

Negative-control options only weaken temporary source copies in the test builder;
they never modify product source. Each demonstrates a failing regression first.
The matching fixed run uses the unchanged production implementation.

Evidence is in `artifacts/test-results/C09-*.log`. SQLite migration/FIFO and
10-text/2-image interleaving additionally use `tools/build-connected-state-tests.py`.
Counts describe the exact logged build; changed source requires the affected run.
`C09-UIDT-focus-denial.log` preserves the exact earlier failing tool output: another
authorized panel test replaced the visible Activity on the shared emulator. The
coordinator refused admission; no FGS bypass occurred. The owner confirmed that
concurrent UI use and reserved the emulator before the subsequent PASS70 run.

`TransferProcessDeathInstrumentation` / `--death-only` were executed in the three
explicitly authorized cases: force-stop after private files but before a ticket,
after claim but before HTTP, and after receipt but before cleanup. Six instrumentation
invocations produced three successful recoveries with 29 assertions in total.
Only `com.baseer.freshchat.transfer.test` was terminated. Preparation logs intentionally
contain `Process crashed`; recovery logs contain the acceptance results. This proves
the tested SQLite/files process-restart boundaries, not power loss or OEM Task Manager.

`--stage-only [--before-stage-fix]` covers the metadata-publication/admission race,
cross-instance process fence, stale owner release, receipt drain before a full-quota
orphan import, and a useful dispatch-blocked snapshot after one failed import. It
uses the real storage lane/SQLite/store and a synthetic SAF provider.

Full BChat screens, OEM background restrictions, API26 hardware, real TLS/Tailscale
and the owner's phone have not been accepted by these tests.
