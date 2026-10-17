#!/usr/bin/env python3
"""Production renderer: explicit legacy JVM API adapters, optional actual Android35 construction.

The standalone test does not post notifications, create channels, request permissions, or
exercise service/auth/FCM/audio/OEM/product Activity behavior. No product APK is built.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--build-android', action='store_true')
parser.add_argument('--run', action='store_true', help='Build and run only the isolated test package')
parser.add_argument('--serial', default='emulator-5580')
parser.add_argument('--label', default='jvm', help='Separate evidence directory; native runs require a fresh label')
args = parser.parse_args()
if args.serial != 'emulator-5580' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Only the authorized emulator and a bounded evidence label are accepted')
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
tests = root / 'tests/notification-messaging'
production = [source / (name + '.java') for name in (
    'BChatMessagingNotificationStyle', 'BChatNotificationConversations', 'NotificationPresentation', 'AvatarInitials')]
resources = sorted(path for path in (root / 'app/src/main/res').rglob('*') if path.is_file())
inputs = production + resources + sorted(path for path in tests.rglob('*') if path.is_file()) + [Path(__file__).resolve()]
hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
output = root / 'artifacts/notification-messaging' / args.label
output.mkdir(parents=True, exist_ok=True)
if args.run and (output / 'instrumentation.log').exists():
    raise SystemExit('Use a fresh native evidence label; prior runtime evidence is preserved')
scope = ('Production renderer/parser/RAM projection; explicit legacy JVM adapters. Optional actual SDK35 '
         'Builder/Person/Canvas/Icon/Parcel construction only; no notify/channel/audio/FCM/OEM/API26 runtime/product Activity')
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope, 'source_sha256': hashes},
    ensure_ascii=False, indent=2), encoding='utf-8')


def run(*command, timeout=90):
    result = subprocess.run([str(item) for item in command], text=True, encoding='utf-8',
                            errors='replace', capture_output=True, timeout=timeout)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit(f'{Path(str(command[0])).name} failed ({result.returncode}); see build.log')
    return result.stdout


def frozen():
    for path in inputs:
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[path.relative_to(root).as_posix()]:
            raise SystemExit('Input changed during verification: ' + path.relative_to(root).as_posix())


java_home = Path(os.environ.get('JAVA_HOME', r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'))
javac = shutil.which('javac') or java_home / 'bin/javac.exe'
java = shutil.which('java') or java_home / 'bin/java.exe'
with tempfile.TemporaryDirectory(prefix='jvm-', dir=output) as folder:
    classes = Path(folder) / 'classes'
    classes.mkdir()
    run(javac, '-encoding', 'UTF-8', '-d', classes, *production,
        *sorted((tests / 'shared').rglob('*.java')), *sorted((tests / 'jvm').rglob('*.java')))
    result = run(java, '-cp', classes, 'com.baseer.freshchat.LegacyMessagingHarness')
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    if not re.search(r'^PASS [1-9][0-9]* production renderer assertions', result):
        raise SystemExit('Missing legacy boundary assertion evidence')
    print(result, end='')
frozen()

if args.build_android or args.run:
    sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
    bt, jar = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
    approved = Path(os.environ.get('LOCALAPPDATA', '')) / 'Baseer/BChatSigning/fresh-install-20261009'
    key = Path(os.environ.get('BCHAT_SIGNING_KEY', str(approved / 'bchat-preview-fresh.p12')))
    password = Path(os.environ.get('BCHAT_SIGNING_PASSWORD_FILE', str(approved / 'keystore.password')))
    if not key.is_file() or not password.is_file():
        raise SystemExit('Existing documented signing paths required; this tool never creates/reads a key')
    with tempfile.TemporaryDirectory(prefix='android-', dir=output) as folder:
        build = Path(folder)
        classes, dex, generated = build / 'classes', build / 'dex', build / 'generated'
        for directory in (classes, dex, generated):
            directory.mkdir()
        run(bt / ('aapt2' + exe), 'compile', '--dir', root / 'app/src/main/res', '-o', build / 'resources.zip')
        run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', jar, '--manifest',
            tests / 'native/AndroidManifest.xml', build / 'resources.zip', '--java', generated,
            '--custom-package', 'com.baseer.freshchat')
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
            '-cp', jar, '-d', classes, *sorted(generated.rglob('*.java')), *production,
            *sorted((tests / 'shared').rglob('*.java')), *sorted((tests / 'native').rglob('*.java')))
        with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in classes.rglob('*.class'):
                archive.write(path, path.relative_to(classes).as_posix())
        run(bt / ('d8' + batch), '--min-api', '26', '--lib', jar, '--output', dex, build / 'classes.jar')
        with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
            for path in dex.glob('*.dex'):
                archive.write(path, path.name)
        run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
        apk = output / 'BChat-standalone-notification-messaging-tests.apk'
        run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
            '--ks-pass', 'file:' + str(password), '--out', apk, build / 'aligned.apk')
        run(bt / ('apksigner' + batch), 'verify', apk)
        print('Standalone renderer test APK verified; no product APK built or modified', flush=True)
        if args.run:
            adb = sdk / ('platform-tools/adb' + exe)
            package = 'com.baseer.bchat.notification.messaging.test'
            run(adb, '-s', args.serial, 'install', '-r', apk)
            result = run(adb, '-s', args.serial, 'shell', 'am', 'instrument', '-w', '-r',
                         package + '/com.baseer.freshchat.MessagingInstrumentation', timeout=90)
            (output / 'instrumentation.log').write_text(result, encoding='utf-8')
            print(result)
            if not re.search(r'PASS [1-9][0-9]* actual Android35 MessagingStyle assertions', result) or 'INSTRUMENTATION_CODE: 0' not in result:
                raise SystemExit('Native construction checks failed; preserved instrumentation.log')
            raw = run(adb, '-s', args.serial, 'exec-out', 'run-as', package, 'cat', 'files/messaging-results.json')
            (output / 'messaging-results.json').write_text(raw, encoding='utf-8')
            evidence = json.loads(raw)
            samples = evidence.get('samples', [])
            if evidence.get('passed') is not True or evidence.get('sdk') != 35 or evidence.get('configurations') != 4:
                raise SystemExit('Unexpected native evidence scope')
            if evidence.get('cases') != 48 or len(samples) != 48 or len({item.get('case') for item in samples}) != 48:
                raise SystemExit('Incomplete/duplicate native construction inventory')
            if any(item.get('passed') is not True or not 0 <= item.get('messages', -1) <= 5 for item in samples):
                raise SystemExit('Invalid native construction sample')
    frozen()
print('Frozen-source verification complete. ' + scope)
