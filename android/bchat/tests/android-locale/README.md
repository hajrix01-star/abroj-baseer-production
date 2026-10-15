> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Locale and persistence device regression

This suite is compiled, not executed in the current environment. It requires an authorized disposable Android test installation of the current same-signer BChat build. It temporarily changes language preferences and creates/removes local fixture drafts, a pending share and private media files. Do not run it on a user's working installation. It restores the earlier language/draft on ordinary completion, but an interrupted process can retain fixtures.

Build after the app so generated resources/classes match:

```sh
export ANDROID_HOME=/path/to/already-installed-android-sdk
./tools/build-apk.sh
./tools/build-locale-tests.sh
```

The build uses the existing signing key and creates `artifacts/BChat-Locale-Regression-Tests.apk`; it neither installs nor runs it. After explicit device/test authorization, install the current app and test APK on that disposable emulator/device, then run:

```sh
adb shell am instrument -w com.baseer.freshchat.locale.test/com.baseer.freshchat.test.LocaleInstrumentation
```

The suite checks:

- Arabic → English → Arabic Activity recreation with persisted language and matching RTL/LTR root
- English choice on a fresh Activity launch, and locale-aware application-context notification status/audio playback
- Latest typed draft, finished attachment, quoted reply and ChatStore disk reload
- Verbatim synthetic sender/message/conversation names and unchanged original file bytes
- An edited pending-share caption with valid PNG, one-page PDF and PCM WAV fixtures, followed by attachment removal and another recreation
- Explicit share recipient and unrelated chat draft preservation
- Picker query/company/type filters and visible search field after recreation
- Settings screen preservation across language changes

It invokes the same private `applyLanguage` path as the dialog's Apply button to exercise recreation deterministically. Manual review must separately check opening the language dialog, tapping each choice, Cancel/Apply accessibility, actual process death, layout with large fonts/keyboards, background recording cancellation, notifications, audio audibility and same-signer upgrade behavior. Passing/compiling this suite is not a visual or physical-audio acceptance result.
