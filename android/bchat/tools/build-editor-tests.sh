#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to an official SDK}"
BT="$ANDROID_HOME/build-tools/35.0.0"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
CLASSES="${BCHAT_CLASSES:-artifacts/build/classes}"
[[ -f "$CLASSES/com/baseer/freshchat/MainActivity.class" ]] || { echo 'Fresh app classes are required' >&2; exit 1; }
OUT=artifacts/preview-tests/editor-native
mkdir -p "$OUT"/{classes,dex}
"$BT/aapt2" link -o "$OUT/base.apk" -I "$JAR" --manifest tests/android-editor/AndroidManifest.xml
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -cp "$JAR:$CLASSES" -d "$OUT/classes" tests/android-editor/com/baseer/freshchat/EditorFoundationInstrumentation.java
find "$OUT/classes" -name '*.class' > "$OUT/classes.txt"
"$BT/d8" --min-api 26 --lib "$JAR" --classpath "$CLASSES" --output "$OUT/dex" @"$OUT/classes.txt"
(cd "$OUT/dex" && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp "$OUT/aligned.apk" artifacts/BChat-Preview-Editor-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BChat-Preview-Editor-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned test-source compilation only. No device execution or installer acceptance.'
  exit 0
fi
./tools/sign-preview-apk.sh "$OUT/aligned.apk" artifacts/BChat-Preview-Editor-Tests.apk
sha256sum artifacts/BChat-Preview-Editor-Tests.apk
