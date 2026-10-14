#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/editor-host
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/editor-host \
 app/src/main/java/com/baseer/freshchat/LegacyPreflight.java app/src/main/java/com/baseer/freshchat/StoreJournal.java app/src/main/java/com/baseer/freshchat/ChatStore.java \
 app/src/main/java/com/baseer/freshchat/IntegrityAttachments.java app/src/main/java/com/baseer/freshchat/EditorState.java app/src/main/java/com/baseer/freshchat/BoundedTextWriter.java \
 tests/EditorStateTest.java tests/BoundedTextWriterTest.java
java -cp artifacts/editor-host com.baseer.freshchat.EditorStateTest
java -cp artifacts/editor-host com.baseer.freshchat.BoundedTextWriterTest
