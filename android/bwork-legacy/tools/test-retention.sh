#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME}"
JAR="$ANDROID_HOME/platforms/android-35/android.jar"
OUT="artifacts/retention-test-classes"
mkdir -p "$OUT"
# Execute the current Activity method body on host-owned synthetic files. Do not duplicate its
# current behavior in the test: restoring a destructive sweep must fail the retention assertions.
python3 - "$OUT/AttachmentCleanupHarness.java" <<'PY'
from pathlib import Path
import sys
source = Path('app/src/main/java/com/baseer/bwork/legacy/MainActivity.java').read_text()
start = source.index('    private void cleanupAttachments() {')
end = source.index('\n    private void clearPreview()', start)
method = source[start:end]
Path(sys.argv[1]).write_text('''package com.baseer.bwork.legacy;
import java.io.File;
import java.util.Set;
class AttachmentCleanupHarness {
    boolean importing;
    ChatStore store;
    Object voiceRecorder;
    String cameraPath;
    ChatStore.Attachment exportAttachment;
    File filesDir;
    File getFilesDir() { return filesDir; }
    void runCleanup() { cleanupAttachments(); }
''' + method + '\n}\n')
PY
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options \
  -classpath "$JAR" -d "$OUT" \
  app/src/main/java/com/baseer/bwork/legacy/compat/LegacyIdentity.java app/src/main/java/com/baseer/bwork/legacy/LegacyPreflight.java app/src/main/java/com/baseer/bwork/legacy/StoreJournal.java app/src/main/java/com/baseer/bwork/legacy/ChatStore.java \
  app/src/main/java/com/baseer/bwork/legacy/AttachmentSupport.java \
  "$OUT/AttachmentCleanupHarness.java" tests/AttachmentRetentionTest.java
java -Djava.awt.headless=true -cp "$OUT:$JAR" com.baseer.bwork.legacy.AttachmentRetentionTest
