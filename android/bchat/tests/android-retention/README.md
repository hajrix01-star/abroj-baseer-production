> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Synthetic attachment retention: real Activity flows

This device-only suite uses the application already installed on a **fresh disposable emulator/test installation**. It does not build or replace the application, enable a host/user microphone, import owner data, contact a backend, alter media volume/routing, or modify the normal chat-state snapshot.

The explicit `-e disposable true` flag is mandatory. The suite also refuses to proceed when the normal store contains attachment references or the attachment directory already contains files. A separately named synthetic snapshot replaces both the Activity store and its process-level store throughout test execution, including Activity lifecycle callbacks. The normal snapshot's SHA-256 is checked unchanged. Only files created by this invocation are removed during teardown.

## Build

Use an existing licensed Android SDK, existing app classes, and the existing matching signer:

```sh
ANDROID_HOME=/path/to/android-sdk ./tools/build-retention-tests.sh
```

`APP_CLASSES` may specify a preserved application classes directory. The output is `artifacts/BChat-Retention-Regression-Tests.apk`, separate from all existing test and application APKs.

## Execute baseline, then candidate

Install the frozen 0.4.2 application and the test APK on a fresh disposable emulator first. Preserve that baseline output before installing any candidate application.

```sh
adb install artifacts/releases/0.4.2/BChat-0.4.2-Preview.apk
adb install artifacts/BChat-Retention-Regression-Tests.apk
adb shell am instrument -w -e disposable true -e screenshots true \
  com.baseer.freshchat.retentiontest/com.baseer.freshchat.test.AttachmentRetentionInstrumentation
```

The test emits incremental instrumentation stream messages and the logcat tag `BChatRetentionTest`. These contain synthetic fixture identities and app-context absolute/canonical paths, never owner content.

The optional `screenshots=true` flag captures real sent-image and playing-audio UI states, plus candidate missing-image labels. Generated PNGs are retained under `getExternalFilesDir("retention-test-screenshots")` for ordinary authorized `adb pull <reported-path>` extraction from the disposable guest, without enabling debugging or root in the application. If external files storage is unavailable on a fresh guest, the test falls back to `getFilesDir()/retention-test-screenshots` and logs that location. Private fallback extraction must use an already permitted runtime route; the test does not enable debugging, root, or change permissions. Each `SCREENSHOT` result reports the exact filename, including API and installed version code. No screenshot capture occurs without that flag. The directory contains only these disposable synthetic test screens.

## Covered behavior

- Locally generated PNG/JPEG and PCM WAV/AAC-LC M4A fixtures
- App-context absolute versus canonical roots and the old lexical cleanup predicate
- Real `MainActivity.addFilesToDraft`, including its cleanup call
- Real draft photo views and voice play buttons; native image decode and MediaPlayer position advancement
- Actual `inspectAttachment` image dialog with decoded pixels, 1400px target, FIT_CENTER, screenshot, normal positive-button dismissal, chat retention and unchanged source bytes
- Real `sendDraft`, delayed and explicit `persistDraft`, list/chat navigation, Activity closure and a new Activity using the isolated disk snapshot
- Bounded root-layout callback/unchanged-bounds counts after send, plus candidate quiescence and composer max-lines checks at actual 280dp/420dp/restored root heights
- Source existence, length and SHA-256 across those transitions
- Fresh-decoder verification after Activity reopen
- An explicitly removed, test-owned WAV after real PCM waveform caching, verifying `BP-SOURCE-IO` on frozen versionCode 6 and `BP-SOURCE-MISSING` on candidate versionCode 7 or later, despite cached waveform availability
- Optional candidate-only actual virtual MediaRecorder start → bounded 8-second virtual-input recording → finish/save → draft/play → send/play → navigation/reopen. Request with `-e recording true` after granting RECORD_AUDIO in the disposable guest. The test refuses non-emulator hardware and never sets up the host microphone; unavailable permission/input produces an explicit BLOCKED result, not a pass. The longer fixture input accommodates slow software emulation: the app’s existing 750ms minimum encoded duration and all recording validity checks remain unchanged, and invalid files are never accepted.
- Candidate-only missing-image status and accessibility in Arabic/English, plus export source validation and error-code localization; the temporary language preference is restored

Fixture-preservation failures are collected rather than aborting immediately, allowing baseline evidence for both images and audio. Unexpected harness/API failures show their exception-cause chain. MediaPlayer advancement is a native execution check, **not proof of audible speaker/Bluetooth output**. Optional virtual-emulator recorder coverage is distinct from physical microphone capture. Owner-device behavior, physical routing and upgrade acceptance remain separate checks.

Failed playback checks additionally log only safe model/native state, target/control attachment and Activity lifecycle/focus flags, plus BP codes. Native position/isPlaying getters are skipped while unprepared so observing a failure does not itself induce a native state error. The playback deadline and pass assertions are unchanged.

Main-thread handoffs use a 30-second Handler/latch deadline rather than global UI-idle waits. A timed-out queued action is cancelled before execution. An already-running action cannot be forcibly rolled back; the suite reports BLOCKED with its main-thread stack and schedules no further actions or fixture removal. Activity launch/resume is bounded at 45 seconds and teardown at 8 seconds. A blocked disposable guest may therefore retain only its synthetic fixtures until the runtime operator resets it. BLOCKED results are never reported as passes.

Status: sources and test APK compile. Device execution results belong to the separately captured runtime evidence; compilation alone is not a pass.
