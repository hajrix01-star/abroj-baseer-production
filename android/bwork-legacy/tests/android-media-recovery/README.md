> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Reconstructed ordinary media regression

This suite was rewritten after executor replacement. Earlier 0.5.0 app/test/log bytes were lost. Their historical outcomes do not validate this reconstruction. Current native status: not compiled or executed until the compiler SDK is recovered; no signing key replacement is permitted.

Valid synthetic PNG/JPEG/PDF/WAV only. No malformed payloads, deserialization probes, security probes, real photos, camera, microphone, external providers, networking or production data are used. It creates UUID fixture files and replaces the Activity's visible layout without replacing or mutating chat history. Run only with an explicitly authorized disposable test installation.

Coverage prepared:
- 1200x20000 streaming-generated PNG: bounded original-resolution region and unchanged source bytes.
- All 8 JPEG EXIF transforms with expected corner colors.
- Valid 2-page PDF: asynchronous load, hidden/shown/detach ownership.
- Two-pointer View events, pixel zoom, pan and fit.
- Controlled latch holding one image worker plus 32 valid region jobs. Repeated busy retries and same-viewport updates must share one 15-second deadline, which cannot silently restart after timeout.
- Fit/dismiss cancellation: removal of actual scheduled callbacks, deterministic stale callback delivery, and actual newly decoded detail after resources are released.
- Valid quiet synthetic WAV: native playback, injected becoming-noisy pause, receiver teardown and no auto-resume. No physical routing/audibility claim.

Compiler-only command:
ANDROID_HOME=/path/to/existing/sdk APP_CLASSES=/path/to/current/classes ./tools/build-media-recovery-tests.sh --compile-only

Packaging additionally requires SIGNING_KEY pointing to the recovered existing test identity and --package. The script never generates keys or installs/runs anything.

Authorized coordinator runtime command after installing the exact matching-signed candidate and test APK:
adb shell am instrument -w -e disposable true com.baseer.freshchat.mediarecoverytest/com.baseer.freshchat.test.MediaRecoveryInstrumentation

Expect around one minute. Record exact app/test hashes and fresh logs. A build or source check alone is not a native pass. Physical Samsung, real input providers, genuine HEIC, and wired/USB/Bluetooth events remain separate acceptance. The in-process native codec cannot be forcibly interrupted safely; the UI deadline fences late results and shared worker bounds resource use.
