#!/usr/bin/env python3
"""C18/C19 Protocol only: production Java with existing explicit Gson-JSON JVM adapters.
Archives actual source/harness/tool bytes before compiling them. No download, auth, HTTP,
storage, native JSON run, emulator, Panel/Activity/product APK, notification, FCM or CI edits.
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
            raise SystemExit('Explicit Gson path missing; no fallback/download')
        return explicit.resolve()
    candidates = []
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
    if os.environ.get('GRADLE_HOME'):
        candidates += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
    executable = shutil.which('gradle')
    if executable:
        candidates += sorted((Path(executable).resolve().parents[1] / 'lib').glob('gson-*.jar'))
    candidates += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
    found = next((path.resolve() for path in candidates if path.is_file()), None)
    if found is None:
        raise SystemExit('Existing Gson test runtime required; nothing downloaded')
    return found


parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--gson-jar', type=Path)
parser.add_argument('--android-jar', type=Path, help='Optional existing SDK35 stub compile only, NOT native execution')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Bounded fresh evidence label required')
if args.android_jar and not args.android_jar.is_file():
    raise SystemExit('Existing Android stub jar required')
gson = gson_file(args.gson_jar)
root = Path(__file__).resolve().parents[1]
production = root / 'app/src/main/java/com/baseer/freshchat/GroupPeopleProtocol.java'
tests = sorted((root / 'tests/group-people-protocol').rglob('*.java'))
adapters = sorted((root / 'tests/room-preferences-store/jvm/org/json').glob('*.java'))
inputs = [production] + tests + adapters + [Path(__file__).resolve()]
output = root / 'artifacts/group-people-protocol' / args.label
output.mkdir(parents=True, exist_ok=False)
archive = output / 'inputs'
hashes = {}
for path in inputs:
    name, raw = path.relative_to(root).as_posix(), path.read_bytes()
    target = archive / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[name] = hashlib.sha256(raw).hexdigest()
scope = ('Production GroupPeopleProtocol, semantic JSONObject/JSONArray fixtures using existing declared Gson-backed JVM adapters; '
         'no native JSON/HTTP/auth/storage/Panel/Activity/FCM/device claim')
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
                            encoding='utf-8', errors='replace', timeout=90)
    with (output / 'build.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit('Protocol build/run failed; source/log evidence preserved')
    return result.stdout


frozen()
with tempfile.TemporaryDirectory(prefix='people-protocol-', dir=output) as folder:
    classes = Path(folder) / 'classes'
    classes.mkdir()
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        raise SystemExit('Existing JDK required')
    run(javac, '-encoding', 'UTF-8', '-cp', gson, '-d', classes,
        *(archive / path.relative_to(root) for path in inputs if path.suffix == '.java'))
    result = run(java, '-cp', os.pathsep.join([str(classes), str(gson)]), 'com.baseer.freshchat.GroupPeopleProtocolTest')
    (output / 'jvm.log').write_text(result, encoding='utf-8')
    match = re.search(r'^PASS ([1-9][0-9]*) production GroupPeopleProtocol assertions', result)
    if not match:
        raise SystemExit('Missing positive protocol evidence')
    if args.android_jar:
        stubs = Path(folder) / 'android35-stub-classes'
        stubs.mkdir()
        run(javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options', '-cp', args.android_jar,
            '-d', stubs, archive / production.relative_to(root))
    frozen()
    (output / 'evidence.json').write_text(json.dumps({'schema': 1, 'passed': True, 'scope': scope,
        'assertions': int(match.group(1)), 'source_inputs': len(inputs), 'source_archive_before_after_equal': True,
        'android35_stub_compile_only': bool(args.android_jar)}, indent=2), encoding='utf-8')
    print(result, end='')
