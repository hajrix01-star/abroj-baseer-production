#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/image-unit
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/image-unit \
  app/src/main/java/com/baseer/freshchat/ImagePreviewPolicy.java tests/ImagePreviewPolicyTest.java
java -cp artifacts/image-unit ImagePreviewPolicyTest
python3 tools/test-image-contracts.py
