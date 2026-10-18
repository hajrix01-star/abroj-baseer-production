#!/usr/bin/env python3
"""Compile actual SDK35 channels + preference tests in a separate unsigned no-UI/no-network test APK."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat/BChatNotificationChannels.java'
before = hashlib.sha256(source.read_bytes()).hexdigest()
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
build = sdk / 'build-tools/35.0.0'
android = sdk / 'platforms/android-35/android.jar'
suffix = '.exe' if os.name == 'nt' else ''
javac = shutil.which('javac')
if not javac or not android.is_file():
    raise SystemExit('Existing JDK17 and SDK35 required; nothing is downloaded.')
output = root / 'artifacts/BChat-Channel-Tests-UNSIGNED.apk'
temporary = root / 'artifacts/test-runtime'
temporary.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='channel-tests-', dir=temporary) as name:
    folder = Path(name)
    classes, dex = folder / 'classes', folder / 'dex'
    classes.mkdir(); dex.mkdir()
    base = folder / 'base.apk'
    subprocess.run([str(build / ('aapt2' + suffix)), 'link', '-o', str(base), '-I', str(android),
                    '--manifest', str(root / 'tests/notification-channels/native/AndroidManifest.xml')], check=True)
    sources = [source, root / 'tests/notification-channels/native/ChannelInstrumentation.java']
    subprocess.run([javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
                    '-cp', str(android), '-d', str(classes), *map(str, sources)], check=True)
    args = folder / 'classes.txt'
    args.write_text('\n'.join(str(file).replace('\\', '/') for file in classes.rglob('*.class')), encoding='utf-8')
    subprocess.run([str(build / ('d8.bat' if os.name == 'nt' else 'd8')), '--min-api', '26',
                    '--lib', str(android), '--output', str(dex), '@' + str(args)], check=True)
    with zipfile.ZipFile(base, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in dex.glob('classes*.dex'): archive.write(file, file.name)
    subprocess.run([str(build / ('zipalign' + suffix)), '-f', '4', str(base), str(output)], check=True)
if hashlib.sha256(source.read_bytes()).hexdigest() != before:
    raise SystemExit('Production channel source changed during native build.')
print('Production channel source SHA256:', before)
print(output)
print('Unsigned isolated test artifact only; no device install, notification/audio or product APK claim.')
