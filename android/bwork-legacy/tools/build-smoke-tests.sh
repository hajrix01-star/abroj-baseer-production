#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME}"
BT="${BUILD_TOOLS:-$ANDROID_HOME/build-tools/35.0.0}"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
D8="$BT/d8"
if [[ ! -e "$D8" && -e "$BT/d8.bat" ]]; then D8="$BT/d8.bat"; fi
mkdir -p artifacts/preview-tests/smoke/{classes,dex}
"$BT/aapt2" link -o artifacts/preview-tests/smoke/base.apk -I "$JAR" --manifest tests/android/AndroidManifest.xml
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR" -d artifacts/preview-tests/smoke/classes tests/android/com/baseer/bwork/legacy/test/SmokeInstrumentation.java
find artifacts/preview-tests/smoke/classes -name '*.class' > artifacts/preview-tests/smoke/classes.txt
"$D8" --min-api 26 --lib "$JAR" --output artifacts/preview-tests/smoke/dex @artifacts/preview-tests/smoke/classes.txt
(cd artifacts/preview-tests/smoke/dex && jar uf ../base.apk classes*.dex)
"$BT/zipalign" -f 4 artifacts/preview-tests/smoke/base.apk artifacts/preview-tests/smoke/aligned.apk
if [[ "${BWORK_LEGACY_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp artifacts/preview-tests/smoke/aligned.apk artifacts/BWork-Preview-Smoke-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BWork-Preview-Smoke-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned preview test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh artifacts/preview-tests/smoke/aligned.apk artifacts/BWork-Preview-Smoke-Tests.apk
"$BT/apksigner" verify artifacts/BWork-Preview-Smoke-Tests.apk
