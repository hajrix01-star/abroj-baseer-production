#!/usr/bin/env bash
# Compile recovered ordinary tests; package only when explicitly requested with the preview signing helper.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Existing Android SDK is required}"
: "${APP_CLASSES:?Current verified app classes are required}"
MODE="${1:---compile-only}"; [[ "$MODE" == --compile-only || "$MODE" == --package ]] || exit 2
JAR="$ANDROID_HOME/platforms/android-35/android.jar";BT="$ANDROID_HOME/build-tools/35.0.0"
BUILD="$PWD/artifacts/preview-tests/media-recovery-device";mkdir -p "$BUILD/classes" "$BUILD/dex"
find tests/android-media-recovery -name '*.java' > "$BUILD/sources.txt"
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR:$APP_CLASSES" -d "$BUILD/classes" @"$BUILD/sources.txt"
[[ "$MODE" == --package ]] || { echo 'Recovered ordinary media test sources compiled only; NOT executed.';exit 0; }
"$BT/aapt2" link -o "$BUILD/base.apk" -I "$JAR" --manifest tests/android-media-recovery/AndroidManifest.xml
find "$BUILD/classes" -name '*.class' > "$BUILD/classes.txt"
"$BT/d8" --min-api 26 --lib "$JAR" --classpath "$APP_CLASSES" --output "$BUILD/dex" @"$BUILD/classes.txt"
(cd "$BUILD/dex" && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 "$BUILD/base.apk" "$BUILD/aligned.apk"
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp "$BUILD/aligned.apk" artifacts/BChat-Preview-Media-Recovery-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BChat-Preview-Media-Recovery-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned preview test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh "$BUILD/aligned.apk" artifacts/BChat-Preview-Media-Recovery-Tests.apk
"$BT/apksigner" verify artifacts/BChat-Preview-Media-Recovery-Tests.apk
sha256sum artifacts/BChat-Preview-Media-Recovery-Tests.apk
echo 'Test APK packaged only; NOT installed or executed.'
