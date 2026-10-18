#!/usr/bin/env python3
"""DEV148: actual production PushState+Owner/Port/Index, eight focused JVM families.
Existing routing Android/preferences/queue templates + Store AtomicFile/Gson-JSON adapters,
actual private JVM index files. SDK35 stub compile only, never Gradle/ADB/native/auth/FCM.
Archives actual generated adapter/source/tool bytes before compiling those frozen inputs.
"""
from pathlib import Path
import argparse
import ast
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
            raise SystemExit('Explicit Gson missing; no fallback')
        return explicit.resolve()
    paths = []
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        paths.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
    if os.environ.get('GRADLE_HOME'):
        paths += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
    gradle = shutil.which('gradle')
    if gradle:
        paths += sorted((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
    paths += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
    found = next((path.resolve() for path in paths if path.is_file()), None)
    if found is None:
        raise SystemExit('Existing Gson test runtime required; no downloads')
    return found


parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--case', choices=('all', 'factory-reconcile', 'health-post'), default='all')
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path, help='Optional existing SDK35 stub only')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Fresh bounded label required')
if args.android_jar and not args.android_jar.is_file():
    raise SystemExit('Explicit SDK stub missing; no silent skip')
gson = gson_file(args.gson_jar)
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat'
routing_tool = root / 'tools/test-push-routing-state.py'
# Only literal test templates are read, not execution/import of the legacy suite.
module = ast.parse(routing_tool.read_text(encoding='utf-8'))
templates = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign)
                 and any(isinstance(name, ast.Name) and name.id == 'files' for name in node.targets))
generated = {name: text for name, text in templates.items() if name != 'android/os/Handler.java' and name.startswith('android/')}
production = [source / name for name in ('BChatPushState.java', 'BChatRoomPreferencesOwner.java',
    'BChatRoomMuteIndex.java', 'BChatRoomMutePort.java', 'RoomPreferencesController.java',
    'RoomPreferencesStore.java', 'RoomPreferencesProtocol.java', 'NotificationPresentation.java',
    'BChatNotificationConversations.java', 'BChatNotificationPresentationReset.java',
    'sync/AccountScope.java', 'sync/OutboxPolicy.java')]
tests = root / 'tests/push-room-owner'
adapter_root = root / 'tests/room-preferences-store/jvm'
java_inputs = production + sorted(tests.rglob('*.java')) + [adapter_root / name for name in
    ('android/util/AtomicFile.java', 'org/json/JSONArray.java', 'org/json/JSONException.java')]
stub_only = [source / 'sync/BChatStorageRepository.java']
inputs = java_inputs + stub_only + [routing_tool, Path(__file__).resolve()]
output = root / 'artifacts/push-room-owner' / args.label
output.mkdir(parents=True, exist_ok=False)
archive = output / 'inputs'
hashes, generated_hashes = {}, {}
for path in inputs:
    name, raw = path.relative_to(root).as_posix(), path.read_bytes()
    target = archive / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[name] = hashlib.sha256(raw).hexdigest()
for name, raw in generated.items():
    target = archive / 'generated-adapters' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw.encode('utf-8'))
    generated_hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
scope = ('Production State/Owner/Port/Index, real private JVM index files; explicit existing '
         'Android/preferences/Handler/repository-queue/AtomicFile/Gson-JSON/reflection adapters; '
         'SDK35 stub compile only, no Android/auth/HTTP/FCM/Activity/power-loss claim')
head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, capture_output=True, text=True, check=True).stdout.strip()
(output / 'source-manifest.json').write_text(json.dumps({'schema': 1, 'scope': scope, 'git_head_at_freeze': head,
    'case': args.case, 'archived_inputs': 'inputs', 'compiled_from_archived_inputs': True, 'source_sha256': hashes,
    'generated_adapter_sha256': generated_hashes, 'adapter_gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest(),
    'android_stub_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None}, indent=2), encoding='utf-8')


def frozen():
    for path in inputs:
        name = path.relative_to(root).as_posix()
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashes[name] or hashlib.sha256((archive / name).read_bytes()).hexdigest() != hashes[name]:
            raise SystemExit('Live/archive input changed: ' + name)
    for name, expected in generated_hashes.items():
        if hashlib.sha256((archive / 'generated-adapters' / name).read_bytes()).hexdigest() != expected:
            raise SystemExit('Compiled adapter changed: ' + name)


def run(*command):
    result = subprocess.run([str(item) for item in command], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=120)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-8000:])
        raise SystemExit('Push room Owner failed; actual archived inputs/raw logs retained')
    return result.stdout


frozen()
javac, java = shutil.which('javac'), shutil.which('java')
if not javac or not java:
    raise SystemExit('Existing JDK required')
run(javac, '-version')
files = output / 'private-files'
files.mkdir()
with tempfile.TemporaryDirectory(prefix='push-owner-compile-', dir=output) as directory:
    classes = Path(directory) / 'classes'
    classes.mkdir()
    compile_inputs = [archive / path.relative_to(root) for path in java_inputs]
    compile_inputs += sorted((archive / 'generated-adapters').rglob('*.java'))
    run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', gson, '-d', classes, *compile_inputs)
    raw = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), 'com.baseer.freshchat.PushOwnerCases', files, args.case)
    (output / 'jvm.log').write_text(raw, encoding='utf-8')
    expected_families = 8 if args.case == 'all' else 1
    match = re.search(r'^PASS ([1-9][0-9]*) production PushState room Owner assertions; ' + str(expected_families) + r' focused families$', raw, re.M)
    rows = re.findall(r'^FAMILY ([a-z0-9-]+) PASS ([1-9][0-9]*)$', raw, re.M)
    if not match or len(rows) != expected_families or len({name for name, _ in rows}) != expected_families:
        raise SystemExit('Missing selected family evidence')
    counts = {name: int(count) for name, count in rows}
    result = json.loads((files / 'push-owner-results.json').read_text(encoding='utf-8'))
    if sum(counts.values()) != int(match.group(1)) or counts != result['families'] or result['assertions'] != int(match.group(1)):
        raise SystemExit('Raw/result inventory mismatch')
    if args.android_jar:
        stub = Path(directory) / 'sdk35-stub-classes'
        stub.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', args.android_jar,
            '-d', stub, *(archive / path.relative_to(root) for path in production + stub_only))
    frozen()
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'scope': scope,
        'case': args.case, 'assertions': int(match.group(1)), 'families': counts, 'source_inputs': len(inputs),
        'generated_adapters': len(generated_hashes), 'source_archive_before_after_equal': True,
        'android35_stub_compile_only': bool(args.android_jar)}, indent=2), encoding='utf-8')
    print(raw, end='')
