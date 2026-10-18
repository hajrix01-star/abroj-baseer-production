#!/usr/bin/env python3
"""C01 behavior: compile the production store with explicit JVM Android adapters.

Uses an already installed Gradle Gson jar for the test-only JSONObject API; never downloads,
installs, or adds a product dependency. AtomicFile adapter runs backup and .new protocols.
This is a real-files JVM test, not Android instrumentation or a phone performance claim.
--baseline-ref proves the unchanged isolation regression fails against the pre-fix source.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--baseline-ref')
parser.add_argument('--gson-jar', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
repository = root.parents[1]
java_root = root / 'app/src/main/java/com/baseer/freshchat/sync'
fixtures = root / 'tests/jvm-connected-media'
javac, java = shutil.which('javac'), shutil.which('java')
if not javac or not java:
    raise SystemExit('Existing JDK is required; no test dependencies are installed.')
candidates = [args.gson_jar]
if os.environ.get('BCHAT_TEST_GSON_JAR'):
    candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
if os.environ.get('GRADLE_HOME'):
    candidates.extend((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
candidates.extend(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
gradle = shutil.which('gradle')
if gradle:
    candidates.extend((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
gson = next((candidate.resolve() for candidate in candidates if candidate and candidate.is_file()), None)
if not gson:
    raise SystemExit('Pass --gson-jar with the existing Gradle lib/gson-*.jar; nothing is downloaded.')
adapters = list((root / 'tests/jvm-media/android').rglob('*.java'))
adapters += list((fixtures / 'android').rglob('*.java'))
adapters += list((fixtures / 'org').rglob('*.java'))
with tempfile.TemporaryDirectory(prefix='bchat-connected-media-store-') as temporary:
    folder = Path(temporary)
    store = java_root / 'BChatConnectedMediaStore.java'
    if args.baseline_ref:
        store = folder / 'BChatConnectedMediaStore.java'
        content = subprocess.check_output(['git', 'show', f'{args.baseline_ref}:android/bchat/app/src/main/java/com/baseer/freshchat/sync/BChatConnectedMediaStore.java'], cwd=repository)
        store.write_bytes(content)
        cases = [fixtures / 'ConnectedMediaIsolationRegression.java']
    else:
        cases = [fixtures / 'ConnectedMediaStoreTest.java', fixtures / 'ConnectedMediaIsolationRegression.java']
    subprocess.run([javac, '-encoding', 'UTF-8', '-cp', str(gson), '-d', str(folder),
                    *map(str, adapters), str(store), str(java_root / 'AccountScope.java'),
                    str(java_root / 'OutboxPolicy.java'), *map(str, cases)], check=True)
    classpath = os.pathsep.join([str(folder), str(gson)])
    result = subprocess.run([java, '-cp', classpath, 'com.baseer.freshchat.sync.ConnectedMediaIsolationRegression'],
                            capture_output=bool(args.baseline_ref), text=True)
    if args.baseline_ref:
        if result.returncode == 0 or 'Invalid media metadata' not in result.stderr:
            raise SystemExit(f'Baseline did not exhibit the expected corrupt-A/healthy-B failure:\n{result.stdout}\n{result.stderr}')
        print('PASS baseline production store reproduces IOException from corrupt A while requesting healthy B')
    else:
        result.check_returncode()
        subprocess.run([java, '-cp', classpath, 'com.baseer.freshchat.sync.ConnectedMediaStoreTest'], check=True)
