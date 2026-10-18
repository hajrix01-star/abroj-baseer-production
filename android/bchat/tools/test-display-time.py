#!/usr/bin/env python3
"""Archive/compile/test the actual pure display formatter, never panels or a device."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--label', required=True)
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', args.label):
    raise SystemExit('Fresh bounded evidence label required')
root = Path(__file__).resolve().parents[1]
repository = root.parents[1]
output = root / 'artifacts/display-time' / args.label
output.mkdir(parents=True, exist_ok=False)
classes = output / 'classes'
classes.mkdir()
files = [root / 'app/src/main/java/com/baseer/freshchat/BChatDisplayTime.java',
         root / 'tests/display-time/DisplayTimeTest.java', Path(__file__).resolve()]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

inputs = {}
for path in files:
    relative = path.relative_to(repository)
    raw = path.read_bytes()
    target = output / 'frozen-inputs' / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    inputs[relative.as_posix()] = hashlib.sha256(raw).hexdigest()

def frozen():
    if any(sha(repository / path) != expected or sha(output / 'frozen-inputs' / path) != expected for path, expected in inputs.items()):
        raise SystemExit('Live/archive inputs changed; no acceptance')

def jdk(name):
    configured = os.environ.get('JAVA_HOME')
    if configured:
        candidate = Path(configured) / 'bin' / (name + ('.exe' if os.name == 'nt' else ''))
        if candidate.is_file():
            return candidate
    candidate = shutil.which(name)
    if not candidate:
        raise SystemExit('Installed JDK17 required through JAVA_HOME/PATH')
    return Path(candidate)

def run(*command):
    result = subprocess.run(list(map(str, command)), text=True, encoding='utf-8', errors='replace', capture_output=True, timeout=45)
    with (output / 'raw.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit('Pure formatter compile/test failed; original raw retained')
    return result.stdout

manifest = {'source_sha256': inputs, 'scope': 'Actual pure production BChatDisplayTime + exact test, JDK17/Java8 target. Process-local Locale/TimeZone defaults only; no panel/native/wire-parser/auth/clock/zone-conversion acceptance.'}
(output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
frozen()
try:
    run(jdk('javac'), '--release', '8', '-encoding', 'UTF-8', '-d', classes,
        *[output / 'frozen-inputs' / path.relative_to(repository) for path in files if path.suffix == '.java'])
    frozen()
    raw = run(jdk('java'), '-cp', classes, 'com.baseer.freshchat.DisplayTimeTest')
finally:
    frozen()
matched = re.fullmatch(r'PASS (\d+) pure display-time checks;.*\s*', raw)
if not matched:
    raise SystemExit('Missing actual formatter check count')
(output / 'result.json').write_text(json.dumps({'passed': True, 'checks': int(matched.group(1)), 'stdout': raw}, indent=2), encoding='utf-8')
print(raw, end='')
