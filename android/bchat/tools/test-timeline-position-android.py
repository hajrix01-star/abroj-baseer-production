#!/usr/bin/env python3
"""Five isolated actual-Activity position groups; no benchmark or product build.

E85A remains untouched. Its test-only class declaration is the sole foundation
transformation; the final production Activity is copied without transformation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PACKAGE = 'com.baseer.bchat.timeline.position.test'
FOUNDATION_SHA = 'E85A5214286681C8E4C2FE004B1FF5781250C4B8C80976133C14463AE65421DE'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--label', required=True)
parser.add_argument('--base-commit', required=True)
parser.add_argument('--expected-activity-sha256', required=True)
parser.add_argument('--run-built', action='store_true')
parser.add_argument('--selection', choices=('all', 'cached-remaining', 'newer-remaining'), default='all')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Fresh bounded label required')
if not re.fullmatch(r'[0-9a-f]{40}', args.base_commit) or not re.fullmatch(r'[0-9a-fA-F]{64}', args.expected_activity_sha256):
    raise SystemExit('Explicit full Git base and reviewed Activity SHA256 required')
args.expected_activity_sha256 = args.expected_activity_sha256.upper()
all_cases = ['late-enqueue-then-known-present-jump', 'present-jump-before-layout-sendcapture',
             'late-enqueue-after-real-user-gesture', 'late-enqueue-with-actual-cached-older',
             'late-enqueue-with-actual-cached-newer', 'late-enqueue-after-actual-owner-invalidation']
selected_cases = (all_cases[-2:] if args.selection == 'newer-remaining' else
                  all_cases[-3:] if args.selection == 'cached-remaining' else all_cases)
root = Path(__file__).resolve().parents[1]
repo = root.parents[1]
tests = root / 'tests/timeline-position-android'
activity = root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java'
foundation = root / 'tests/timeline-hook-android/java/com/baseer/freshchat/TimelineHookInstrumentation.java'
output = root / 'artifacts/timeline-position-android' / args.label
project = output / 'project'
sdk = Path('D:/Codex/AndroidSdk')
gradle = Path('D:/Codex/tools/gradle-8.11.1/bin/gradle.bat')
signing = Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')
apk = output / 'BChat-standalone-timeline-position-tests.apk'
activity_name = activity.relative_to(repo).as_posix()


def digest(raw):
    return hashlib.sha256(raw).hexdigest().upper()


def sha(path):
    return digest(path.read_bytes())


def git(*command):
    return subprocess.check_output(['git', '-C', str(repo), *command])


def blob(name):
    return git('show', args.base_commit + ':' + name)


def run(*command, cwd=None, timeout=180):
    environment = os.environ.copy()
    environment['JAVA_HOME'] = 'C:/Program Files/Eclipse Adoptium/jdk-17.0.20.101-hotspot'
    environment['ANDROID_HOME'] = str(sdk)
    completed = subprocess.run(list(map(str, command)), cwd=cwd, env=environment, text=True,
                               encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)
    with (output / 'build-and-run.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + completed.stdout + completed.stderr)
    if completed.returncode:
        print((completed.stdout + completed.stderr)[-6000:])
        raise SystemExit('Build/native command failed; evidence retained, no acceptance')
    return completed.stdout


def copied_files():
    paths = [project / name for name in ('build.gradle', 'settings.gradle', 'gradle.properties', 'app/build.gradle')]
    for folder in (project / 'app/src', output / 'frozen-inputs'):
        paths.extend(path for path in folder.rglob('*') if path.is_file())
    return {path.relative_to(output).as_posix(): sha(path) for path in paths}


if not args.run_built:
    output.mkdir(parents=True, exist_ok=False)
    if git('rev-parse', args.base_commit).decode().strip() != args.base_commit:
        raise SystemExit('Base must be an existing exact commit')
    live_sources, compiled_sources, copied, captured = {}, {}, {}, {}

    def save(name, raw):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        copied[name] = digest(raw)

    for path in [activity, foundation, *sorted(path for path in tests.rglob('*') if path.is_file()), Path(__file__).resolve()]:
        raw = path.read_bytes()
        relative = path.relative_to(repo).as_posix()
        if path == activity and digest(raw) != args.expected_activity_sha256:
            raise SystemExit('Activity differs from reviewed source freeze')
        if path == foundation and digest(raw) != FOUNDATION_SHA:
            raise SystemExit('E85A foundation must remain exactly frozen')
        live_sources[relative] = digest(raw)
        captured[relative] = raw
        save('frozen-inputs/live/' + relative, raw)
    prefix = 'android/bchat/tests/performance-android/'
    for name in ('build.gradle', 'settings.gradle', 'gradle.properties'):
        relative = prefix + name
        raw = blob(relative)
        compiled_sources[relative] = digest(raw)
        save('frozen-inputs/base-git/' + relative, raw)
        save('project/' + name, raw)
    paths = git('ls-tree', '-r', '--name-only', args.base_commit, '--',
                'android/bchat/app/src/main/java', 'android/bchat/app/src/main/res').decode().splitlines()
    excluded = []
    for relative in paths:
        if Path(relative).name in ('BChatFirebaseMessagingService.java', 'BChatFirebaseTokenSource.java'):
            excluded.append(relative)
            continue
        if relative == activity_name:
            raw = captured[relative]
        else:
            raw = blob(relative)
            compiled_sources[relative] = digest(raw)
            save('frozen-inputs/base-git/' + relative, raw)
        save('project/app/src/main/' + relative.removeprefix('android/bchat/app/src/main/'), raw)
    wrapper = prefix + 'java/com/baseer/freshchat/CountingTimelineAdapter.java'
    raw = blob(wrapper)
    compiled_sources[wrapper] = digest(raw)
    save('frozen-inputs/base-git/' + wrapper, raw)
    save('project/app/src/main/java/com/baseer/freshchat/CountingTimelineAdapter.java', raw)
    # Test-only reusable fixture: exactly one declaration change, no method rewrite.
    declaration = b'public final class TimelineHookInstrumentation extends Instrumentation {'
    foundation_raw = captured[foundation.relative_to(repo).as_posix()]
    if foundation_raw.count(declaration) != 1:
        raise SystemExit('Exactly one frozen test foundation declaration expected')
    transformed = foundation_raw.replace(declaration, b'class TimelinePositionFixture extends Instrumentation {')
    save('project/app/src/main/java/com/baseer/freshchat/TimelinePositionFixture.java', transformed)
    for relative, raw in captured.items():
        test_prefix = 'android/bchat/tests/timeline-position-android/'
        if relative.startswith(test_prefix + 'java/'):
            save('project/app/src/main/java/' + relative.removeprefix(test_prefix + 'java/'), raw)
    manifest_relative = 'android/bchat/tests/timeline-position-android/AndroidManifest.xml'
    manifest_raw = captured[manifest_relative]
    if b'android.permission.INTERNET' in manifest_raw or b'android:supportsRtl="true"' not in manifest_raw:
        raise SystemExit('Isolation/RTL preflight refused')
    base_manifest = blob('android/bchat/app/src/main/AndroidManifest.xml')
    if b'android:supportsRtl="true"' not in base_manifest:
        raise SystemExit('Product RTL manifest no longer matches fixture')
    save('frozen-inputs/base-git/android/bchat/app/src/main/AndroidManifest.xml', base_manifest)
    save('project/app/src/main/AndroidManifest.xml', manifest_raw)
    template = captured['android/bchat/tests/timeline-position-android/app.gradle']
    if template.count(b'@BASE_COMMIT@') != 1 or template.count(b'@ACTIVITY_SHA@') != 1:
        raise SystemExit('Exactly two BuildConfig literal transformations required')
    save('project/app/build.gradle', template.replace(b'@BASE_COMMIT@', args.base_commit.encode())
         .replace(b'@ACTIVITY_SHA@', args.expected_activity_sha256.encode()))
    if copied_files() != copied:
        raise SystemExit('Copied snapshot contains extra/missing/changed files')
    manifest = {'schema': 1, 'base_commit': args.base_commit, 'activity_sha256': args.expected_activity_sha256,
                'selection': args.selection, 'selected_cases': selected_cases,
                'live_source_sha256': live_sources, 'base_git_source_sha256': compiled_sources,
                'copied_input_sha256': copied, 'excluded_sources': excluded,
                'foundation': {'original_sha256': FOUNDATION_SHA, 'compiled_sha256': digest(transformed),
                               'transformation': 'Exactly one test-only class declaration rename/non-final; every method byte unchanged'},
                'source_epochs': 'Only final target Activity and owned fixture are live captured; every other production Java/resource and AndroidX wrapper/template is exact explicit Git-base blob. No live Store/Controller/Port WIP.',
                'scope': f'Explicit {args.selection} selection, at most {len(selected_cases)} native cases; actual Activity/AndroidX/SQLite/owner/adapter/preDraw, synthetic identity/proofs. No HTTP/auth/FCM/ACK truth/benchmark/799 rerun.'}
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def build_frozen():
        if copied_files() != copied:
            raise SystemExit('Compiled/archive snapshot changed')
        for name, expected in live_sources.items():
            if sha(repo / name) != expected:
                raise SystemExit('Frozen target/harness changed: ' + name)

    build_frozen()
    try:
        run(gradle, ':app:assembleDebug', '--offline', '--no-daemon', '--console=plain', cwd=project, timeout=240)
    finally:
        build_frozen()
    unsigned = list((project / 'app/build/outputs/apk/debug').glob('*-unsigned.apk'))
    if len(unsigned) != 1:
        raise SystemExit('Exactly one unsigned standalone APK expected, no debug-key fallback')
    run(sdk / 'build-tools/35.0.0/apksigner.bat', 'sign', '--ks', signing / 'bchat-preview-fresh.p12',
        '--ks-key-alias', 'bchat-preview', '--ks-pass', 'file:' + str(signing / 'keystore.password'), '--out', apk, unsigned[0])
    run(sdk / 'build-tools/35.0.0/apksigner.bat', 'verify', apk)
    build_frozen()
    manifest['apk_sha256'] = sha(apk)
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Frozen separate position test build complete; no instrumentation run yet.')

manifest = json.loads((output / 'source-manifest.json').read_text(encoding='utf-8'))
manifest_hash = sha(output / 'source-manifest.json')
if (manifest['base_commit'] != args.base_commit or manifest['activity_sha256'] != args.expected_activity_sha256
        or manifest['selection'] != args.selection or manifest['selected_cases'] != selected_cases):
    raise SystemExit('run-built source arguments differ from compiled snapshot')


def frozen():
    if sha(output / 'source-manifest.json') != manifest_hash or copied_files() != manifest['copied_input_sha256']:
        raise SystemExit('Compiled/archive/manifest bytes changed')
    if sha(apk) != manifest['apk_sha256']:
        raise SystemExit('Standalone APK changed')
    for name, expected in manifest['live_source_sha256'].items():
        if sha(repo / name) != expected:
            raise SystemExit('Frozen Activity/fixture changed: ' + name)


frozen()
if args.run_built:
    adb = sdk / 'platform-tools/adb.exe'
    provenance = {'base_commit': args.base_commit, 'activity_sha256': args.expected_activity_sha256,
                  'selection': args.selection, 'selected_cases': selected_cases,
                  'manifest_sha256': manifest_hash, 'head_at_run_start': git('rev-parse', 'HEAD').decode().strip(),
                  'serial': 'emulator-5580', 'scope': manifest['scope']}
    (output / 'run-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    run(adb, '-s', 'emulator-5580', 'install', '-r', apk)
    run(adb, '-s', 'emulator-5580', 'shell', 'pm', 'clear', PACKAGE)
    frozen()
    try:
        raw = run(adb, '-s', 'emulator-5580', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'selection', args.selection,
                  PACKAGE + '/com.baseer.freshchat.TimelinePositionInstrumentation', timeout=180)
    finally:
        frozen()
    (output / 'instrumentation.log').write_text(raw, encoding='utf-8')
    evidence = subprocess.run([str(adb), '-s', 'emulator-5580', 'exec-out', 'run-as', PACKAGE,
                               'cat', 'files/timeline-position-results.json'], capture_output=True, timeout=20)
    if evidence.returncode:
        raise SystemExit('No native result; no acceptance invented')
    (output / 'timeline-position-results.json').write_bytes(evidence.stdout)
    native = json.loads(evidence.stdout)
    if native.get('selection') != args.selection or native.get('requested_case_names') != selected_cases:
        raise SystemExit('Native case selection differs; raw result retained, no acceptance')
    executions = native.get('case_execution_counts', [])
    if ([row.get('name') for row in executions] != selected_cases[:len(executions)]
            or len(executions) > len(selected_cases) or native.get('started_case_count') != len(executions)
            or native.get('completed_case_count') != sum(row.get('passed') is True for row in executions)):
        raise SystemExit('Native executed-case accounting inconsistent; no acceptance')
    if native.get('passed') and (len(executions) != len(selected_cases)
                                 or native.get('completed_case_count') != len(selected_cases)):
        raise SystemExit('Native success omitted selected cases; no acceptance')
    frozen()
    provenance['head_at_run_end'] = git('rev-parse', 'HEAD').decode().strip()
    provenance['started_case_count'] = native.get('started_case_count')
    provenance['completed_case_count'] = native.get('completed_case_count')
    (output / 'run-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(raw)
    if not native.get('passed') or 'INSTRUMENTATION_CODE: -1' not in raw:
        raise SystemExit('Position fixture failed; failure/raw/copies retained. Report before changes.')
    print('Separate position evidence retained; no benchmark/product-release acceptance.')
