#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to an installed Android SDK}"
LINT="${LINT:-$ANDROID_HOME/cmdline-tools/19.0/bin/lint}"
[[ -x "$LINT" ]] || LINT="$ANDROID_HOME/cmdline-tools/latest/bin/lint"
temp="$(mktemp -d)"
trap 'rm -rf "$temp"' EXIT
cp app/src/main/AndroidManifest.xml "$temp/"
cp -a app/src/main/res "$temp/res"
cp -a app/src/main/java "$temp/src"
printf 'target=android-35\n' > "$temp/project.properties"
mkdir -p artifacts/lint-home
export HOME="$PWD/artifacts/lint-home" XDG_CONFIG_HOME="$PWD/artifacts/lint-home/.config" ANDROID_USER_HOME="$PWD/artifacts/lint-home/.android"
export JAVA_OPTS="-Duser.home=$HOME"
"$LINT" --offline --sources "$temp/src" --classpath "$PWD/artifacts/build/classes" --compile-sdk-version 35 --java-language-level 8 --sdk-home "$ANDROID_HOME" --exitcode --text artifacts/lint-full.txt "$temp"
