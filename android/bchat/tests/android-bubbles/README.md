> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Native text-bubble measurement regression

This suite invokes the installed app's real `MainActivity.messageBubble` and Android's native `measure`/`layout`. It requires an explicitly disposable emulator/test installation. It builds only a separate test APK, never the application.

```sh
ANDROID_HOME=/path/to/licensed-sdk ./tools/build-bubble-tests.sh
adb install artifacts/BChat-Bubble-Regression-Tests.apk
adb shell am instrument -w -e disposable true \
  com.baseer.freshchat.bubbletest/com.baseer.freshchat.test.BubbleGeometryInstrumentation
```

Run first against the preserved pre-fix application to verify the incoming group bubble fails for collapsed width. Then run the same test APK against the final application, on both Android 27 and 35 where available. Retain exact application/test APK hashes and outputs.

The 112 cases cover Arabic RTL and English LTR, 320dp/411dp window widths, group/person conversations, incoming/outgoing messages, short and long sender/body text, quotes, deleted labels, and image/audio/PDF cards. Assertions check nonzero readable content, window bounds, sender/body short-text line counts, logical alignment, footer text and reply bounds, and positive explicit attachment dimensions. Synthetic attachment views stay detached: this suite does not claim media decoding or playback coverage.

The suite uses a separately named synthetic ChatStore, detached test layouts, and temporary locale preferences restored on teardown. It does not send a message, delete existing user data, request permissions, or contact a backend. Main-thread actions and Activity launch have bounded deadlines. A main-thread timeout prevents further UI actions and fixture cleanup rather than racing an in-flight action.

`tools/test-bubble-contracts.py` supplies fast source tripwires, not native runtime acceptance. Actual app screenshots and attachment retention/decoding checks remain separate from these deterministic native measurements.
