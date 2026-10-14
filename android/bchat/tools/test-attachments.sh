#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME}"
JAR="$ANDROID_HOME/platforms/android-35/android.jar"
mkdir -p artifacts/attachment-test-classes
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR" -d artifacts/attachment-test-classes app/src/main/java/com/baseer/freshchat/LegacyPreflight.java app/src/main/java/com/baseer/freshchat/StoreJournal.java app/src/main/java/com/baseer/freshchat/ChatStore.java app/src/main/java/com/baseer/freshchat/AttachmentSupport.java tests/AttachmentPolicyTest.java
java -cp "artifacts/attachment-test-classes:$JAR" com.baseer.freshchat.AttachmentPolicyTest
