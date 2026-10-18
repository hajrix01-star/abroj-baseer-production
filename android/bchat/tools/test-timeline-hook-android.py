#!/usr/bin/env python3
"""One isolated full-Activity C11 functional fixture, not a benchmark or product APK.

Explicit immutable Git base for dependencies/resources, plus one frozen live target Activity.
Never copies live Store/Controller/Port work. No network/dependency downloads/global device changes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

PACKAGE = 'com.baseer.bchat.timeline.hook.test'
parser = argparse.ArgumentParser()
parser.add_argument('--label', required=True)
parser.add_argument('--base-commit', required=True)
parser.add_argument('--expected-activity-sha256', required=True)
parser.add_argument('--run-built', action='store_true')
parser.add_argument('--case', dest='test_case', choices=('functional', 'send-visibility', 'pending-layout'), default='functional')
args = parser.parse_args()
if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
    raise SystemExit('Fresh bounded label required')
if not re.fullmatch(r'[0-9a-f]{40}', args.base_commit) or not re.fullmatch(r'[0-9a-fA-F]{64}', args.expected_activity_sha256):
    raise SystemExit('Explicit full Git base and target Activity SHA256 required')
args.expected_activity_sha256 = args.expected_activity_sha256.upper()
root = Path(__file__).resolve().parents[1]
repo = root.parents[1]
tests = root / 'tests/timeline-hook-android'
activity = root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java'
output = root / 'artifacts/timeline-hook-android' / args.label
project = output / 'project'
sdk = Path('D:/Codex/AndroidSdk')
gradle = Path('D:/Codex/tools/gradle-8.11.1/bin/gradle.bat')
signing = Path('C:/Users/hp/AppData/Local/Baseer/BChatSigning/fresh-install-20261009')
apk = output / 'BChat-standalone-timeline-hook-tests.apk'
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
    result = subprocess.run(list(map(str, command)), cwd=cwd, env=environment, text=True,
                            encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)
    with (output / 'build-and-run.log').open('a', encoding='utf-8') as log:
        log.write(Path(str(command[0])).name + '\n' + result.stdout + result.stderr)
    if result.returncode:
        print((result.stdout + result.stderr)[-6000:])
        raise SystemExit('Build/native command failed; raw evidence retained, no acceptance')
    return result.stdout


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

    # One capture of each owned live input; source generation never re-reads a live alias.
    for path in [activity, *sorted(path for path in tests.rglob('*') if path.is_file()), Path(__file__).resolve()]:
        raw = path.read_bytes()
        relative = path.relative_to(repo).as_posix()
        if path == activity and digest(raw) != args.expected_activity_sha256:
            raise SystemExit('Target Activity differs from reviewed freeze')
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
    for relative, raw in captured.items():
        test_prefix = 'android/bchat/tests/timeline-hook-android/'
        if relative.startswith(test_prefix + 'java/'):
            save('project/app/src/main/java/' + relative.removeprefix(test_prefix + 'java/'), raw)
    manifest_relative = 'android/bchat/tests/timeline-hook-android/AndroidManifest.xml'
    manifest_raw = captured[manifest_relative]
    if b'android.permission.INTERNET' in manifest_raw or b'android:supportsRtl="true"' not in manifest_raw:
        raise SystemExit('Isolation/RTL preflight rejected')
    base_manifest = blob('android/bchat/app/src/main/AndroidManifest.xml')
    if b'android:supportsRtl="true"' not in base_manifest:
        raise SystemExit('RTL fixture no longer matches product manifest')
    save('frozen-inputs/base-git/android/bchat/app/src/main/AndroidManifest.xml', base_manifest)
    save('project/app/src/main/AndroidManifest.xml', manifest_raw)
    template = captured['android/bchat/tests/timeline-hook-android/app.gradle']
    if template.count(b'@BASE_COMMIT@') != 1 or template.count(b'@ACTIVITY_SHA@') != 1:
        raise SystemExit('Expected exactly two declared BuildConfig transformations')
    save('project/app/build.gradle', template.replace(b'@BASE_COMMIT@', args.base_commit.encode())
         .replace(b'@ACTIVITY_SHA@', args.expected_activity_sha256.encode()))
    # Explicit source-body reuse inventory; no native inflight/media proof is fabricated.
    extractor = root / 'tools/test-room-explore-hook.py'
    extractor_raw = extractor.read_bytes()
    relative = extractor.relative_to(repo).as_posix()
    live_sources[relative] = digest(extractor_raw)
    save('frozen-inputs/live/' + relative, extractor_raw)
    extraction = {'__name__': 'declared_hook_extractor', '__file__': str(extractor)}
    exec(compile(extractor_raw, str(extractor), 'exec'), extraction)
    media = {}
    base_activity = blob(activity_name).decode('utf-8')
    for marker in ('private void pumpMediaThumbnails(', 'private void toggleInlineAudio(',
                   'private void showMeasuredAudioWave(', 'private void stopInlineAudio(',
                   'private void detachAudioControls('):
        previous, _ = extraction['fragment'](base_activity, marker)
        current, _ = extraction['fragment'](captured[activity_name].decode('utf-8'), marker)
        media[marker] = {'base_body_sha256': digest(previous.encode()), 'target_body_sha256': digest(current.encode()),
                         'equal_ignoring_only_CRLF': previous.replace('\r\n', '\n') == current.replace('\r\n', '\n')}
    if not all(row['equal_ignoring_only_CRLF'] for row in media.values()):
        raise SystemExit('Media callback source changed; stop and report the new test gap')
    if copied_files() != copied:
        raise SystemExit('Copied snapshot/extra file mismatch')
    manifest = {'schema': 1, 'base_commit': args.base_commit, 'activity_sha256': args.expected_activity_sha256, 'selected_case': args.test_case,
                'live_source_sha256': live_sources, 'base_git_source_sha256': compiled_sources,
                'copied_input_sha256': copied, 'excluded_sources': excluded,
                'media_body_inventory': media,
                'source_epochs': 'Only target Activity is live reviewed bytes; all other production Java/resources and transparent wrapper/templates are exact explicit Git-base blobs. No live Store/Controller/Port WIP.',
                'scope': ('Two AR/EN dark/font2 actual <=320dp full Activity pending-layout configurations; native TextView.Layout/touch/overlap/message-viewport geometry, synthetic reflected identity/view route, real SQLite current/stale entries, explicitly synthetic media metadata only. No button clicks/auth/HTTP/FCM/send/benchmark claim.'
                          if args.test_case == 'pending-layout' else 'One functional full Activity/AndroidX/SQLite fixture; synthetic identity/proofs, no auth/HTTP/FCM/benchmark/codec/inflight/audio-playing claim')}
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')

    def build_frozen():
        if copied_files() != copied:
            raise SystemExit('Copied compile/archive bytes changed')
        for name, expected in live_sources.items():
            if sha(repo / name) != expected:
                raise SystemExit('Live frozen target/harness changed: ' + name)

    build_frozen()
    try:
        run(gradle, ':app:assembleDebug', '--offline', '--no-daemon', '--console=plain', cwd=project, timeout=240)
    finally:
        build_frozen()
    unsigned = list((project / 'app/build/outputs/apk/debug').glob('*-unsigned.apk'))
    if len(unsigned) != 1:
        raise SystemExit('Exactly one unsigned standalone APK expected, no debug-key fallback')
    run(sdk / 'build-tools/35.0.0/apksigner.bat', 'sign', '--ks', signing / 'bchat-preview-fresh.p12',
        '--ks-key-alias', 'bchat-preview', '--ks-pass', 'file:' + str(signing / 'keystore.password'),
        '--out', apk, unsigned[0])
    run(sdk / 'build-tools/35.0.0/apksigner.bat', 'verify', apk)
    build_frozen()
    manifest['apk_sha256'] = sha(apk)
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Frozen isolated functional test build complete; no instrumentation run yet.')

manifest = json.loads((output / 'source-manifest.json').read_text(encoding='utf-8'))
manifest_hash = sha(output / 'source-manifest.json')
if manifest['base_commit'] != args.base_commit or manifest['activity_sha256'] != args.expected_activity_sha256 or manifest['selected_case'] != args.test_case:
    raise SystemExit('run-built source arguments differ from compiled snapshot')


def frozen():
    if sha(output / 'source-manifest.json') != manifest_hash or copied_files() != manifest['copied_input_sha256']:
        raise SystemExit('Compiled source/archive/manifest changed')
    if sha(apk) != manifest['apk_sha256']:
        raise SystemExit('Standalone APK changed')
    for name, expected in manifest['live_source_sha256'].items():
        if sha(repo / name) != expected:
            raise SystemExit('Frozen Activity/harness changed: ' + name)


frozen()
if args.run_built:
    adb = sdk / 'platform-tools/adb.exe'
    provenance = {'base_commit': args.base_commit, 'activity_sha256': args.expected_activity_sha256,
                  'selected_case': args.test_case,
                  'manifest_sha256': manifest_hash, 'head_at_run_start': git('rev-parse', 'HEAD').decode().strip(),
                  'serial': 'emulator-5580', 'scope': manifest['scope']}
    (output / 'run-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    run(adb, '-s', 'emulator-5580', 'install', '-r', apk)
    run(adb, '-s', 'emulator-5580', 'shell', 'pm', 'clear', PACKAGE)
    frozen()
    try:
        raw = run(adb, '-s', 'emulator-5580', 'shell', 'am', 'instrument', '-w', '-r', '-e', 'case', args.test_case,
                  PACKAGE + '/com.baseer.freshchat.TimelineHookInstrumentation', timeout=180)
    finally:
        frozen()
    (output / 'instrumentation.log').write_text(raw, encoding='utf-8')
    evidence = subprocess.run([str(adb), '-s', 'emulator-5580', 'exec-out', 'run-as', PACKAGE,
                               'cat', 'files/timeline-hook-results.json'], capture_output=True, timeout=20)
    if evidence.returncode:
        raise SystemExit('No native result; no acceptance manufactured')
    (output / 'timeline-hook-results.json').write_bytes(evidence.stdout)
    native = json.loads(evidence.stdout)
    images = (('timeline-pending-layout-ar.png', 'timeline-pending-layout-en.png') if args.test_case == 'pending-layout'
              else ('timeline-send-visibility.png',) if args.test_case == 'send-visibility'
              else ('timeline-ar-dark-font2-anchor.png', 'timeline-ar-dark-font2-media.png'))
    for name in images:
        image = subprocess.run([str(adb), '-s', 'emulator-5580', 'exec-out', 'run-as', PACKAGE,
                                'cat', 'files/' + name], capture_output=True, timeout=15)
        if image.returncode == 0:
            (output / name).write_bytes(image.stdout)
    frozen()
    provenance['head_at_run_end'] = git('rev-parse', 'HEAD').decode().strip()
    (output / 'run-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(raw)
    if not native.get('passed') or 'INSTRUMENTATION_CODE: -1' not in raw:
        raise SystemExit('Functional fixture failed; failure/raw/copies preserved. Report before changes.')
    print('Functional evidence retained for independent review; no benchmark/product-release claim.')
