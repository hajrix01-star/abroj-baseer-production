#!/usr/bin/env bash
# Compiles device tests; optionally packages them. Never builds/installs/runs the application.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the already installed Android SDK}"
MODE="${1:-}"
[[ -z "$MODE" || "$MODE" == --compile-only ]] || { echo 'Usage: build-image-tests.sh [--compile-only]' >&2; exit 2; }
BT="$ANDROID_HOME/build-tools/35.0.0"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
OPTIONAL="$ANDROID_HOME/platforms/android-35/optional"
APP_CLASSES="${APP_CLASSES:-$PWD/artifacts/build/classes}"
[[ -f "$APP_CLASSES/com/baseer/bwork/legacy/ChatStore.class" ]] || { echo 'Current app classes required via APP_CLASSES.' >&2; exit 1; }
[[ -f "$OPTIONAL/android.test.mock.jar" ]] || { echo 'SDK optional android.test.mock library missing.' >&2; exit 1; }
mkdir -p artifacts/preview-tests/image-device/classes
find tests/android-images -name '*.java' | sort > artifacts/preview-tests/image-device/sources.txt
CLASSPATH="$JAR:$OPTIONAL/android.test.mock.jar:$OPTIONAL/android.test.base.jar:$APP_CLASSES"
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$CLASSPATH" \
  -d artifacts/preview-tests/image-device/classes @artifacts/preview-tests/image-device/sources.txt
if [[ "$MODE" == --compile-only ]]; then
  printf 'Image instrumentation sources compiled. NOT installed or executed; no APK built.\n'; exit 0
fi
[[ -f "$APP_CLASSES/com/baseer/bwork/legacy/ImagePreviews.class" ]] || { echo 'Recompile current image-preview app sources before test APK packaging.' >&2; exit 1; }
mkdir -p artifacts/preview-tests/image-device/dex
"$BT/aapt2" link -o artifacts/preview-tests/image-device/base.apk -I "$JAR" --manifest tests/android-images/AndroidManifest.xml
find artifacts/preview-tests/image-device/classes -name '*.class' | sort > artifacts/preview-tests/image-device/classes.txt
"$BT/d8" --min-api 26 --lib "$JAR" --lib "$OPTIONAL/android.test.mock.jar" --lib "$OPTIONAL/android.test.base.jar" \
  --classpath "$APP_CLASSES" --output artifacts/preview-tests/image-device/dex @artifacts/preview-tests/image-device/classes.txt
(cd artifacts/preview-tests/image-device/dex && zip -q ../base.apk classes*.dex)
# Optional independently generated synthetic HEIC fixture; absent means explicit device SKIP.
if [[ -f tests/android-images/assets/synthetic.heic ]]; then
  (cd tests/android-images && zip -q ../../artifacts/preview-tests/image-device/base.apk assets/synthetic.heic)
fi
"$BT/zipalign" -f 4 artifacts/preview-tests/image-device/base.apk artifacts/preview-tests/image-device/aligned.apk
if [[ "${BWORK_LEGACY_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp artifacts/preview-tests/image-device/aligned.apk artifacts/BWork-Preview-Image-Regression-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BWork-Preview-Image-Regression-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned preview test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh artifacts/preview-tests/image-device/aligned.apk artifacts/BWork-Preview-Image-Regression-Tests.apk
"$BT/apksigner" verify artifacts/BWork-Preview-Image-Regression-Tests.apk
printf 'Image regression test APK built. NOT installed or executed.\n'
