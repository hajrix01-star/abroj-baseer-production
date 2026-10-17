#!/usr/bin/env python3
"""Actual Android cart presentation, isolated package only; no product APK/financial API."""
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
parser.add_argument('--run', action='store_true')
parser.add_argument('--label', required=True)
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Bounded evidence label required')
root = Path(__file__).resolve().parents[1]
output = root / 'artifacts/cart-sheet-android' / args.label
if output.exists():
    raise SystemExit('Never overwrite earlier evidence; use a new label')
output.mkdir(parents=True)
tests = root / 'tests/cart-sheet-android'
source = root / 'app/src/main/java/com/baseer/freshchat'
names = ('Ui', 'UiPalette', 'ChatAppearance', 'AvatarInitials', 'AppLocale', 'AppLocalePolicy',
         'LocalSettings', 'LocalSettingsPolicy', 'BChatCartSheet', 'OrderQuantityStepper')
production = [source / (name + '.java') for name in names]
resources = sorted(path for path in (root / 'app/src/main/res').rglob('*') if path.is_file())
inputs = production + resources + sorted(path for path in tests.rglob('*') if path.is_file()) + [Path(__file__).resolve()]
hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
frozen = output / 'inputs'
for path in inputs:
    destination = frozen / path.relative_to(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, destination)
manifest = {'schema': 1, 'source_sha256': hashes,
            'scope': 'Production cart Dialog/line/quantity UI on Android35 with explicit fake action/quote/editor Host. '
                     'No product Activity, price math, persistence, order API, network, phone/OEM or whole C23 acceptance'}
(output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
bt, jar = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
java_home = Path(os.environ.get('JAVA_HOME', r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'))
javac = shutil.which('javac') or java_home / 'bin/javac.exe'
key, password = Path(os.environ['BCHAT_SIGNING_KEY']), Path(os.environ['BCHAT_SIGNING_PASSWORD_FILE'])
if not key.is_file() or not password.is_file():
    raise SystemExit('Existing approved signing files required; no generation or secret output')


def run(*command, timeout=120):
    result = subprocess.run([str(value) for value in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit((result.stdout + result.stderr)[-6000:])
    return result.stdout


def verify():
    for relative, expected in hashes.items():
        if any(hashlib.sha256((base / relative).read_bytes()).hexdigest() != expected for base in (root, frozen)):
            raise SystemExit('Source changed: ' + relative)


verify()
with tempfile.TemporaryDirectory(prefix='build-', dir=output) as folder:
    build = Path(folder)
    classes, generated, dex = build / 'classes', build / 'generated', build / 'dex'
    for path in (classes, generated, dex):
        path.mkdir()
    run(bt / ('aapt2' + exe), 'compile', '--dir', frozen / 'app/src/main/res', '-o', build / 'resources.zip')
    run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', jar, '--manifest',
        frozen / 'tests/cart-sheet-android/AndroidManifest.xml', build / 'resources.zip',
        '--java', generated, '--custom-package', 'com.baseer.freshchat')
    run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', jar,
        '-d', classes, *generated.rglob('*.java'), *(frozen / path.relative_to(root) for path in production),
        *sorted((frozen / 'tests/cart-sheet-android').rglob('*.java')))
    with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in classes.rglob('*.class'):
            archive.write(path, path.relative_to(classes).as_posix())
    run(bt / ('d8' + batch), '--min-api', '26', '--lib', jar, '--output', dex, build / 'classes.jar')
    with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
        for path in dex.glob('*.dex'):
            archive.write(path, path.name)
    run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
    apk = output / 'BChat-standalone-cart-sheet-tests.apk'
    run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
        '--ks-pass', 'file:' + str(password), '--out', apk, build / 'aligned.apk')
    run(bt / ('apksigner' + batch), 'verify', apk)
    manifest['test_apk_sha256'] = hashlib.sha256(apk.read_bytes()).hexdigest()
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
verify()
print('Standalone cart UI test APK verified; no product APK built', flush=True)
if args.run:
    adb = sdk / ('platform-tools/adb' + exe)
    package = 'com.baseer.bchat.cart.sheet.test'
    run(adb, '-s', 'emulator-5580', 'install', '-r', apk)
    native = run(adb, '-s', 'emulator-5580', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'disposable', 'true',
                 package + '/com.baseer.freshchat.CartSheetInstrumentation', timeout=150)
    (output / 'instrumentation.log').write_text(native, encoding='utf-8')
    raw = subprocess.run([str(adb), '-s', 'emulator-5580', 'exec-out', 'run-as', package, 'cat',
                          'files/cart-sheet-results.json'], capture_output=True, timeout=20)
    if raw.returncode:
        raise SystemExit('No actual native JSON; see instrumentation.log')
    (output / 'cart-sheet-results.json').write_bytes(raw.stdout)
    evidence = json.loads(raw.stdout)
    captures = output / 'captures'
    captures.mkdir()
    for render in evidence['renders']:
        for position in ('top', 'bottom'):
            name = render['name'] + '-' + position + '.png'
            frame = subprocess.run([str(adb), '-s', 'emulator-5580', 'exec-out', 'run-as', package,
                                    'cat', 'files/' + name], capture_output=True, timeout=20)
            if frame.returncode:
                raise SystemExit('Expected native frame absent: ' + name)
            (captures / name).write_bytes(frame.stdout)
    print(native, flush=True)
    verify()
    if not evidence['passed'] or 'INSTRUMENTATION_CODE: -1' not in native:
        raise SystemExit('Cart presentation test failed; preserved result/log/source, no acceptance')
