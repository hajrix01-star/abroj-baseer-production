#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts
# Fresh owned output on every run prevents removed/renamed classes from surviving.
out=$(mktemp -d artifacts/capture-host-XXXXXX)
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d "$out" \
 app/src/main/java/com/baseer/bwork/legacy/compat/LegacyIdentity.java app/src/main/java/com/baseer/bwork/legacy/LegacyPreflight.java \
 app/src/main/java/com/baseer/bwork/legacy/StoreJournal.java \
 app/src/main/java/com/baseer/bwork/legacy/ChatStore.java \
 app/src/main/java/com/baseer/bwork/legacy/IntegrityAttachments.java \
 app/src/main/java/com/baseer/bwork/legacy/EditorState.java \
 app/src/main/java/com/baseer/bwork/legacy/CaptureAdmission.java \
 tests/CaptureAdmissionTest.java tests/EditorIntegrityTest.java tests/EditorStateTest.java
java -cp "$out" com.baseer.bwork.legacy.CaptureAdmissionTest
java -cp "$out" com.baseer.bwork.legacy.EditorIntegrityTest
java -cp "$out" com.baseer.bwork.legacy.EditorStateTest
printf 'Fresh capture test classes: %s\n' "$out"
