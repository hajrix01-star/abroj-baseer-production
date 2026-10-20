#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/editor-host
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/editor-host \
 app/src/main/java/com/baseer/bwork/legacy/compat/LegacyIdentity.java app/src/main/java/com/baseer/bwork/legacy/LegacyPreflight.java app/src/main/java/com/baseer/bwork/legacy/StoreJournal.java app/src/main/java/com/baseer/bwork/legacy/ChatStore.java \
 app/src/main/java/com/baseer/bwork/legacy/IntegrityAttachments.java app/src/main/java/com/baseer/bwork/legacy/EditorState.java app/src/main/java/com/baseer/bwork/legacy/BoundedTextWriter.java \
 tests/EditorStateTest.java tests/BoundedTextWriterTest.java
java -cp artifacts/editor-host com.baseer.bwork.legacy.EditorStateTest
java -cp artifacts/editor-host com.baseer.bwork.legacy.BoundedTextWriterTest
