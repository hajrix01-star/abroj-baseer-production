#!/usr/bin/env python3
"""Run the real pure-Java notification parser and RAM conversation projection.

No Android fixtures, network, SharedPreferences, service extraction, or emulator are involved.
The test checks this buffer only; it does not assert OS presentation or audio behavior.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
sources = [
    root / 'app/src/main/java/com/baseer/freshchat/NotificationPresentation.java',
    root / 'app/src/main/java/com/baseer/freshchat/BChatNotificationConversations.java',
    root / 'tests/NotificationConversationsTest.java',
]
before = {source: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
temporary = root / 'artifacts/test-runtime'
temporary.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='notification-conversations-', dir=temporary) as folder:
    classes = Path(folder) / 'classes'
    classes.mkdir()
    subprocess.run([shutil.which('javac') or 'javac', '-encoding', 'UTF-8', '-d', str(classes),
                    *map(str, sources)], check=True)
    subprocess.run([shutil.which('java') or 'java', '-cp', str(classes),
                    'com.baseer.freshchat.NotificationConversationsTest'], check=True)
for source, expected in before.items():
    if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Source changed during verification: {source.name}')
    print(source.relative_to(root).as_posix(), 'SHA256:', expected)
print('Pure parser/projection/RAM-gate evidence only; no Android, MessagingStyle, FCM, audio, or product release claim.')
