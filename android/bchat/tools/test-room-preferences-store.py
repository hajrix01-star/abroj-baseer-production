#!/usr/bin/env python3
"""C17 Store-only tests: declared JVM file/API adapters, optional real Android35 AtomicFile.

No product APK, Activity, network, auth, controller or FCM. Uses the already installed Gradle
Gson only for the JVM JSONObject adapter, never a new product dependency or a wire-parser claim.
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
import uuid
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path, help='Optional existing SDK35 stub compile only; no Android execution')
parser.add_argument('--build-android', action='store_true')
parser.add_argument('--run', action='store_true')
parser.add_argument('--serial', default='emulator-5580')
parser.add_argument('--label', default='jvm')
parser.add_argument('--case', choices=('all', 'ambiguous-epoch', 'recovery', 'membership-snapshot'), default='all')
args = parser.parse_args()
if args.case in ('recovery', 'membership-snapshot') and (args.build_android or args.run):
    raise SystemExit('Recovery/rejoin delta is JVM-only; existing native AtomicFile evidence is not rerun/relabelled')
if args.android_jar and not args.android_jar.is_file():
    raise SystemExit('Explicit SDK stub missing; no download or silent skip')
if args.serial != 'emulator-5580' or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Only authorized emulator and a bounded evidence label are accepted')
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
tests = root / 'tests/room-preferences-store'
production = [source / 'RoomPreferencesStore.java', source / 'RoomPreferencesProtocol.java',
              source / 'sync/AccountScope.java', source / 'sync/OutboxPolicy.java']
inputs = production + sorted(path for path in tests.rglob('*') if path.is_file()) + [Path(__file__).resolve()]
input_bytes = {path.relative_to(root).as_posix(): path.read_bytes() for path in inputs}
hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in input_bytes.items()}
output = root / 'artifacts/room-preferences-store' / args.label
output.mkdir(parents=True, exist_ok=True)
if (output / 'source-manifest.json').exists():
    raise SystemExit('Use a fresh evidence label; previous source/log evidence is preserved')
archived = output / 'inputs'
archived.mkdir(exist_ok=False)
for name, raw in input_bytes.items():
    target = archived / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
production_build = [archived / path.relative_to(root) for path in production]
tests_build = archived / tests.relative_to(root)
scope = ('Production Store/Protocol on actual JVM files with explicit Context/Looper/AtomicFile/Gson-JSON adapters; '
         + ('recovery/rejoin delta JVM-only; no native/restart rerun. ' if args.case in ('recovery', 'membership-snapshot') else
            'optional actual Android35 AtomicFile/JSON/Looper and four restart processes. ' if args.case == 'all' else
            'optional focused actual Android35 AtomicFile/JSON/Looper ambiguous-epoch edge; no restart-suite rerun. ')
         + 'Fault injections are explicit; '
         'no power-loss/interprocess-writer/HTTP/auth/controller/UI/FCM/C17 completion')
candidates = [args.gson_jar]
if os.environ.get('BCHAT_TEST_GSON_JAR'):
    candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
if os.environ.get('GRADLE_HOME'):
    candidates += list((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
candidates += list(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
gradle = shutil.which('gradle')
if gradle:
    candidates += list((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
gson = next((candidate.resolve() for candidate in candidates if candidate and candidate.is_file()), None)
if gson is None:
    raise SystemExit('Existing Gradle Gson required via --gson-jar; nothing is downloaded/installed')
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope, 'case': args.case,
    'archived_inputs': 'inputs', 'compiled_from_archived_inputs': True, 'source_sha256': hashes,
    'jvm_adapter_gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest(),
    'android_stub_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None}, ensure_ascii=False, indent=2), encoding='utf-8')


def run(*command, timeout=120):
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
        name = path.relative_to(root).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Source changed during verification: ' + name)
        if hashlib.sha256((archived / name).read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Archived input changed during verification: ' + name)


java_home = Path(os.environ.get('JAVA_HOME', r'C:\Program Files\Eclipse Adoptium\jdk-17.0.20.101-hotspot'))
javac = shutil.which('javac') or java_home / 'bin/javac.exe'
java = shutil.which('java') or java_home / 'bin/java.exe'
frozen()
with tempfile.TemporaryDirectory(prefix='jvm-', dir=output) as folder:
    classes = Path(folder) / 'classes'
    files = output / 'membership-private-files' if args.case == 'membership-snapshot' else Path(folder) / 'owned-files'
    classes.mkdir(); files.mkdir()
    run(javac, '-encoding', 'UTF-8', '-cp', gson, '-d', classes, *production_build,
        *sorted((tests_build / 'shared').rglob('*.java')), *sorted((tests_build / 'jvm').rglob('*.java')))
    result = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), 'com.baseer.freshchat.StoreJvm', files, args.case)
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production RoomPreferencesStore checks', result, re.M)
    if not match:
        raise SystemExit('Missing Store JVM evidence')
    print(result, end='')
    jvm_checks = int(match.group(1))
    membership_results = files / 'membership-snapshot-results/results.json'
    if membership_results.is_file():
        shutil.copyfile(membership_results, output / 'membership-results.json')
    if args.android_jar:
        stub_classes = Path(folder) / 'sdk35-stub-classes'
        stub_classes.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', args.android_jar,
            '-d', stub_classes, *production_build)
frozen()

if args.build_android or args.run:
    sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
    bt, jar = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
    approved = Path(os.environ.get('LOCALAPPDATA', '')) / 'Baseer/BChatSigning/fresh-install-20261009'
    key = Path(os.environ.get('BCHAT_SIGNING_KEY', str(approved / 'bchat-preview-fresh.p12')))
    password = Path(os.environ.get('BCHAT_SIGNING_PASSWORD_FILE', str(approved / 'keystore.password')))
    if not key.is_file() or not password.is_file():
        raise SystemExit('Existing documented signing paths required; no key generated/read by this tool')
    with tempfile.TemporaryDirectory(prefix='android-', dir=output) as folder:
        build = Path(folder); classes, dex = build / 'classes', build / 'dex'; classes.mkdir(); dex.mkdir()
        run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', jar, '--manifest', tests_build / 'native/AndroidManifest.xml')
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', jar,
            '-d', classes, *production_build, *sorted((tests_build / 'shared').rglob('*.java')), *sorted((tests_build / 'native').rglob('*.java')))
        with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in classes.rglob('*.class'):
                archive.write(path, path.relative_to(classes).as_posix())
        run(bt / ('d8' + batch), '--min-api', '26', '--lib', jar, '--output', dex, build / 'classes.jar')
        with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
            for path in dex.glob('*.dex'):
                archive.write(path, path.name)
        run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
        apk = output / 'BChat-standalone-room-preferences-store-tests.apk'
        run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
            '--ks-pass', 'file:' + str(password), '--out', apk, build / 'aligned.apk')
        run(bt / ('apksigner' + batch), 'verify', apk)
        print('Standalone Store test APK verified; no product APK/resources compiled or modified', flush=True)
        if args.run:
            adb, package = sdk / ('platform-tools/adb' + exe), 'com.baseer.bchat.room.preferences.store.test'
            run(adb, '-s', args.serial, 'install', '-r', apk)
            session, evidence = uuid.uuid4().hex, []
            phases = ('all', 'seed', 'started', 'ack', 'verify') if args.case == 'all' else ('ambiguous',)
            for phase in phases:
                # Only our uniquely named standalone test process is stopped; never product/user apps.
                run(adb, '-s', args.serial, 'shell', 'am', 'force-stop', package)
                result = run(adb, '-s', args.serial, 'shell', 'am', 'instrument', '-w', '-r',
                    '-e', 'phase', phase, '-e', 'session', session, package + '/com.baseer.freshchat.StoreInstrumentation')
                (output / ('instrumentation-' + phase + '.log')).write_text(result, encoding='utf-8')
                print(result)
                if not re.search(r'PASS [1-9][0-9]* actual Android35 RoomPreferencesStore assertions', result) or 'INSTRUMENTATION_CODE: 0' not in result:
                    raise SystemExit('Native Store phase failed; evidence preserved: ' + phase)
                raw = run(adb, '-s', args.serial, 'exec-out', 'run-as', package, 'cat', f'files/store-results-{phase}-{session}.json')
                (output / ('results-' + phase + '.json')).write_text(raw, encoding='utf-8')
                item = json.loads(raw)
                if item.get('passed') is not True or item.get('phase') != phase or item.get('session') != session or item.get('sdk') != 35:
                    raise SystemExit('Native phase identity mismatch')
                if type(item.get('process_id')) is not int or item['process_id'] <= 0 or type(item.get('assertions')) is not int or item['assertions'] <= 0:
                    raise SystemExit('Native phase process/assertion evidence missing')
                evidence.append(item)
            if evidence[0]['assertions'] != jvm_checks or len({item['process_id'] for item in evidence}) != len(phases):
                raise SystemExit('Incomplete shared-case or real separate-process evidence')
            evidence_name = 'restart-evidence.json' if args.case == 'all' else 'focused-evidence.json'
            (output / evidence_name).write_text(json.dumps({'schema': 1, 'passed': True, 'case': args.case,
                'session': session, 'phases': evidence, 'restart_cutpoints': 3 if args.case == 'all' else 0,
                'scope': 'Sequential process stops (all suite) or focused ambiguous-epoch component only; not hardware power loss or network'}, indent=2), encoding='utf-8')
    frozen()
if args.case == 'membership-snapshot':
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'case': args.case,
        'scope': scope, 'assertions': jvm_checks, 'source_inputs': len(inputs),
        'source_archive_before_after_equal': True, 'android35_stub_compile_only': bool(args.android_jar),
        'actual_private_files': 'membership-private-files', 'bound_results': 'membership-results.json'}, indent=2), encoding='utf-8')
print('Frozen-source verification complete. ' + scope)
