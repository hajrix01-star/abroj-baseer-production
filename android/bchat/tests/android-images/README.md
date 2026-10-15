> Current independent-preview builds target `com.baseer.bchat.preview` and use the new preview signer. Use [PREVIEW-BUILDS.md](../PREVIEW-BUILDS.md) for current build/output paths and ordinary-only runtime scope. Older commands, app versions, signer assumptions, hashes, and runtime results below are historical evidence, not acceptance of this preview.

# Synthetic image-preview regression

Status: the separate image instrumentation suite **passed on a disposable API 29 emulator with 169 passing assertions**, using the final code-7 candidate `BChat-0.4.3-55cb7490eb11.apk` (SHA-256 `55cb7490eb11c6af5f6aaf6fe082ea5ef3820417a938c1f562753153e1d7e5e0`) and repaired test APK SHA-256 `48b659379f6ed95794a82b5850fed413b91436043c8da5f4543908c54026cabb`. The valid-HEIC fixture is explicitly skipped; no HEIC codec pass is claimed. No application APK was changed or rebuilt by this harness repair. Physical camera/gallery/share, physical-device, and upgrade acceptance remain separate.

The live API 29 diagnostic screenshot shows the actual Arabic message-actions dialog while the first accessibility lookup reports no active root. A real touch at the measured, focused Reply row succeeds; Reply, Cancel, confirmed Delete, and tombstone-menu Undo then pass all dialog-dismissal, persistence, and original-byte assertions. This is evidence of accessibility-root availability/timing in the harness rather than an absent/broken message menu on that tested API.

Earlier results remain distinct: the original API 27 run passed 150 assertions and then failed while the old harness targeted Reply; the repaired API 27 run is still pending. A repaired API 35 run passed 104 assertions (including modern ImageDecoder and all EXIF transforms), then timed out on malformed-image visible state before message actions. Its external-files diagnostic directory was unavailable. API 35 is not a full suite pass, and that UI timeout has no screenshot-grounded app diagnosis.

## Local checks

From `android/bchat`:

```sh
./tools/test-images.sh
ANDROID_HOME=/path/to/existing/android-sdk \
  APP_CLASSES=/path/to/current/app/classes \
  ./tools/build-image-tests.sh --compile-only
```

The pure Java suite currently checks 30,736 assertions: invalid/overflowing dimensions, the 100,000-pixel source-edge and 200-million-pixel source-area limits, 1–1,400 target-edge clamping, nonzero aspect-preserving fits, ceil-aware power-of-two downsampling, and image-card width/height bounds across viewport sizes and densities. It includes 5,000 deterministic generated dimension pairs. These checks do not execute Android.

The 42 source-contract checks are regression tripwires for explicit outer image-card sizing, background decoding, source confinement/size checks, modern and legacy decode routes, EXIF transforms, work/cache bounds, stale-result guards, visibility/detach cleanup, loading/failure text, FIT_CENTER, draft/inspection paths, original-byte import/export/camera paths, and loading-string locale parity. They are not behavioral proof.

`build-image-tests.sh --compile-only` creates classes in `artifacts/image-device/classes`. It does not compile, package, install, or launch the application. The default mode additionally packages a separate `artifacts/BChat-Image-Regression-Tests.apk` using an existing matching local test signing key and current app classes; it never generates a replacement key. It does not install or execute either APK.

## Instrumentation safety and execution

Use only an explicitly authorized disposable emulator or test installation. **Never run this on the owner's working installation.** The suite launches the real Activity, replaces its visible layout, injects a separately named synthetic ChatStore, and exercises real draft/message actions. Activity attachment cleanup can delete files not referenced by that isolated store. The required `-e disposable true` flag prevents accidental launches without an explicit opt-in. It does not make a working installation safe.

The test provider is in-process only (`MockContentResolver` plus `ImageFixtureProvider`); it is not declared/exported in the manifest and has no network access. The suite uses generated four-color fixtures and separately named local state files. No private photo, gallery, microphone, or existing message bytes are needed. Generated files are deleted in teardown. Test store injection stays in place through Activity shutdown so test composer state is not restored into the original ChatStore field.

On a disposable emulator/device, install a current app and instrumentation APK signed with the same existing key, then:

```sh
adb shell am instrument -w -e disposable true \
  com.baseer.freshchat.imagetest/com.baseer.freshchat.test.ImagePreviewInstrumentation
```

Run at minimum on API 26/27 and API 28+; ideally include the user's actual Android/API and vendor family. The 19.2MP fixture is generated at native dimensions before compression, so use a test device/emulator with enough heap for a roughly 77 MB temporary fixture bitmap. The preview itself must remain under the much smaller asserted display-allocation limits.

## Native coverage and action-test safeguards

