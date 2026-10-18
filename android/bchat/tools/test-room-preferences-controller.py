#!/usr/bin/env python3
"""C17 controller-only ordering tests using production Store/Protocol and real JVM files.

Reuses the declared Store test API/Gson adapters, not Android JSON or real HTTP. No dependency
download, emulator, product APK, auth/bootstrap, Activity, notifications, FCM or CI mutation.
Every new run archives actual compiled inputs and this tool before compilation.
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


def discover_gson(explicit):
    """Resolve only existing test runtime jars. Never override an explicit missing path."""
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit('Explicit --gson-jar is missing; no fallback/download allowed')
        return explicit.resolve(), 'explicit'
    candidates = []
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        candidates.append((Path(os.environ['BCHAT_TEST_GSON_JAR']), 'BCHAT_TEST_GSON_JAR'))
    if os.environ.get('GRADLE_HOME'):
        candidates += [(path, 'GRADLE_HOME') for path in sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))]
    gradle = shutil.which('gradle')
    if gradle:
        candidates += [(path, 'gradle_PATH') for path in sorted((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))]
    candidates += [(path, 'known_Windows_runtime') for path in sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))]
    for path, origin in candidates:
        if path.is_file():
            return path.resolve(), origin
    raise SystemExit('Existing Gson adapter dependency required; nothing downloaded')


parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--case', choices=('all', 'ack-proof', 'recovery'), default='all')
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path, help='Optional existing SDK35 stub compilation only, NOT Android execution')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Bounded fresh evidence label required')
gson, gson_origin = discover_gson(args.gson_jar)
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
tests = root / 'tests/room-preferences-controller'
adapters = root / 'tests/room-preferences-store/jvm'
production = [source / name for name in ('RoomPreferencesController.java', 'RoomPreferencesStore.java',
    'RoomPreferencesProtocol.java', 'sync/AccountScope.java', 'sync/OutboxPolicy.java')]
adapter_inputs = [path for path in adapters.rglob('*.java') if 'com/baseer/' not in path.as_posix()]
java_inputs = production + sorted(adapter_inputs) + sorted(tests.rglob('*.java'))
inputs = java_inputs + [Path(__file__).resolve()]
output = root / 'artifacts/room-preferences-controller' / args.label
output.mkdir(parents=True, exist_ok=False)
archive = output / 'inputs'
hashes = {}
for path in inputs:
    name, raw = path.relative_to(root).as_posix(), path.read_bytes()
    target = archive / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[name] = hashlib.sha256(raw).hexdigest()
scope = ('Production Controller/Store/Protocol, actual JVM files; declared deterministic scheduler, '
         'transport and Android Context/Looper/AtomicFile/Gson-JSON adapters; no real HTTP/Android/Activity/FCM')
if args.android_jar and not args.android_jar.is_file():
    raise SystemExit('Existing SDK35 android.jar required')
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope, 'case': args.case,
    'archived_inputs': 'inputs', 'compiled_from_archived_inputs': True, 'source_sha256': hashes,
    'android_stub_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None,
    'adapter_gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest(),
    'gson_discovery_origin': gson_origin}, indent=2), encoding='utf-8')


def frozen():
    for path in inputs:
        name = path.relative_to(root).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name] or hashlib.sha256((archive / name).read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Live or archived input changed: ' + name)


def run(*command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=90)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit('Controller test build/run failed; original evidence retained')
    return result.stdout


frozen()
with tempfile.TemporaryDirectory(prefix='controller-', dir=output) as folder:
    classes, files = Path(folder) / 'classes', Path(folder) / 'owned-files'
    classes.mkdir(); files.mkdir()
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        raise SystemExit('Existing JDK required')
    run(javac, '-encoding', 'UTF-8', '-cp', gson, '-d', classes,
        *(archive / path.relative_to(root) for path in java_inputs))
    result = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), 'com.baseer.freshchat.ControllerCases', files, args.case)
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production RoomPreferencesController assertions', result)
    if not match:
        raise SystemExit('Missing positive assertion evidence')
    if args.android_jar:
        android_classes = Path(folder) / 'android35-stub-classes'
        android_classes.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
            '-cp', args.android_jar, '-d', android_classes,
            *(archive / path.relative_to(root) for path in production))
    frozen()
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'case': args.case,
        'assertions': int(match.group(1)), 'source_inputs': len(inputs), 'scope': scope,
        'android35_stub_compile_only': bool(args.android_jar),
        'source_before_after_equal': True, 'archived_before_after_equal': True}, indent=2), encoding='utf-8')
    print(result, end='')
