#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tools/test-localization.py
mkdir -p artifacts/locale-policy-classes
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options \
  -d artifacts/locale-policy-classes app/src/main/java/com/baseer/bwork/legacy/AppLocalePolicy.java tests/AppLocalePolicyTest.java
java -cp artifacts/locale-policy-classes AppLocalePolicyTest
