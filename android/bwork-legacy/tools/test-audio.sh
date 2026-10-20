#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/audio-unit
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/audio-unit \
  app/src/main/java/com/baseer/bwork/legacy/AudioDiagnostic.java \
  app/src/main/java/com/baseer/bwork/legacy/PlaybackState.java \
  tests/AudioDiagnosticTest.java tests/PlaybackStateTest.java
java -cp artifacts/audio-unit AudioDiagnosticTest
java -cp artifacts/audio-unit PlaybackStateTest
