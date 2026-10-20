> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Native entry and attached-layout acceptance

This device-only suite runs the **installed frozen application**, with synthetic fixtures and a separately named ChatStore. It does not rebuild or replace the application, use owner data, import credentials, contact a backend, or run an emulator. Compilation alone is not an acceptance pass.

Use an authorized **disposable emulator/test installation**. `-e disposable true` is mandatory. The suite refuses a normal store with attachment references or an attachment directory containing existing files. Run after other synthetic suites have completed their cleanup, or use a fresh disposable guest. A fresh synthetic snapshot already containing a draft, quoted reply and generated PNG verifies that an absent demo-entry preference shows entry without resetting stored content.

## Build and execute

Use the existing licensed SDK and same signing key. No replacement signer is generated.

```sh
ANDROID_HOME=/workspace/shared/baseer-chat-fresh/.tools/android-sdk \
APP_CLASSES="$PWD/artifacts/candidates/0.4.4-0a2e/classes" \
  ./tools/build-entry-layout-tests.sh
adb install -r artifacts/BChat-Entry-Layout-Tests.apk
adb shell am instrument -w -e disposable true -e screenshots true \
  com.baseer.freshchat.entrylayouttest/com.baseer.freshchat.test.EntryLayoutInstrumentation
```

The builder defaults to `artifacts/build/classes`, matching the other test builders. Use explicit `APP_CLASSES` as above for a frozen candidate. The application candidate is `artifacts/candidates/0.4.4-0a2e/BChat-0.4.4-Preview.apk`, versionCode 8, SHA-256 `0a2eacb196a6ea7a28d5ae1ef9acf306ee7838af2bc6c21d88601c9afe8c7d09`. Runtime operators should record the exact application and test APK hashes, device API and native output for each run. The suite verifies candidate versionCode 8 or newer, but does not independently attest the APK hash.

Results stream incrementally under `BChatEntryLayout` and instrumentation `stream`. A failed assertion remains a failure even when later geometry configurations succeed. A missing fundamental precondition stops the run with ERROR/BLOCKED.

## Native coverage

- Missing local entry preference with pre-populated synthetic chat/draft/file state
- Arabic and English minimal read-only entry, no EditText credential inputs or second sign-in action, exactly one centered original-B bitmap (verified against its resource pixels), sample eye show/hide and accessibility label; real 360dp screenshots of the entry and its credential controls
- Actual demo-entry view click, default unchecked process-only session, checked pending choice preserved across language recreation, native exit confirmation Cancel/confirm buttons
- Fresh Activity and isolated disk reload staying at entry after exit, followed by explicit re-entry with exact latest typed draft, reply target and original attachment SHA-256 preserved
- Actual language-choice dialog and Apply, Activity recreation, root direction and committed language from entry and Settings
- Signed-out ACTION_SEND through Android Activity dispatch, actual Home navigation, ACTION_MAIN relaunch, deferred Bundle preservation across entry language recreation, and Explore leading to the recipient picker
- Actual attached recipient selection; edited share-preview caption recreation, confirmed exit and re-entry preservation; unrelated draft preservation
- Arabic and English main screens in **actual attached Activity windows** at 360dp and 320dp, with resource fontScale 1.0 and 2.0; no manually measured detached layouts or mocked screenshots
- Exact on-screen wordmark coordinates unchanged between Chats, expanded search, Requests, Tasks and back to Chats, logical-start placement and unmirrored Latin mark
- Native bottom-label glyph bounds, full visibility, selected state and RTL/LTR ordering
- Opposite-script synthetic short/long conversation titles, separate name/avatar/time/unread bounds, true glyph-edge alignment when not ellipsized, and actual `99+` badge fitting
- Current device 12/24-hour preference compared with the rendered native DateFormat value
- Actual adapter company grouping plus scrolling every company header into view to verify its visible header precedes an attached own-company chat

The synthetic constructor-built long-name/unread fixtures temporarily replace only in-memory conversation entries used by the real adapter. They are not persisted and are restored before any final store write or teardown. Production code and assertions are not altered to accommodate outcomes.

## Screenshots and geometry

`-e screenshots true` captures the **real display** via UiAutomation after bounded Choreographer frame waits. PNGs are retained under the app's `getExternalFilesDir("entry-layout-screenshots")`, typically:

```
/sdcard/Android/data/com.baseer.freshchat/files/entry-layout-screenshots/
```

Every `SCREENSHOT` record reports the actual app-context absolute path. Use the authorized guest extraction route, such as `adb pull`, to retain these synthetic screenshots. Screenshot capture failure fails the requested run. `GEOMETRY` records report the measured root, wordmark, footer, name, avatar, time and unread coordinates. Single-line Android TextViews may use a very wide internal Layout; text-fit and avatar-edge assertions subtract the actual TextView `scrollX` to compare visible glyph coordinates. Diagnostics retain raw Layout edges, scroll offsets and expected visible edges. The strict 2px glyph-edge tolerance is unchanged. Checkbox actions assert the resulting checked state after the native click, rather than incorrectly treating CompoundButton's optional OnClickListener-handled return value as its toggled state. At narrower widths, Android's real window is resized; this is on-screen native rendering, rather than a claim that the entire device has that screen width. Original window attributes are restored.

