#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/media-recovery-unit
find tests/jvm-media -name '*.java' | sort > artifacts/media-recovery-unit/sources.txt
printf '%s\n' app/src/main/java/com/baseer/freshchat/AttachmentSupport.java app/src/main/java/com/baseer/freshchat/LegacyPreflight.java app/src/main/java/com/baseer/freshchat/ChatStore.java app/src/main/java/com/baseer/freshchat/ImagePreviewPolicy.java tests/MediaImageRecoveryPolicyTest.java >> artifacts/media-recovery-unit/sources.txt
if [[ -f app/src/main/java/com/baseer/freshchat/StoreJournal.java ]]; then printf "%s\n" app/src/main/java/com/baseer/freshchat/StoreJournal.java >> artifacts/media-recovery-unit/sources.txt; fi
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/media-recovery-unit @artifacts/media-recovery-unit/sources.txt
java -cp artifacts/media-recovery-unit com.baseer.freshchat.MediaFoundationRecoveryTest
java -cp artifacts/media-recovery-unit MediaImageRecoveryPolicyTest
python3 tools/test-media-recovery-contracts.py