- Generated landscape JPEG and portrait PNG run through the actual platform path and forced legacy BitmapFactory path. Nonzero dimensions, orientation, software allocation, downsampling bounds, and unchanged source hashes are asserted.
- A generated 6,000 × 3,200 JPEG tests large-image bounded decoding.
- All eight EXIF orientation values use four distinct corner colors. Both the platform-selected and forced legacy paths must produce the correct dimensions and corner placement, including mirrored/transposed orientations.
- Main-thread full decode must reject explicitly. Empty/malformed data, malformed HEIC, wrong MIME, exact-size mismatch, and a file outside the private attachment directory must fail safely. A visible malformed image must retain a nonzero card and unavailable label.
- A deterministic worker barrier verifies request deduplication and cancellation. Forty distinct requests against a blocked worker exercise the 32-work bound and retryable busy results. The RAM cache cap is asserted at 16 MiB.
- Unattached views request no decode. A same-turn landscape-to-portrait rebind must not display stale landscape pixels. INVISIBLE/VISIBLE, detach, queued removal, and reload paths assert pixel/request ownership.
- Real `messageBubble`/`attachmentCard` construction tests image-only and captioned messages restored from isolated local storage, explicit OUTER width/height, on-screen dimensions, actual bitmap arrival, and FIT_CENTER. The larger card is exercised separately.
- Long-press on an image opens the actual message menu. Action selection waits for an exact-text, enabled, visible row/button in the focused dialog, then uses Android accessibility action click. If accessibility cannot perform that click, the harness saves the live screenshot and both process-window/accessibility trees before sending real touch input at the freshly measured row/button bounds. Each selection must dismiss its own dialog. No production action handler or store mutation is called to simulate Reply/Delete/Cancel/Undo. Reply must persist the original target after reload. Local deletion requires confirmation; cancelling preserves the message after reload. Confirming creates a persisted tombstone without attachments. Long-pressing that tombstone and selecting the actual Undo item restores the original attachment path and exact SHA-256 after reload.
- A synthetic in-process provider exercises exact SHA-256 fidelity through `AttachmentSupport.importUri` and `saveToUri`. Draft reload, local send, and pending-share stage/reload/send retain the original path and size.
- A synthetic capture file is delivered to the actual `MainActivity.onActivityResult(CAMERA, RESULT_OK, null)` path. Its JPEG/EXIF bytes must remain unchanged through draft, send, and reload. This does not launch an external camera app or prove its URI grant behavior.

Main-thread dispatch is bounded at 30 seconds and launch at 45 seconds. The suite does not use unbounded `waitForIdleSync`; asynchronous checks poll their own semantic condition. If a UI dispatch times out, queued work is cancelled where possible and no further app mutation or fixture deletion runs against a possibly in-flight action.

On action-targeting failure, diagnostics are captured before Activity teardown under the app's external-files `image-test-diagnostics` directory. These are synthetic test screens only and intentionally remain available for `adb pull`. A screenshot captured after instrumentation exits may show the launcher and is not evidence about the failed dialog.

## HEIC honesty

No valid HEIC fixture is bundled. This environment has read-only HEIC support in ImageMagick and no HEIC encoder; renaming PNG/JPEG bytes would not test HEIC. The suite emits an explicit **SKIP** for valid-HEIC acceptance when `assets/synthetic.heic` is absent, while malformed-HEIC safe failure is separate.

An independently generated, small, genuinely synthetic HEIC can be placed at `tests/android-images/assets/synthetic.heic` before packaging the test APK. Keep its creation recipe/provenance with the fixture and use no personal image. The test first probes the device's native decoder independently. If that codec works, the bounded application path must also work; if unavailable, the suite checks safe failure and emits a codec-specific SKIP rather than claiming HEIC support. Original bytes must survive either outcome. Codec support remains device-dependent.

## Required physical acceptance

1. Install the matching-signed current review build over the previous build without uninstalling. Verify existing draft, sent, and imported images survive.
2. In Arabic and English, send a gallery photo with no caption, then one with a caption. Test portrait and landscape. Both should have a substantive-width visible card immediately, then actual image pixels rather than a narrow blank strip.
3. Open a larger preview; the full image should fit without stretching/cropping. Open/close the keyboard, scroll the message off/on screen, navigate back/reopen, rotate, and restart the app. Draft thumbnails should remain visible and sent-image geometry should remain stable.
4. Test a new camera capture, an ACTION_SEND image, multiple shared images, and a large photo. Verify no automatic send, correct destination review, and byte-identical original export through a chosen SAF provider.
5. Test a genuine EXIF-rotated JPEG and a real HEIC only with explicit permission and without uploading private bytes. HEIC may be unsupported by that Android device; failure should leave a useful visible unavailable state and a saveable original.
6. Long-press the image to reply; cancel local deletion, then confirm and undo it on a synthetic message. Verify the surrounding bubble actions remain usable.
7. Exercise malformed/unsupported images and long scrolling histories. The UI must remain responsive, cards must stay sized, originals must remain saveable, and old decoded pixels must not flash into another message.

The physical acceptance steps above remain open. Emulator automation validates only the branches and fixtures reported by its actual run; it does not establish physical microphone/speaker, external camera/gallery/SAF behavior, valid-HEIC codec support, or upgrade preservation.
