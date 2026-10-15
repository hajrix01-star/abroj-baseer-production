#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
# Fresh owned output on every run prevents removed/renamed classes from surviving.
out=$(mktemp -d artifacts/capture-host-XXXXXX)
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d "$out" \
 app/src/main/java/com/baseer/freshchat/LegacyPreflight.java \
 app/src/main/java/com/baseer/freshchat/StoreJournal.java \
 app/src/main/java/com/baseer/freshchat/ChatStore.java \
 app/src/main/java/com/baseer/freshchat/IntegrityAttachments.java \
 app/src/main/java/com/baseer/freshchat/EditorState.java \
 app/src/main/java/com/baseer/freshchat/CaptureAdmission.java \
 tests/CaptureAdmissionTest.java tests/EditorIntegrityTest.java tests/EditorStateTest.java
java -cp "$out" com.baseer.freshchat.CaptureAdmissionTest
java -cp "$out" com.baseer.freshchat.EditorIntegrityTest
java -cp "$out" com.baseer.freshchat.EditorStateTest
printf 'Fresh capture test classes: %s\n' "$out"
