#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ANDROID_HOME:?Set ANDROID_HOME to the already installed Android SDK}"
BT="$ANDROID_HOME/build-tools/35.0.0"
JAR="$ANDROID_HOME/platforms/android-35/android.jar"
mkdir -p artifacts/preview-tests/outbox-tests/{classes,dex}
"$BT/aapt2" link -o artifacts/preview-tests/outbox-tests/base.apk -I "$JAR" --manifest tests/outbox-android/AndroidManifest.xml
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR" \
  -d artifacts/preview-tests/outbox-tests/classes app/src/main/java/com/baseer/freshchat/sync/*.java \
  tests/outbox-android/com/baseer/freshchat/sync/test/OutboxInstrumentation.java
find artifacts/preview-tests/outbox-tests/classes -name '*.class' > artifacts/preview-tests/outbox-tests/classes.txt
"$BT/d8" --min-api 26 --lib "$JAR" --output artifacts/preview-tests/outbox-tests/dex @artifacts/preview-tests/outbox-tests/classes.txt
(cd artifacts/preview-tests/outbox-tests/dex && zip -q ../base.apk classes*.dex)
"$BT/zipalign" -f 4 artifacts/preview-tests/outbox-tests/base.apk artifacts/preview-tests/outbox-tests/aligned.apk
if [[ "${BCHAT_UNSIGNED_ONLY:-0}" == 1 ]]; then
  cp artifacts/preview-tests/outbox-tests/aligned.apk artifacts/BChat-Preview-Outbox-Tests-UNSIGNED-COMPILE-CHECK.apk
  sha256sum artifacts/BChat-Preview-Outbox-Tests-UNSIGNED-COMPILE-CHECK.apk
  echo 'Unsigned preview test compilation only; not installed or run.'
  exit 0
fi
./tools/sign-preview-apk.sh artifacts/preview-tests/outbox-tests/aligned.apk artifacts/BChat-Preview-Outbox-Tests.apk
"$BT/apksigner" verify artifacts/BChat-Preview-Outbox-Tests.apk