## Boundaries and restoration

The suite does not change the system clock format, system font setting, host audio routes, permissions, or microphone input. It checks the current 12/24-hour preference only. Run separately on a disposable guest configured to the other time format if acceptance requires both. Resource fontScale is temporarily changed only for the Activity, and the actual configured scale and native geometry are checked.

Exit verifies no recorder or delayed notification remains and clears deferred permission targets; it does not claim active recording/playback cancellation coverage. Existing image/audio/retention suites own actual media playback, recorder/send/reopen regression. This suite uses text-only external ACTION_SEND; file URI grant persistence, true OS process death, real authentication, backend delivery and physical speaker/microphone behavior are outside its scope.

The prior local settings, share-preview preference maps and LocalSettings processDemoSession flag are restored exactly. The Activity is fully destroyed before the original process-store pointer is restored. Normal chat-state existence and SHA-256 are checked unchanged. Only invocation-owned synthetic fixtures/state files are removed. Screenshots intentionally remain for review. A stopped process can leave fixtures in a disposable guest.

Main-thread calls have a 30-second Handler/latch deadline, launch/recreation 45 seconds, frame waits 8 seconds, native attached-dialog lookup 10 seconds and Activity teardown 8 seconds. Dialog choice and positive/negative button clicks use the attached real Android ListView and standard button IDs, avoiding transformed accessibility-label casing. The clicked native button text is logged. API 29+ uses public WindowInspector for process window roots; API 26/27 uses read-only process window-root inspection before hidden-API enforcement. No `waitForIdleSync` loops are used. If a UI action times out, queued work is cancelled when possible and no subsequent mutation or cleanup races an in-flight action. The result is BLOCKED, never a pass.

## Targeted external-file and active-media boundary suite

A separate APK/package supplies the complementary file-grant and active-media checks without rebuilding the main layout APK or duplicating send/reopen media suites:

```sh
ENTRY_LAYOUT_VARIANT=boundary ANDROID_HOME=/path/to/licensed-sdk \
APP_CLASSES="$PWD/artifacts/candidates/0.4.4-0a2e/classes" \
  ./tools/build-entry-layout-tests.sh
adb install -r artifacts/BChat-Entry-Boundary-Tests.apk
adb shell am instrument -w -e disposable true -e screenshots true -e recording true \
  com.baseer.freshchat.entryboundarytest/com.baseer.freshchat.test.EntryBoundaryInstrumentation
```

This boundary suite uses its own synthetic snapshot, restores both preference maps, verifies the normal snapshot unchanged and cleans only invocation-owned fixtures. Its separate package includes a source Activity running under the test-package UID, and a **non-exported read-only ContentProvider**. The source creates a small PNG in its own private files, then sends the app an actual ACTION_SEND with EXTRA_STREAM, ClipData and FLAG_GRANT_READ_URI_PERMISSION. The target checks that the URI remains deferred through Home/MAIN and entry language recreation, imports only after Explore, compares the imported bytes to the source SHA-256 and opens the actual image-share preview. Cleanup asks the source Activity to delete only its own UUID-named PNG. This is a real temporary external URI grant, with no public provider, persistent grant or owner file involved.

A generated 30-second PCM WAV is placed in a synthetic draft. The actual native voice control starts it; MediaPlayer must advance and still be playing immediately before the real exit confirmation button is clicked. Exit must release the native player, reset playback to IDLE, abandon audio focus, and preserve the completed draft/file hash.

With `-e recording true`, the suite requires ranchu/goldfish emulator hardware and an **already granted** RECORD_AUDIO permission. It starts the app's actual virtual MediaRecorder, verifies it is still recording immediately before confirmed exit, and checks that exit releases it and removes only the unfinished recording file while preserving the earlier completed draft attachment. It never configures a host microphone or changes app recording-validation thresholds. Without this flag it reports the recording scope as untested. A requested but unavailable recording precondition fails/blocks the requested run.

Actual boundary screenshots are retained in `getExternalFilesDir("entry-boundary-screenshots")`; exact paths are emitted. Normal UI calls/launch/teardown remain bounded. The boundary suite does not claim physical audibility, physical microphone capture, OS process death, persistable-provider grants, or an actively scheduled-notification cancellation test. The main suite verifies the post-exit notification state only.


## Minimal-entry motion and real process restart suite

The old 49c1 candidate's 709c layout/ac3775 boundary APKs, source archive and SHA256SUMS are retained in `artifacts/entry-layout-frozen-709c/`. The intermediate 4c97 and 155d test APKs/source are separately preserved under `artifacts/entry-layout-frozen-4c97/` and `artifacts/entry-layout-frozen-155d/`. These are historical evidence and must not be used as acceptance of the final 0a2e entry.

For frozen 0a2e, compiled test hashes are:

