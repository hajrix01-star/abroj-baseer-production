#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p artifacts/core-classes
java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/core-classes app/src/main/java/com/baseer/freshchat/LegacyPreflight.java app/src/main/java/com/baseer/freshchat/StoreJournal.java app/src/main/java/com/baseer/freshchat/ChatStore.java app/src/main/java/com/baseer/freshchat/NotificationDemoPolicy.java tests/ChatStoreTest.java tests/NotificationDemoPolicyTest.java app/src/main/java/com/baseer/freshchat/VoiceGestureState.java tests/VoiceGestureStateTest.java
java -cp artifacts/core-classes ChatStoreTest
java -cp artifacts/core-classes NotificationDemoPolicyTest
java -cp artifacts/core-classes VoiceGestureStateTest

java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/core-classes app/src/main/java/com/baseer/freshchat/ReplyWireContract.java tests/ReplyWireContractTest.java
java -cp artifacts/core-classes ReplyWireContractTest

java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/core-classes app/src/main/java/com/baseer/freshchat/RuntimeOrigin.java tests/RuntimeOriginTest.java
java -cp artifacts/core-classes RuntimeOriginTest

java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -d artifacts/core-classes app/src/main/java/com/baseer/freshchat/PlaybackState.java app/src/main/java/com/baseer/freshchat/WaveformSamples.java app/src/main/java/com/baseer/freshchat/LocalSettingsPolicy.java tests/PlaybackStateTest.java tests/WaveformSamplesTest.java tests/LocalSettingsPolicyTest.java
java -cp artifacts/core-classes PlaybackStateTest
java -cp artifacts/core-classes WaveformSamplesTest
java -cp artifacts/core-classes LocalSettingsPolicyTest

java com.sun.tools.javac.Main -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath artifacts/core-classes -d artifacts/core-classes tests/StorageFoundationTest.java tests/StoreJournalTest.java
java -cp artifacts/core-classes StorageFoundationTest
java -cp artifacts/core-classes StoreJournalTest
