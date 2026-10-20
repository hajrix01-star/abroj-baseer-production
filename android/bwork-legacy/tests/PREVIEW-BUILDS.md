# Independent preview test builds

The current application is `com.baseer.bchat.preview`, version 9 /
`0.5.0-bchat-preview`. Its Java classes and generated `R` remain in
`com.baseer.freshchat`. The previous `com.baseer.freshchat` application and
preserved source/APK evidence are separate. Do not uninstall or replace that app
to install this preview.

The canonical app-targeted instrumentation manifests and launch intents now
target the preview. Test APK package names remain their existing test-only IDs.
The isolated outbox test still targets its own
`com.baseer.freshchat.outbox.test` package and needs no application installation.

## Build without signing or device execution

Run from `android/bchat`, after compiling the current application classes:

```sh
export ANDROID_HOME=/path/to/already-installed-android-sdk
export APP_CLASSES="$PWD/artifacts/build/classes"
export BCHAT_CLASSES="$APP_CLASSES"
BCHAT_UNSIGNED_ONLY=1 ./tools/build-bubble-tests.sh
BCHAT_UNSIGNED_ONLY=1 ./tools/build-entry-layout-tests.sh
```

All ten `tools/build-*-tests.sh` builders accept `BCHAT_UNSIGNED_ONLY=1`.
Unsigned APK names end in `-UNSIGNED-COMPILE-CHECK.apk` and are not installers.
The image builder also supports `--compile-only`, producing classes without an
APK. The media-recovery builder defaults to `--compile-only`; use `--package`
with `BCHAT_UNSIGNED_ONLY=1` to check its complete unsigned package.
`ENTRY_LAYOUT_VARIANT=boundary` or `lifecycle` selects those entry packages.

Generated build directories live under `artifacts/preview-tests/`, keeping
earlier build evidence intact. Signed output filenames use these names:

| Builder | Signed output under `artifacts/` |
| --- | --- |
| `build-smoke-tests.sh` | `BChat-Preview-Smoke-Tests.apk` |
| `build-audio-tests.sh` | `BChat-Preview-Audio-Regression-Tests.apk` |
| `build-bubble-tests.sh` | `BChat-Preview-Bubble-Regression-Tests.apk` |
| `build-editor-tests.sh` | `BChat-Preview-Editor-Tests.apk` |
| `build-image-tests.sh` | `BChat-Preview-Image-Regression-Tests.apk` |
| `build-locale-tests.sh` | `BChat-Preview-Locale-Regression-Tests.apk` |
| `build-media-recovery-tests.sh --package` | `BChat-Preview-Media-Recovery-Tests.apk` |
| `build-outbox-tests.sh` | `BChat-Preview-Outbox-Tests.apk` |
| `build-retention-tests.sh` | `BChat-Preview-Retention-Regression-Tests.apk` |
| `build-entry-layout-tests.sh` | `BChat-Preview-Entry-Layout-Tests.apk` |
| `ENTRY_LAYOUT_VARIANT=boundary build-entry-layout-tests.sh` | `BChat-Preview-Entry-Boundary-Tests.apk` |
| `ENTRY_LAYOUT_VARIANT=lifecycle build-entry-layout-tests.sh` | `BChat-Preview-Entry-Lifecycle-Tests.apk` |

## Sign with the independent preview identity

For an authorized signed build, omit `BCHAT_UNSIGNED_ONLY` and provide
`BCHAT_SIGNING_KEY` and `BCHAT_SIGNING_PASSWORD_FILE` as local paths. The common
`tools/sign-preview-apk.sh INPUT.apk OUTPUT.apk` helper uses the `bchat-preview`
alias and reads the password through apksigner's file option. Builders neither
generate keys nor contain passwords. The app and app-targeted instrumentation
must use the same independent preview signer.

The builders do not install, launch, or run either APK. Compilation and signature
verification do not establish a native test pass.

## Ordinary functional scope

Execution belongs on an explicitly authorized, disposable preview installation.
Keep exact app/test hashes and fresh runtime results. Historical hashes and
older release acceptance described in individual suite READMEs do not validate
the independent preview or authorize running every old suite.

- Bubble geometry and entry/layout exercise ordinary synthetic display,
  language, draft, entry, navigation, exit/cancel, and text-share cases with
  isolated stores and a required `-e disposable true` flag.
- Smoke and locale cover ordinary flows but alter the installed app's local
  draft/history/preferences. They lack the same disposable guard; use only a
  fresh authorized preview test installation.
- Entry boundary includes valid synthetic external PNG sharing and native WAV
  playback through normal exit. Its optional recording path requires separate
  runtime permission and is outside a playback-only review.
- Audio, image, retention, media-recovery, and editor full suites include
  intentionally unavailable/corrupt inputs, injected failures/events, or blocked
  workers. Do not execute these full suites for an ordinary-only review.
- Entry lifecycle includes separate process stages and motion-setting
  preconditions. It is not part of a simple functional sweep. Outbox is an
  isolated database suite, not application UI acceptance.

For ordinary preview review, use a separately scoped harness when an existing
suite mixes ordinary checks with excluded fault cases. Do not substitute
compilation success for physical audio, microphone, external-provider, or
real-device acceptance.
