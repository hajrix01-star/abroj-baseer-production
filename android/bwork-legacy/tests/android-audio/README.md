> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Private audio regression (0.4.1)

Current status: the isolated 25-check engine suite has executed successfully in disposable Android emulators, and the additional actual-Activity retention suite reproduces the old file-loss defect and verifies the candidate correction. Exact app hashes, APIs and limits are in `../../VALIDATION.md`. Speaker audibility, physical microphone/routing and phone upgrade are not inferred. The sections below preserve the original 0.4.1 scope; they are not a claim that the prior phone failure was caused by MediaPlayer’s pathname overload.

## What changed and what is known

The owner's 0.4.0 screenshot shows a decoded real waveform plus the old generic playback-failure toast. That proves the generic failure path was reached; it does not identify the native exception or prove a codec is unsupported.

One verified lifecycle defect and separate source-loading hardening are addressed:

1. MediaPlayer previously received an app-private pathname. The documented String API warns that another process may open the path; however, current AOSP already opens ordinary local paths with FileInputStream and forwards a descriptor internally. Explicit app-opened read-only FD loading and exact length are therefore portability/integrity hardening, **not a demonstrated cause or a confirmed fix for the owner's toast**. No file permissions are loosened. Waveform extraction also uses a descriptor.
2. A keyboard/height change reconstructs draft controls. Immediate view-detach stop interrupted preparation/playback. Replacement controls for the exact same attachment now rebind synchronously to the existing native player. An unreplaced removal stops on the next main-loop turn; navigation, deletion, sending and Activity.onPause still stop explicitly.

Errors now include the last operation stage, a fixed failure category and native `what`/`extra`. Only 12 events are held in RAM. No exception messages, stack traces, file names, paths, content, remote reporting or new permissions. A 15-second prepare deadline prevents an endless spinner. The persistent error label opens diagnostic details and an existing explicit export route; only a native unsupported code is described as unsupported. User volume remains user-controlled; no forced speaker routing or unmuting.

AOSP implementation: https://android.googlesource.com/platform/frameworks/base/+/master/media/java/android/media/MediaPlayer.java (local path branch of setDataSource).

Official reference: https://developer.android.com/reference/android/media/MediaPlayer#setDataSource(java.lang.String) and the FileDescriptor overload on that same page. Audio focus: https://developer.android.com/media/optimize/audio-focus .

## Local checks

From `android/bchat`:

```
./tools/test-audio.sh
# Build current application first with the existing signing identity.
ANDROID_HOME=/path/to/existing/sdk ./tools/build-audio-tests.sh
```

The test build requires current app classes containing AudioDiagnostic. `APP_CLASSES=/path/to/current/classes` can override the build/classes location. It produces `artifacts/BChat-Audio-Regression-Tests.apk`; it does not install or run it and does not replace a frozen application APK.

## Device execution (authorized disposable test install)

Use a dedicated emulator or test device and the matching signed current app build. Do not run on the owner's working installation without approval: this instrumentation launches the real Activity and temporarily replaces its visible layout. It does not mutate the real ChatStore. Its generated audio files and isolated temporary store snapshot are deleted at the end. It generates a quiet 440 Hz tone; media volume and routing are not changed.

```
adb install -r artifacts/BChat-0.4.1-Preview.apk
adb install -r artifacts/BChat-Audio-Regression-Tests.apk
adb shell am instrument -w com.baseer.freshchat.audiotest/com.baseer.freshchat.test.AudioPlaybackInstrumentation
```

The tests generate PCM/WAV and AAC-LC/M4A locally, exercising the actual MediaPlayer and VoicePlayerView for private descriptor preparation, position advancement, pause/resume, native seek, supported speed or safe fallback, clip switching, stale callback fencing, compact-view reconstruction, completion/replay, async cancel, unreplaced detach, Activity.onPause, corrupt bytes and recovery. An injected app-owned focus-loss callback verifies pause/no-autoresume; this is **not** a physical competing-app/call interruption test. A separately named temporary ChatStore under the app-private root verifies save/reload/send retains the AAC source. No recording permission or original user audio is used.

## Required physical acceptance

1. Install 0.4.1 over 0.4.0 using the same signer; never uninstall to fix a mismatch. Confirm existing drafts/messages/attachments remain.
2. Record at least 2 seconds, stop to preview, play/pause/seek, open/close keyboard while playing, then send locally and replay the sent message. Close/reopen the app and replay again.
3. Try an existing 0.4.0 voice recording and an imported audio file. Switch recordings repeatedly; only one may play. Verify speaker/Bluetooth route and media volume normally. Test interruption by another app/call and verify no unexpected restart.
4. Test cancel/lock and the 2-minute recorder limit separately; recorder capture logic was not changed by the playback fix.
5. If a failure remains, open the inline error details and report only the `BP-...`, `what` and `extra` codes plus Android/device version. Do not upload private audio or paths. A source error calls for selecting the file again; it must not recommend deleting the app. An unsupported-code error offers saving the unchanged original for another player.
