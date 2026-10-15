#!/usr/bin/env bash
# Builds synthetic disposable-install instrumentation only. Never builds or installs the app.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the already installed Android SDK}"
BT="$ANDROID_HOME/build-tools/35.0.0"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
APP_CLASSES="${APP_CLASSES:-$PWD/artifacts/build/classes}"
[[ -f "$APP_CLASSES/com/baseer/freshchat/ChatStore.class" ]] || { echo 'Existing frozen application classes required through APP_CLASSES.' >&2; exit 1; }
mkdir -p artifacts/preview-tests/bubble-device/{classes,dex}
find tests/android-bubbles tests/android-ui-support -name '*.java' | sort > artifacts/preview-tests/bubble-device/sources.txt
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR:$APP_CLASSES" \
  -d artifacts/preview-tests/bubble-device/classes @artifacts/preview-tests/bubble-device/sources.txt
"$BT/aapt2" link -o artifacts/preview-tests/bubble-device/base.apk -I "$JAR" --manifest tests/android-bubbles/AndroidManifest.xml
find artifacts/preview-tests/bubble-device/classes -name '*.class' | sort > artifacts/preview-tests/bubble-device/classes.txt
"$BT/d8" --min-api 26 --lib "$JAR" --classpath "$APP_CLASSES" --output artifacts/preview-tests/bubble-device/dex @artifacts/preview-tests/bubble-device/classes.txt
(cd artifacts/preview-tests/bubble-device/dex && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 artifacts/preview-tests/bubble-device/base.apk artifacts/preview-tests/bubble-device/aligned.apk
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp artifacts/preview-tests/bubble-device/aligned.apk artifacts/BChat-Preview-Bubble-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BChat-Preview-Bubble-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned native test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh artifacts/preview-tests/bubble-device/aligned.apk artifacts/BChat-Preview-Bubble-Regression-Tests.apk
"$BT/apksigner" verify artifacts/BChat-Preview-Bubble-Regression-Tests.apk
sha256sum artifacts/BChat-Preview-Bubble-Regression-Tests.apk
printf 'Bubble instrumentation built. NOT installed or executed; requires -e disposable true.\n'
