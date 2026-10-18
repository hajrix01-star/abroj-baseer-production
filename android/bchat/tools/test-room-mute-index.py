#!/usr/bin/env python3
"""DEV114 index/port/controller component, real JVM files and explicit Android/JSON/queue adapters.
Optional actual Android35 standalone component package; never product APK, Activity/FCM wiring,
network, downloads or power-loss claim. JVM adapters and actual native results remain separate.
Archive the exact source/harness/tool bytes before compiling from those archives.
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


def gson_file(explicit):
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit('Explicit Gson path missing; no fallback')
        return explicit.resolve()
    paths = []
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        paths.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
    if os.environ.get('GRADLE_HOME'):
        paths += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
    executable = shutil.which('gradle')
    if executable:
        paths += sorted((Path(executable).resolve().parents[1] / 'lib').glob('gson-*.jar'))
    paths += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
    found = next((path.resolve() for path in paths if path.is_file()), None)
    if found is None:
        raise SystemExit('Existing Gson test runtime required; nothing downloaded')
    return found


parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--case', choices=('all', 'admission-state', 'recovery', 'health', 'foreign-rebind'), default='all')
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path)
parser.add_argument('--port-source', type=Path, help='Focused health regression against an archived Port; no native run')
parser.add_argument('--build-android', action='store_true')
parser.add_argument('--run', action='store_true')
parser.add_argument('--serial', default='emulator-5580')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Bounded fresh evidence label required')
if args.serial != 'emulator-5580':
    raise SystemExit('Only authorized emulator-5580')
if args.case != 'all' and (args.run or args.build_android):
    raise SystemExit('Focused JVM case does not rerun native/index suites')
gson = gson_file(args.gson_jar)
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
port_override = args.port_source.resolve() if args.port_source else None
if port_override and (args.case != 'health' or args.run or args.build_android
        or not port_override.is_file() or port_override.name != 'BChatRoomMutePort.java'
        or not port_override.is_relative_to(root / 'artifacts')):
    raise SystemExit('Port override must be an existing local artifact and focused health JVM only')


def input_bytes(path):
    return (port_override if port_override and path == source / 'BChatRoomMutePort.java' else path).read_bytes()
tests = root / 'tests/room-mute-index'
adapters = root / 'tests/room-preferences-store/jvm'
production = [source / name for name in ('BChatRoomMuteIndex.java', 'BChatRoomMutePort.java',
    'RoomPreferencesController.java', 'RoomPreferencesStore.java', 'RoomPreferencesProtocol.java',
    'NotificationPresentation.java', 'sync/AccountScope.java', 'sync/OutboxPolicy.java')]
foreign = args.case == 'foreign-rebind'
if foreign:
    production = [source / name for name in ('BChatRoomMuteIndex.java', 'NotificationPresentation.java')]
java_inputs = production + sorted(path for path in adapters.rglob('*.java') if 'com/baseer/' not in path.as_posix())
if foreign:
    java_inputs += sorted((tests / 'rebind').rglob('*.java'))
else:
    java_inputs += sorted((root / 'tests/room-preferences-controller').rglob('*.java'))
    java_inputs += sorted((tests / 'shared').rglob('*.java')) + sorted((tests / 'jvm').rglob('*.java'))
inputs = java_inputs + ([] if foreign else sorted(path for path in (tests / 'native').rglob('*') if path.is_file())) + [Path(__file__).resolve()]
output = root / 'artifacts/room-mute-index' / args.label
output.mkdir(parents=True, exist_ok=False)
archive = output / 'inputs'
hashes = {}
for path in inputs:
    name, raw = path.relative_to(root).as_posix(), input_bytes(path)
    target = archive / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[name] = hashlib.sha256(raw).hexdigest()
scope = ('Production index/port/controller and actual JVM private files; explicit Android Context/Looper/AtomicFile/'
         'Gson-JSON/queue/HTTP fixtures, no Android runtime/FCM/Activity/wiring/power-loss claim')
if foreign:
    scope = ('DEV163 actual production Index + NotificationPresentation.roomKey and JVM files; explicit Context/Looper/'
             'AtomicFile/Gson-JSON/fault adapters. No Port/Controller/Store/Host/auth/HTTP/Android runtime/FCM/'
             'process-kill/power-loss/manager-wiring claim. All existing slots complete canonical V1 same foreign '
             'route; bak then base; partial/orphan/mixed/unsupported refuse without mutation/evidence. '
             'Real SHA256 used: computed source/destination overlap guard is source-reviewed, no artificial collision adapter.')
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope, 'case': args.case, 'archived_inputs': 'inputs',
    'compiled_from_archived_inputs': True, 'source_sha256': hashes,
    'port_source_override': port_override.relative_to(root).as_posix() if port_override else None,
    'adapter_gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest(),
    'android_stub_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None}, indent=2), encoding='utf-8')


def frozen():
    for path in inputs:
        name = path.relative_to(root).as_posix()
        if hashlib.sha256(input_bytes(path)).hexdigest() != hashes[name] or hashlib.sha256((archive / name).read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Live/archive input changed: ' + name)


def run(*command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit('Mute component failed; source/log evidence retained')
    return result.stdout


frozen()
with tempfile.TemporaryDirectory(prefix='room-mute-', dir=output) as folder:
    classes, files = Path(folder) / 'classes', Path(folder) / 'owned-files'
    classes.mkdir(); files.mkdir()
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        raise SystemExit('Existing JDK required')
    run(javac, '-encoding', 'UTF-8', '-cp', gson, '-d', classes,
        *(archive / path.relative_to(root) for path in java_inputs))
    main = 'com.baseer.freshchat.RebindCases' if foreign else 'com.baseer.freshchat.RoomMuteCases'
    result = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), main, files, args.case)
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production room mute component assertions', result, re.M)
    if not match:
        raise SystemExit('Missing component assertion evidence')
    if args.android_jar:
        android_classes = Path(folder) / 'android35-stub-classes'
        android_classes.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', args.android_jar,
            '-d', android_classes, *(archive / path.relative_to(root) for path in production))
    frozen()
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'scope': scope, 'case': args.case,
        'assertions': int(match.group(1)), 'source_inputs': len(inputs), 'source_archive_before_after_equal': True,
        'focused_groups': [{'name': name, 'assertions': int(count)} for name, count in re.findall(r'^GROUP ([a-z0-9-]+) assertions=([0-9]+)$', result, re.M)] if foreign else None,
        'android35_stub_compile_only': bool(args.android_jar)}, indent=2), encoding='utf-8')
    print(result, end='')

if args.build_android or args.run:
    sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
    bt, platform = sdk / 'build-tools/35.0.0', sdk / 'platforms/android-35/android.jar'
    exe, batch = ('.exe', '.bat') if os.name == 'nt' else ('', '')
    approved = Path(os.environ.get('LOCALAPPDATA', '')) / 'Baseer/BChatSigning/fresh-install-20261009'
    key = Path(os.environ.get('BCHAT_SIGNING_KEY', str(approved / 'bchat-preview-fresh.p12')))
    password = Path(os.environ.get('BCHAT_SIGNING_PASSWORD_FILE', str(approved / 'keystore.password')))
    if not key.is_file() or not password.is_file():
        raise SystemExit('Existing documented signing paths required; no key search/generation')
    with tempfile.TemporaryDirectory(prefix='android-', dir=output) as folder:
        build = Path(folder); classes, dex = build / 'classes', build / 'dex'; classes.mkdir(); dex.mkdir()
        run(bt / ('aapt2' + exe), 'link', '-o', build / 'base.apk', '-I', platform, '--manifest',
            archive / 'tests/room-mute-index/native/AndroidManifest.xml')
        native_java = production + sorted((tests / 'shared').rglob('*.java')) + sorted((tests / 'native').rglob('*.java'))
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', platform,
            '-d', classes, *(archive / path.relative_to(root) for path in native_java))
        with zipfile.ZipFile(build / 'classes.jar', 'w', zipfile.ZIP_DEFLATED) as package:
            for path in classes.rglob('*.class'):
                package.write(path, path.relative_to(classes).as_posix())
        run(bt / ('d8' + batch), '--min-api', '26', '--lib', platform, '--output', dex, build / 'classes.jar')
        with zipfile.ZipFile(build / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as package:
            for path in dex.glob('*.dex'):
                package.write(path, path.name)
        run(bt / ('zipalign' + exe), '-f', '4', build / 'base.apk', build / 'aligned.apk')
        apk = output / 'BChat-standalone-room-mute-component-tests.apk'
        run(bt / ('apksigner' + batch), 'sign', '--ks', key, '--ks-key-alias', 'bchat-preview',
            '--ks-pass', 'file:' + str(password), '--out', apk, build / 'aligned.apk')
        run(bt / ('apksigner' + batch), 'verify', apk)
        (output / 'native-build.json').write_text(json.dumps({'schema': 1,
            'apk_sha256': hashlib.sha256(apk.read_bytes()).hexdigest(), 'sdk35_stub_sha256': hashlib.sha256(platform.read_bytes()).hexdigest(),
            'scope': 'Unique standalone component package only; no product APK/resources/FCM'}, indent=2), encoding='utf-8')
        frozen()
        if args.run:
            adb, package_name = sdk / ('platform-tools/adb' + exe), 'com.baseer.bchat.room.mute.index.test'
            run(adb, '-s', args.serial, 'install', '-r', apk)
            session, evidence = uuid.uuid4().hex, []
            for phase in ('all', 'seed', 'clear', 'verify'):
                run(adb, '-s', args.serial, 'shell', 'am', 'force-stop', package_name)
                result = run(adb, '-s', args.serial, 'shell', 'am', 'instrument', '-w', '-r', '-e', 'phase', phase,
                    '-e', 'session', session, package_name + '/com.baseer.freshchat.MuteIndexInstrumentation')
                (output / ('instrumentation-' + phase + '.log')).write_text(result, encoding='utf-8')
                print(result)
                if not re.search(r'PASS [1-9][0-9]* actual Android35 room mute assertions', result) or 'INSTRUMENTATION_CODE: 0' not in result:
                    raise SystemExit('Native component phase failed; raw/source evidence retained: ' + phase)
                raw = run(adb, '-s', args.serial, 'exec-out', 'run-as', package_name, 'cat', 'files/mute-results-' + phase + '-' + session + '.json')
                (output / ('results-' + phase + '.json')).write_text(raw, encoding='utf-8')
                item = json.loads(raw)
                if item.get('passed') is not True or item.get('phase') != phase or item.get('session') != session or item.get('sdk') != 35:
                    raise SystemExit('Native identity mismatch')
                if type(item.get('process_id')) is not int or item['process_id'] <= 0 or type(item.get('assertions')) is not int or item['assertions'] <= 0:
                    raise SystemExit('Native positive assertion/PID missing')
                evidence.append(item)
            if len({item['process_id'] for item in evidence}) != 4:
                raise SystemExit('Separate-process evidence missing')
            (output / 'native-evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'phases': evidence,
                'restart_cutpoints': 2, 'scope': 'Actual SDK35 shared Index cases + 3 production Controller/Port flows with queue/HTTP/auth fixtures; '
                'seed/newPID clear/newPID verify index only; not power-loss/Activity/FCM/HTTP integration'}, indent=2), encoding='utf-8')
    frozen()
