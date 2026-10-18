#!/usr/bin/env python3
"""Room-search DTO tests: actual protocol, JVM JSON adapters, declared constants-only media shim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--gson-jar', type=Path)
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Fresh bounded evidence label required')
root = Path(__file__).resolve().parents[1]
java = root / 'app/src/main/java/com/baseer/freshchat'
tests = root / 'tests/room-explore'
adapters = root / 'tests/room-preferences-store/jvm/org/json'
output = root / 'artifacts/room-explore' / args.label
output.mkdir(parents=True, exist_ok=False)
gson_candidates = []
if args.gson_jar is not None:
    if not args.gson_jar.is_file():
        raise SystemExit('Explicit Gson path missing; no fallback/download')
    gson_candidates = [args.gson_jar]
else:
    if os.environ.get('BCHAT_TEST_GSON_JAR'):
        gson_candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
    if os.environ.get('GRADLE_HOME'):
        gson_candidates += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
    gradle = shutil.which('gradle')
    if gradle:
        gson_candidates += sorted((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
    gson_candidates += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
gson = next((path.resolve() for path in gson_candidates if path.is_file()), None)
if gson is None:
    raise SystemExit('Existing test-only Gson dependency required; no download')
java_home = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else None
suffix = '.exe' if os.name == 'nt' else ''
javac = java_home / 'bin' / ('javac' + suffix) if java_home else shutil.which('javac')
jvm = java_home / 'bin' / ('java' + suffix) if java_home else shutil.which('java')
if not javac or not jvm:
    raise SystemExit('Existing JDK17 required')
actual = [java / 'RoomExploreProtocol.java', java / 'ReplyWireContract.java',
          java / 'sync/OutboxPolicy.java', java / 'sync/AccountScope.java']
media_source = java / 'sync/BChatConnectedMediaStore.java'
inputs = actual + sorted(adapters.glob('*.java')) + sorted(tests.rglob('*.java')) + [media_source, Path(__file__).resolve()]
archive, project, classes = output / 'inputs', output / 'project', output / 'classes'
hashes, compiled = {}, []
for path in inputs:
    relative = path.relative_to(root)
    raw = path.read_bytes()
    target = archive / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    hashes[relative.as_posix()] = hashlib.sha256(raw).hexdigest()
    if path.suffix == '.java' and path != media_source:
        destination = project / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        compiled.append(destination)
# Protocol only references compile-time limits, not a storage operation. Generate this
# explicitly declared test adapter from the actual owner's literal multiplication values.
constants = []
for name in ('IMAGE_LIMIT', 'AUDIO_LIMIT', 'PDF_LIMIT'):
    matches = re.findall(r'public static final int ' + name + r' = ([0-9* ]+);', media_source.read_text(encoding='utf-8'))
    if len(matches) != 1:
        raise SystemExit('Media constant shape changed; update the declared adapter deliberately')
    value = 1
    for factor in matches[0].split('*'):
        value *= int(factor.strip())
    constants.append(f'public static final int {name} = {value};')
shim = project / 'constants/BChatConnectedMediaStore.java'
shim.parent.mkdir(parents=True)
shim.write_text('package com.baseer.freshchat.sync; public final class BChatConnectedMediaStore {'
                + ''.join(constants) + '}\n', encoding='utf-8')
compiled.append(shim)
compiled_hashes = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in compiled}
manifest = {'scope': 'Actual RoomExploreProtocol/ReplyWireContract/OutboxPolicy on JVM with Gson JSONObject adapters; '
                     'media-limit constants adapter generated from actual owner source, not storage execution; '
                     'no Android/Activity/HTTP/rights proof or UI acceptance',
            'source_sha256': hashes, 'compiled_sha256': compiled_hashes,
            'gson_sha256': hashlib.sha256(gson.read_bytes()).hexdigest()}
(output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

def frozen():
    for name, digest in hashes.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest or hashlib.sha256((archive / name).read_bytes()).hexdigest() != digest:
            raise SystemExit('Live/archived input changed: ' + name)
    for name, digest in compiled_hashes.items():
        if hashlib.sha256((output / name).read_bytes()).hexdigest() != digest:
            raise SystemExit('Compiled copy changed: ' + name)

def run(command):
    result = subprocess.run([str(value) for value in command], text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=90)
    with (output / 'test.log').open('a', encoding='utf-8') as log:
        log.write(result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit('Room explore test failed; evidence preserved')
    return result.stdout

frozen()
classes.mkdir()
run([javac, '-encoding', 'UTF-8', '-cp', gson, '-d', classes, *compiled])
result = run([jvm, '-cp', os.pathsep.join((str(classes), str(gson))), 'com.baseer.freshchat.RoomExploreCases'])
frozen()
print(result.strip())
