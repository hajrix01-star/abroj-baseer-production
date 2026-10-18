#!/usr/bin/env python3
"""Build/run an isolated actual-OS privacy harness; never a product APK or FCM test.

Real production modules and Android35 notify/active rows/SharedPrefs, synthetic event/auth
posting driver, bounded executor adapter and explicit test resources. No HTTP/audio/network.
--run requires the parent-owned emulator lease. Only the unique disposable package is changed.
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

PACKAGE = 'com.baseer.bchat.notification.privacy.test'
INSTRUMENTATION = PACKAGE + '/com.baseer.freshchat.NotificationPrivacyInstrumentation'
parser = argparse.ArgumentParser()
parser.add_argument('--run', action='store_true')
parser.add_argument('--boundary-only', action='store_true', help='Only the bounded immediate-post/reset race probe, not completed main journeys')
parser.add_argument('--baseline-reset', type=Path, help='Exact archived unmodified A2017C7F Reset only; replaces compiled Reset input, not product source')
parser.add_argument('--serial', default='emulator-5580')
parser.add_argument('--label', required=True, help='Fresh evidence folder; previous runs are never overwritten')
args = parser.parse_args()
if args.serial != 'emulator-5580' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Only authorized emulator-5580 and a safe unique label are accepted')
root = Path(__file__).resolve().parents[1]
output = root / 'artifacts/notification-privacy-android' / args.label
if output.exists():
    raise SystemExit('Evidence folder already exists; choose a new label without overwriting prior evidence')
output.mkdir(parents=True)
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
bt = sdk / 'build-tools/35.0.0'
jar = sdk / 'platforms/android-35/android.jar'
java_home = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot'))
javac = shutil.which('javac') or str(java_home / 'bin/javac.exe')
exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
signing = Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')
key, password_file = signing / 'bchat-preview-fresh.p12', signing / 'keystore.password'
if not key.is_file() or not password_file.is_file():
    raise SystemExit('Existing documented signing files are required; no secrets are read/printed or key generated')


def run(*command, timeout=90):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=timeout)
    with (output / 'build-and-run.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-5000:])
        raise SystemExit(f'{Path(str(command[0])).name} failed; inspect preserved build-and-run.log')
    return result.stdout


source = root / 'app/src/main/java/com/baseer/freshchat'
names = ('BChatPushState', 'BChatNotificationPresentationReset', 'BChatNotificationConversations',
         'NotificationPresentation', 'BChatMessagingNotificationStyle', 'BChatNotificationChannels',
         'BChatNotificationLedger', 'AvatarInitials')
production = [source / (name + '.java') for name in names]
production += [source / 'sync/AccountScope.java', source / 'sync/OutboxPolicy.java']
override = None
if args.baseline_reset:
    archived = (root / 'artifacts/test-results/C15-pending-registration-GREEN/inputs/app/src/main/java/com/baseer/freshchat/BChatNotificationPresentationReset.java').resolve()
    if args.baseline_reset.resolve() != archived or hashlib.sha256(archived.read_bytes()).hexdigest() != 'a2017c7fd31468d006559fc99fba85ebea76dff3d24e10d3afb325b4dbcc49dc':
        raise SystemExit('Only the exact archived original Reset SHA256 A2017C7F is allowed; no source mutation')
    production[production.index(source / 'BChatNotificationPresentationReset.java')] = archived
    override = {'production_class': 'BChatNotificationPresentationReset',
                'compiled_source': archived.relative_to(root).as_posix(),
                'sha256': 'a2017c7fd31468d006559fc99fba85ebea76dff3d24e10d3afb325b4dbcc49dc',
                'reason': 'Actual frozen prior source, same measurement harness; old service had no posting hook'}
tests = root / 'tests/notification-privacy'
inputs = production + sorted(path for path in tests.rglob('*') if path.is_file()) + [Path(__file__).resolve()]
hashes = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
manifest = {'schema': 1, 'source_sha256': hashes,
            'compiled_override': override,
            'scope': 'Actual Android35 OS notify/cancel/active rows + real production modules/SharedPrefs; '
                     'synthetic event/auth posting driver, bounded executor and test-resource adapters; '
                     'no service/FCM/HTTP/Activity/audio/OEM/API26/product-release claim'}
(output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def frozen():
    changed = [path.relative_to(root).as_posix() for path in inputs
               if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[path.relative_to(root).as_posix()]]
    if changed:
        raise SystemExit('Inputs changed during verification; no frozen acceptance claimed: ' + ', '.join(changed))


with tempfile.TemporaryDirectory(prefix='build-', dir=output) as temporary:
    build = Path(temporary)
    classes, dex, generated = build / 'classes', build / 'dex', build / 'generated'
    for folder in (classes, dex, generated):
        folder.mkdir()
    run(bt / ('aapt2' + exe), 'compile', '--dir', tests / 'res', '-o', build / 'resources.zip')
    run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', jar,
        '--manifest', tests / 'AndroidManifest.xml', build / 'resources.zip',
        '--java', generated, '--custom-package', 'com.baseer.freshchat')
    run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
        '-cp', jar, '-d', classes, *generated.rglob('*.java'), *production, *tests.rglob('*.java'))
    with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in classes.rglob('*.class'):
            archive.write(item, item.relative_to(classes).as_posix())
    run(bt / ('d8' + batch), '--min-api', '26', '--lib', jar, '--output', dex, build / 'classes.jar')
    with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
        for item in dex.glob('*.dex'):
            archive.write(item, item.name)
    run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
    apk = output / 'BChat-standalone-OS-privacy-tests.apk'
    run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
        '--ks-pass', 'file:' + str(password_file), '--out', apk, build / 'aligned.apk')
    run(bt / ('apksigner' + batch), 'verify', apk)
frozen()
print('Standalone OS privacy test APK verified; no product APK built', flush=True)
if args.run:
    adb = sdk / ('platform-tools/adb' + exe)
    run(adb, '-s', args.serial, 'install', '-r', apk)
    run(adb, '-s', args.serial, 'shell', 'pm', 'grant', PACKAGE, 'android.permission.POST_NOTIFICATIONS')
    for phase in (('boundary',) if args.boundary_only else ('main', 'cold')):
        if phase == 'cold':
            # Kill a cached test process WITHOUT force-stop, which would cancel OS rows itself.
            run(adb, '-s', args.serial, 'shell', 'am', 'kill', PACKAGE)
        result = run(adb, '-s', args.serial, 'shell', 'am', 'instrument', '-w', '-r',
                     '-e', 'phase', phase, INSTRUMENTATION, timeout=90)
        (output / f'instrumentation-{phase}.log').write_text(result, encoding='utf-8')
        captured = subprocess.run([str(adb), '-s', args.serial, 'exec-out', 'run-as', PACKAGE,
                                   'cat', f'files/notification-privacy-{phase}.json'], capture_output=True, timeout=15)
        if captured.returncode:
            raise SystemExit('Native result missing; no result manufactured')
        (output / f'notification-privacy-{phase}.json').write_bytes(captured.stdout)
        evidence = json.loads(captured.stdout)
        print(result, flush=True)
        frozen()
        if not evidence.get('passed') or evidence.get('phase') != phase or 'INSTRUMENTATION_CODE: -1' not in result:
            raise SystemExit('Native privacy check failed; preserved actual evidence, no acceptance claimed')
    print('PASS native '+('boundary-only probe' if args.boundary_only else 'main + real-new-process cold privacy')
          +'; no product/service/FCM/audio/OEM/API26 acceptance claim')
