#!/usr/bin/env bash
# Builds the disposable native entry/layout test APK only; never builds/installs the app.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the already installed Android SDK}"
BT="$ANDROID_HOME/build-tools/35.0.0"; JAR="$ANDROID_HOME/platforms/android-35/android.jar"
APP_CLASSES="${APP_CLASSES:-$PWD/artifacts/build/classes}"
[[ -f "$APP_CLASSES/com/baseer/bwork/legacy/ChatStore.class" ]] || { echo 'Existing frozen app classes required through APP_CLASSES.' >&2; exit 1; }
VARIANT="${ENTRY_LAYOUT_VARIANT:-layout}"
case "$VARIANT" in
  layout) BUILD=artifacts/preview-tests/entry-layout-device; MANIFEST=tests/android-entry-layout/AndroidManifest.xml; OUTPUT=artifacts/BWork-Preview-Entry-Layout-Tests.apk ;;
  boundary) BUILD=artifacts/preview-tests/entry-boundary-device; MANIFEST=tests/android-entry-layout/boundary/AndroidManifest.xml; OUTPUT=artifacts/BWork-Preview-Entry-Boundary-Tests.apk ;;
  lifecycle) BUILD=artifacts/preview-tests/entry-lifecycle-device; MANIFEST=tests/android-entry-layout/lifecycle/AndroidManifest.xml; OUTPUT=artifacts/BWork-Preview-Entry-Lifecycle-Tests.apk ;;
  *) echo 'ENTRY_LAYOUT_VARIANT must be layout, boundary or lifecycle' >&2; exit 1 ;;
esac
mkdir -p "$BUILD"/{classes,dex}
find tests/android-entry-layout tests/android-ui-support -name '*.java' | sort > "$BUILD/sources.txt"
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR:$APP_CLASSES" \
  -d "$BUILD/classes" @"$BUILD/sources.txt"
"$BT/aapt2" link -o "$BUILD/base.apk" -I "$JAR" --manifest "$MANIFEST"
find "$BUILD/classes" -name '*.class' | sort > "$BUILD/classes.txt"
"$BT/d8" --min-api 26 --lib "$JAR" --classpath "$APP_CLASSES" --output "$BUILD/dex" @"$BUILD/classes.txt"
(cd "$BUILD/dex" && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 "$BUILD/base.apk" "$BUILD/aligned.apk"
if [[ "${BWORK_LEGACY_UNSIGNED_ONLY:-0}" == 1 ]]; then
  OUTPUT="${OUTPUT%.apk}-UNSIGNED-COMPILE-CHECK.apk"
  cp "$BUILD/aligned.apk" "$OUTPUT"
  sha256sum "$OUTPUT"
  echo 'Unsigned native test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh "$BUILD/aligned.apk" "$OUTPUT"
"$BT/apksigner" verify "$OUTPUT"
sha256sum "$OUTPUT"
printf 'Entry/layout instrumentation built. NOT installed or executed; requires -e disposable true.\n'
