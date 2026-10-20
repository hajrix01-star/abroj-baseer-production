#!/usr/bin/env bash
# Builds device-only regression tests, never installs or runs them.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the installed Android SDK}"
BT="$ANDROID_HOME/build-tools/35.0.0"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
APP_CLASSES="${APP_CLASSES:-$PWD/artifacts/build/classes}"
[[ -f "$APP_CLASSES/com/baseer/bwork/legacy/AudioDiagnostic.class" ]] || { echo 'Build current app classes first.' >&2; exit 1; }
mkdir -p artifacts/preview-tests/audio-device/{classes,dex}
"$BT/aapt2" link -o artifacts/preview-tests/audio-device/base.apk -I "$JAR" --manifest tests/android-audio/AndroidManifest.xml
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR:$APP_CLASSES" \
  -d artifacts/preview-tests/audio-device/classes tests/android-audio/com/baseer/bwork/legacy/test/AudioPlaybackInstrumentation.java
find artifacts/preview-tests/audio-device/classes -name '*.class' > artifacts/preview-tests/audio-device/classes.txt
"$BT/d8" --min-api 26 --lib "$JAR" --classpath "$APP_CLASSES" --output artifacts/preview-tests/audio-device/dex @artifacts/preview-tests/audio-device/classes.txt
(cd artifacts/preview-tests/audio-device/dex && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 artifacts/preview-tests/audio-device/base.apk artifacts/preview-tests/audio-device/aligned.apk
if [[ "${BWORK_LEGACY_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp artifacts/preview-tests/audio-device/aligned.apk artifacts/BWork-Preview-Audio-Regression-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BWork-Preview-Audio-Regression-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned preview test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh artifacts/preview-tests/audio-device/aligned.apk artifacts/BWork-Preview-Audio-Regression-Tests.apk
"$BT/apksigner" verify artifacts/BWork-Preview-Audio-Regression-Tests.apk
printf 'Built audio device regression APK. NOT installed or executed.\n'
