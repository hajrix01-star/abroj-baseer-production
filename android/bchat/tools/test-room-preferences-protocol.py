#!/usr/bin/env python3
"""C17 protocol only: JVM semantic JSON adapter by default; optional native Android35 JSON.

Never compiles a product APK or touches Activity/PushState/store/controller/HTTP/FCM.
The optional standalone package has no permissions, resources, UI or network.
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
parser.add_argument('--run', action='store_true')
parser.add_argument('--serial', default='emulator-5580')
parser.add_argument('--label', default='jvm')
args = parser.parse_args()
if args.serial != 'emulator-5580' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Only the authorized emulator and a bounded evidence label are accepted')
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
tests = root / 'tests/room-preferences-protocol'
production = [source / 'RoomPreferencesProtocol.java', source / 'sync/AccountScope.java', source / 'sync/OutboxPolicy.java']
inputs = production + sorted(path for path in tests.rglob('*') if path.is_file()) + [Path(__file__).resolve()]
hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
output = root / 'artifacts/room-preferences-protocol' / args.label
output.mkdir(parents=True, exist_ok=True)
if (output / 'instrumentation.log').exists() or (output / 'jvm.log').exists():
    raise SystemExit('Use a fresh evidence label; previous logs are never replaced')
scope = ('Production protocol + AccountScope/OutboxPolicy values only. Default JVM JSONObject object-map adapter, '
         'not a text parser. Optional actual Android35 JSON text/value component. No storage/controller/HTTP/FCM/UI/C17 completion')
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
    result = run(java, '-cp', classes, 'com.baseer.freshchat.RoomPreferencesJvm')
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production RoomPreferencesProtocol checks', result)
    if not match:
        raise SystemExit('Missing JVM protocol evidence')
    print(result, end='')
    jvm_checks = int(match.group(1))
frozen()

if args.build_android or args.run:
    sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
    bt, jar = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
    approved = Path(os.environ.get('LOCALAPPDATA', '')) / 'Baseer/BChatSigning/fresh-install-20261009'
    key = Path(os.environ.get('BCHAT_SIGNING_KEY', str(approved / 'bchat-preview-fresh.p12')))
    password = Path(os.environ.get('BCHAT_SIGNING_PASSWORD_FILE', str(approved / 'keystore.password')))
    if not key.is_file() or not password.is_file():
        raise SystemExit('Existing documented signing paths required; no key is generated/read by this tool')
    with tempfile.TemporaryDirectory(prefix='android-', dir=output) as folder:
        build = Path(folder)
        classes, dex = build / 'classes', build / 'dex'
        classes.mkdir(); dex.mkdir()
        run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', jar,
            '--manifest', tests / 'native/AndroidManifest.xml')
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', jar,
            '-d', classes, *production, *sorted((tests / 'shared').rglob('*.java')),
            *sorted((tests / 'native').rglob('*.java')))
        with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in classes.rglob('*.class'):
                archive.write(path, path.relative_to(classes).as_posix())
        run(bt / ('d8' + batch), '--min-api', '26', '--lib', jar, '--output', dex, build / 'classes.jar')
        with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
            for path in dex.glob('*.dex'):
                archive.write(path, path.name)
        run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
        apk = output / 'BChat-standalone-room-preferences-protocol-tests.apk'
        run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
            '--ks-pass', 'file:' + str(password), '--out', apk, build / 'aligned.apk')
        run(bt / ('apksigner' + batch), 'verify', apk)
        print('Standalone protocol APK verified; no product APK/resources compiled or modified', flush=True)
        if args.run:
            adb, package = sdk / ('platform-tools/adb' + exe), 'com.baseer.bchat.room.preferences.protocol.test'
            run(adb, '-s', args.serial, 'install', '-r', apk)
            result = run(adb, '-s', args.serial, 'shell', 'am', 'instrument', '-w', '-r',
                         package + '/com.baseer.freshchat.RoomPreferencesInstrumentation', timeout=90)
            (output / 'instrumentation.log').write_text(result, encoding='utf-8')
            print(result)
            if not re.search(r'PASS [1-9][0-9]* actual Android35 room preference protocol assertions', result) or 'INSTRUMENTATION_CODE: 0' not in result:
                raise SystemExit('Native protocol checks failed; preserved instrumentation.log')
            raw = run(adb, '-s', args.serial, 'exec-out', 'run-as', package, 'cat', 'files/room-preferences-protocol-results.json')
            (output / 'room-preferences-protocol-results.json').write_text(raw, encoding='utf-8')
            evidence = json.loads(raw)
            if evidence.get('passed') is not True or evidence.get('sdk') != 35 or evidence.get('shared_value_checks') != jvm_checks:
                raise SystemExit('Unexpected native scope/inventory')
            if type(evidence.get('native_text_checks')) is not int or evidence['native_text_checks'] <= 0 or evidence.get('assertions') != jvm_checks + evidence['native_text_checks']:
                raise SystemExit('Incomplete native JSON evidence')
    frozen()
print('Frozen-source verification complete. ' + scope)
