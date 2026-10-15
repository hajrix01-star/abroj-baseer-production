#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" != 1 ]]; then
  echo 'Standalone signed builds are disabled: use tools/build-unified-preview.ps1 so emulator and phone receive the same Gradle release APK.' >&2
  exit 2
fi
: "${ANDROID_HOME:?Set ANDROID_HOME to an already installed and licensed Android SDK}"
BUILD_TOOLS="${BUILD_TOOLS:-$ANDROID_HOME/build-tools/35.0.0}"
ANDROID_JAR="${BCHAT_ANDROID_JAR:-$ANDROID_HOME/platforms/android-35/android.jar}"
D8="$BUILD_TOOLS/d8"
if [[ ! -e "$D8" && -e "$BUILD_TOOLS/d8.bat" ]]; then D8="$BUILD_TOOLS/d8.bat"; fi
APKSIGNER="$BUILD_TOOLS/apksigner"
if [[ ! -e "$APKSIGNER" && -e "$BUILD_TOOLS/apksigner.bat" ]]; then APKSIGNER="$BUILD_TOOLS/apksigner.bat"; fi
DEBUG_ARGS=()
if [[ "${BCHAT_DEBUGGABLE_LOCAL:-0}" == 1 ]]; then
  [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]] || { echo 'Local debuggable builds must be unsigned compile checks.' >&2; exit 2; }
  DEBUG_ARGS=(--debug-mode)
fi
JAVAC=(java com.sun.tools.javac.Main)
BUILD_DIR="$(realpath -m artifacts/build)"
[[ "$BUILD_DIR" == "$PWD/artifacts/build" ]] || { echo 'Refusing build cleanup outside BChat artifacts.' >&2; exit 1; }
rm -rf -- "$BUILD_DIR"
mkdir -p artifacts/build/{compiled,gen,classes,dex} artifacts/signing
"$BUILD_TOOLS/aapt2" compile --no-crunch --dir app/src/main/res -o artifacts/build/compiled.zip
"$BUILD_TOOLS/aapt2" link -o artifacts/build/resources.apk -I "$ANDROID_JAR" --manifest app/src/main/AndroidManifest.xml --custom-package com.baseer.freshchat --java artifacts/build/gen --min-sdk-version 26 --target-sdk-version 35 --version-code 55 --version-name 0.7.39-qa-task-notifications "${DEBUG_ARGS[@]}" artifacts/build/compiled.zip
find app/src/main/java artifacts/build/gen -name '*.java' > artifacts/build/sources.txt
"${JAVAC[@]}" -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$ANDROID_JAR" -d artifacts/build/classes @artifacts/build/sources.txt
find artifacts/build/classes -name '*.class' > artifacts/build/classes.txt
"$D8" --min-api 26 --lib "$ANDROID_JAR" --output artifacts/build/dex @artifacts/build/classes.txt
cp artifacts/build/resources.apk artifacts/build/unsigned.apk
(cd artifacts/build/dex && jar uf ../unsigned.apk classes*.dex)
"$BUILD_TOOLS/zipalign" -f -p 4 artifacts/build/unsigned.apk artifacts/build/aligned.apk
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]]; then
  unsigned_output=artifacts/BChat-0.7.39-qa-task-notifications-Unsigned-COMPILE-CHECK.apk
  if [[ "${BCHAT_DEBUGGABLE_LOCAL:-0}" == 1 ]]; then unsigned_output=artifacts/BChat-0.7.39-qa-task-notifications-Debug-Unsigned.apk; fi
  cp artifacts/build/aligned.apk "$unsigned_output"
  "$BUILD_TOOLS/aapt2" dump badging "$unsigned_output" > artifacts/unsigned-manifest.txt
  sha256sum "$unsigned_output"
  echo 'UNSIGNED compile check only. Not an installer or runtime-accepted release.'
  exit 0
fi
