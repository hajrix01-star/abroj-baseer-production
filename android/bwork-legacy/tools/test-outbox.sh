#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/outbox-classes
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/outbox-classes \
  app/src/main/java/com/baseer/bwork/legacy/sync/{OutboxPolicy,AccountScope}.java tests/OutboxPolicyTest.java
java -cp artifacts/outbox-classes OutboxPolicyTest
