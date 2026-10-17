#!/usr/bin/env python3
"""Execute the production channel module against explicit JVM API26/API35 preference/platform fixtures."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat/BChatNotificationChannels.java'
before = hashlib.sha256(source.read_bytes()).hexdigest()
temporary = root / 'artifacts/test-runtime'
temporary.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='notification-channels-', dir=temporary) as folder:
    classes = Path(folder) / 'classes'
    classes.mkdir()
    fixtures = list((root / 'tests/notification-channels/jvm').rglob('*.java'))
    subprocess.run([shutil.which('javac') or 'javac', '-encoding', 'UTF-8', '-d', str(classes),
                    *map(str, fixtures), str(source)], check=True)
    subprocess.run([shutil.which('java') or 'java', '-cp', str(classes),
                    'com.baseer.freshchat.ChannelRoutingHarness'], check=True)
after = hashlib.sha256(source.read_bytes()).hexdigest()
if before != after:
    raise SystemExit('Production channel source changed during verification.')
print('Production channel source SHA256:', before)
print('No Android/OEM, audio, service/settings integration or product release claim.')
