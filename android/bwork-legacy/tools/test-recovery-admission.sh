#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to an official SDK}"
: "${BWORK_LEGACY_CLASSES:?Set BWORK_LEGACY_CLASSES to freshly compiled application classes}"
JAR="$ANDROID_HOME/platforms/android-35/android.jar"
TEMP=$(mktemp -d)
trap 'rm -rf "$TEMP"' EXIT
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -cp "$JAR:$BWORK_LEGACY_CLASSES" -d "$TEMP" tests/RecoveryAdmissionTest.java
java -cp "$TEMP:$BWORK_LEGACY_CLASSES:$JAR" com.baseer.bwork.legacy.RecoveryAdmissionTest