- Layout: `2d3e73aad283016d8be438332dda698bbc8e86f0e641048af5da7478f898c901`
- Boundary: `8b45dcb7fb6df637c9bec51e5fa72e9780cf3f75c7ee68d0610b687cc9edfb4f`
- Lifecycle: `de1db307647338e80426744ba438ed20c125e521f684fa939f4ec93b00e00957`

Build the lifecycle package independently:

```sh
ENTRY_LAYOUT_VARIANT=lifecycle ANDROID_HOME=/path/to/licensed-sdk \
APP_CLASSES="$PWD/artifacts/candidates/0.4.4-0a2e/classes" \
  ./tools/build-entry-layout-tests.sh
adb install -r artifacts/BChat-Entry-Lifecycle-Tests.apk
```

### Real entry motion

Run only on the authorized disposable guest. The runtime operator must save the exact previous `animator_duration_scale` setting, set it to 1 for the enabled run or 0 for the disabled run, and restore its prior value afterward. The test itself does not change system settings. Force-stop only the disposable target app before each invocation so Android initializes the fresh process with the chosen setting.

```sh
adb shell am instrument -w -e disposable true -e screenshots true \
  -e stage motion -e motion enabled \
  com.baseer.freshchat.entrylifecycletest/com.baseer.freshchat.test.EntryLifecycleInstrumentation
# After selecting animator scale 0 and restarting the disposable target:
adb shell am instrument -w -e disposable true -e screenshots true \
  -e stage motion -e motion disabled \
  com.baseer.freshchat.entrylifecycletest/com.baseer.freshchat.test.EntryLifecycleInstrumentation
```

The enabled run must observe a real running native ObjectAnimator with nonzero displayed rotation, 950ms duration, no repeat, rotationY within 14 degrees and roll within 3 degrees. A real framework focus transfer must cancel/reset it; its prior touch-input mode is restored before the next fresh-launch case and at teardown. Unrelated Activity recreation must preserve its one-play state. A real native dialog then removes window focus without pausing the Activity, which must cancel/reset a fresh intro and prevent restart after focus returns. A separate fresh intro receives actual injected touchscreen DOWN/MOVE/UP events through the Activity; touch-down and an attempted scroll-start gesture must stop both rotations without replay. A fresh entry then checks an actual Home/pause interruption, cancellation and no restart on return. The disabled run requires Android's animator setting to be disabled, confirms the mark remains stationary through a bounded observation interval, and checks recreation remains still. Requested but unobserved motion is a failed/blocked check, never assumed to pass. After the motion checks, actual demo navigation must detach the entry root. Where Android permits read-only observer inspection, the suite captures the exact current app focus/layout callback identities, requires one of each, and verifies both are absent from the same still-live shared observer after detachment. It never mutates callback registries, requests hidden-API exemptions, changes security settings or applies GC pressure. If Android refuses that read, the exact inspection gap is reported and direct removal is not claimed; the public native detachment assertion and separate source cleanup contracts remain required. Synthetic screenshots are emitted under `getExternalFilesDir("entry-lifecycle-screenshots")`.

### True process-only versus remembered entry

These four stages intentionally span **different Android process IDs**. Activity recreation is checked separately and is not substituted for process restart. Run stages 0, 1, 2, 3 in order; after each successful stage, force-stop only the disposable target package. Do not clear its app data between stages.

```sh
# Repeat with N=0, then 1, then 2, then 3.
adb shell am force-stop com.baseer.freshchat
adb shell am instrument -w -e disposable true -e stage N \
  com.baseer.freshchat.entrylifecycletest/com.baseer.freshchat.test.EntryLifecycleInstrumentation
```

- Stage 0 backs up the original preference maps, creates a separately named synthetic ChatStore and exact draft, verifies remember-me defaults unchecked, enters the demo, confirms no persistent active flag, and recreates the Activity in the same process without losing the local session.
- Stage 1 requires a new PID and a naturally cleared process flag. It verifies entry is shown, then clicks the real remember checkbox and demo action, confirming the explicit remembered session is persisted.
- Stage 2 requires another new PID, verifies the remembered demo opens, clicks the real exit confirmation, and verifies both active session paths are cleared while the remember choice remains selected.
- Stage 3 requires another new PID and confirms the explicit exit remains signed out. It then restores both original preference maps, restores the original process flag, checks normal ChatStore existence/SHA-256 unchanged and removes only the test snapshot/checkpoint.

Intermediate successful stages intentionally retain a small `synthetic-entry-session-checkpoint.bin`, the separately named synthetic ChatStore and temporary entry preferences. They never swap or overwrite the normal ChatStore. The checkpoint identifies its expected next stage, source PID, exact fixture, prior preferences and normal snapshot hash. A stage refuses an unexpected sequence or an unchanged process ID.

Stop on any stage failure. Do not continue later stage numbers blindly. Recover the persisted synthetic checkpoint using:

```sh
adb shell am instrument -w -e disposable true -e stage restore \
  com.baseer.freshchat.entrylifecycletest/com.baseer.freshchat.test.EntryLifecycleInstrumentation
```

Alternatively, the authorized runtime operator can reset only the disposable test installation. Do not run unrelated suites while a process-stage checkpoint remains unfinished. Interrupted staged tests are not acceptance passes.
