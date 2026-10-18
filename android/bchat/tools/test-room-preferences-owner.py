#!/usr/bin/env python3
"""DEV140/141: nine focused RAM Owner families with production Port/Index and real JVM
private files, existing Android/AtomicFile/Gson-JSON adapters and deterministic queue.
Optional SDK35 stub compile ONLY. No Gradle/ADB/native/runtime/network/download or product APK.
Archives actual source/harness/tool bytes BEFORE compilation; never overwrites earlier evidence.
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


def gson_file(explicit):
    if explicit is not None:
        if not explicit.is_file():
            raise SystemExit('Explicit Gson path missing; no fallback')
        return explicit.resolve()
    candidates = []
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
    if os.environ.get('GRADLE_HOME'):
        candidates += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
    gradle = shutil.which('gradle')
    if gradle:
        candidates += sorted((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
    candidates += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
    found = next((path.resolve() for path in candidates if path.is_file()), None)
    if found is None:
        raise SystemExit('Existing Gson test runtime required; nothing downloaded')
    return found


parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path, help='Optional existing SDK35 stub, never Android execution')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Fresh bounded evidence label required')
if args.android_jar and not args.android_jar.is_file():
    raise SystemExit('Explicit Android stub missing; no download or silent skip')
gson = gson_file(args.gson_jar)
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
production = [source / name for name in ('BChatRoomPreferencesOwner.java', 'BChatRoomMuteIndex.java',
    'BChatRoomMutePort.java', 'RoomPreferencesController.java', 'RoomPreferencesStore.java',
    'RoomPreferencesProtocol.java', 'NotificationPresentation.java', 'sync/AccountScope.java', 'sync/OutboxPolicy.java')]
adapters = sorted(path for path in (root / 'tests/room-preferences-store/jvm').rglob('*.java')
                  if 'com/baseer/' not in path.as_posix())
cases = sorted((root / 'tests/room-preferences-owner').rglob('*.java'))
java_inputs = production + adapters + cases
inputs = java_inputs + [Path(__file__).resolve()]
output = root / 'artifacts/room-preferences-owner' / args.label
output.mkdir(parents=True, exist_ok=False)
archive = output / 'inputs'
hashes = {}
for path in inputs:
    name, raw = path.relative_to(root).as_posix(), path.read_bytes()
    target = archive / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[name] = hashlib.sha256(raw).hexdigest()
scope = ('Production RAM Owner/Port/Index and actual JVM private files; explicit existing '
         'Context/Looper/AtomicFile/Gson-JSON/queue/private-ticket-reflection fixtures; '
         'SDK35 stub compile only, no Android/auth/HTTP/FCM/wiring/power-loss claim')
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope,
    'archived_inputs': 'inputs', 'compiled_from_archived_inputs': True, 'source_sha256': hashes,
    'adapter_gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest(),
    'android_stub_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None}, indent=2), encoding='utf-8')


def frozen():
    for path in inputs:
        name = path.relative_to(root).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name] or hashlib.sha256((archive / name).read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Live/archive input changed: ' + name)


def run(*command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-7000:])
        raise SystemExit('Owner component failed; exact source/raw logs retained')
    return result.stdout


frozen()
javac, java = shutil.which('javac'), shutil.which('java')
if not javac or not java:
    raise SystemExit('Existing JDK required')
run(javac, '-version')
files = output / 'private-files'
files.mkdir()
with tempfile.TemporaryDirectory(prefix='owner-compile-', dir=output) as directory:
    classes = Path(directory) / 'classes'
    classes.mkdir()
    run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', gson,
        '-d', classes, *(archive / path.relative_to(root) for path in java_inputs))
    raw = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), 'com.baseer.freshchat.OwnerCases', files)
    (output / 'jvm.log').write_text(raw, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production room preferences Owner assertions; 9 focused families$', raw, re.M)
    family_rows = re.findall(r'^FAMILY ([a-z0-9-]+) PASS ([1-9][0-9]*)$', raw, re.M)
    if not match or len(family_rows) != 9 or len({name for name, _ in family_rows}) != 9:
        raise SystemExit('Incomplete focused family evidence')
    result = json.loads((files / 'owner-results.json').read_text(encoding='utf-8'))
    families = {name: int(count) for name, count in family_rows}
    if sum(families.values()) != int(match.group(1)) or result['assertions'] != int(match.group(1)) or result['families'] != families:
        raise SystemExit('Raw family/result count mismatch')
    if args.android_jar:
        stub_classes = Path(directory) / 'android35-stub-classes'
        stub_classes.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', args.android_jar,
            '-d', stub_classes, *(archive / path.relative_to(root) for path in production))
    frozen()
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'scope': scope,
        'assertions': int(match.group(1)), 'families': families, 'source_inputs': len(inputs),
        'source_archive_before_after_equal': True, 'android35_stub_compile_only': bool(args.android_jar)}, indent=2), encoding='utf-8')
    print(raw, end='')
