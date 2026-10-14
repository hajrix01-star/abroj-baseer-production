# Public-API non-UI media kernel

This is an unsigned DEX test entry point, not an APK or installed application. It uses only public Android APIs: ContextWrapper(null) with getApplicationContext/getFilesDir overrides, a test-owned files root, public main Looper preparation, a worker Thread, BitmapFactory/ImageDecoder/BitmapRegionDecoder through the actual ImagePreviews implementation, and ordinary Bitmap/Canvas/ExifInterface APIs.

No ActivityThread/system-context lookup, hidden API/reflection workaround, custom JNI registration, APK installation, signing key, malformed file, resource-exhaustion probe, UI or external provider is involved.

## Recorded terminal outcome

One authorized API29 raw-dalvik attempt was performed on 2026-10-08. On-device DEX SHA-256 was verified as `eb1cfb036f729c54ae17755a6bd0bb02a7abe26f815425a56866c97de591c51e`.

The process stopped at public `Looper.prepareMainLooper`: `android.os.MessageQueue.nativeInit()` has no registered implementation in this raw-dalvik runtime and threw `java.lang.UnsatisfiedLinkError`. Exit code was 1 and checks executed was 0. No decoder worker/image assertion executed. This is an unsupported execution-route gate, not evidence of a defect in the app decoder.

No retry, hidden-API access, alternative initialization or native-registration workaround was attempted. This runtime path is closed. The invocation below is retained only as a reproducibility record, not a request to run it again. Reconstructed APK UI/native-media acceptance remains blocked by the missing original signing key.

The successful unsigned DEX compilation remains separate from this runtime result. Raw evidence: `artifacts/media-kernel-raw-dalvik-unsupported.log`.

## Prepared cases (not reached)

- Generate a complete valid 1200×20000 PNG using row-wise compression, without allocating the full source bitmap.
- Invoke actual ImagePreviews.decodeDetail for metadata, exact 1000×700 original-region pixels, and normal full-image fitting.
- Invoke actual ImagePreviews.decode for the bounded overview.
- Generate ordinary four-corner JPEGs and test EXIF1–8 through both actual detail transformation matrices and the actual platform overview decoder.
- Verify exact PNG pixels, expected JPEG corner colors, dimensions, allocation caps and unchanged original bytes.
- Main calls public Looper.prepareMainLooper when needed, then joins a worker performing decoding. No UI message loop/callback path is exercised.

## Build

ANDROID_HOME=/workspace/shared/baseer-chat-fresh/.tools/android-sdk \
APP_CLASSES=/workspace/shared/abroj-baseer-bchat/android/bchat/artifacts/build/classes \
./tools/build-media-kernel.sh

Output: artifacts/media-kernel-unsigned/dex/classes.dex. COMPILE-MANIFEST.json records test/production source hashes, every class input, Android jar and final DEX hash. Compilation does not establish native execution success.

## Recorded coordinator invocation (do not retry)

The designated owner of the ONE API29 emulator used the isolated directory and invocation below:

mkdir -p /data/local/tmp/bchat-public-media-kernel/fixtures

dalvikvm -cp /data/local/tmp/bchat-public-media-kernel/kernel.dex com.baseer.freshchat.MediaKernelMain /data/local/tmp/bchat-public-media-kernel/fixtures

The test creates a fresh UUID temporary subdirectory beneath this fixture parent and removes only its own files after its worker stops. It has a 90-second worker deadline. If native work remains active, fixture removal is skipped and process exit terminates the test.

If raw dalvik does not initialize the graphics/Looper/native runtime needed by these public APIs, preserve the exact reported stage/exception and stop this path. Do not attempt ActivityThread/systemContext, native-registration tricks, hidden APIs, alternative runtime bootstrapping or installation/signing workarounds.

A native pass covers only these public decoder kernels. It is not evidence for zoom gestures, visibility cancellation, PDF, providers, playback, physical Samsung, or a signed upgrade. A startup/JNI failure establishes only the execution-route limitation, not an image-decoder defect in the app.
