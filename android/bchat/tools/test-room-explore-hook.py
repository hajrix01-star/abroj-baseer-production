#!/usr/bin/env python3
"""Execute frozen, verbatim Activity C16/C21 bodies with declared JVM adapters.

Not a source-tripwire-only test and not a full Activity/Android/HTTP/SQLite journey.
No source patch, old-code simulation, network, dependency download or emulator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

def sha(raw):
    return hashlib.sha256(raw).hexdigest().upper()


def expected_sha(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise argparse.ArgumentTypeError('Expected exactly 64 hexadecimal SHA256 characters')
    return value.upper()


def fragment(source, marker):
    """Balanced Java lexical extraction; no brace counting inside comments/strings."""
    if source.count(marker) != 1:
        raise ValueError('Expected exactly one production marker: ' + marker)
    begin = source.index(marker)
    opening = source.index('{', begin)
    depth, cursor, state = 1, opening + 1, 'code'
    while cursor < len(source) and depth:
        char = source[cursor]
        following = source[cursor:cursor + 2]
        if state == 'line':
            if char in '\r\n':
                state = 'code'
        elif state == 'block':
            if following == '*/':
                state = 'code'
                cursor += 1
        elif state in ('string', 'char'):
            if char == '\\':
                cursor += 1
            elif char == ('"' if state == 'string' else "'"):
                state = 'code'
        elif following == '//':
            state = 'line'
            cursor += 1
        elif following == '/*':
            state = 'block'
            cursor += 1
        elif char == '"':
            state = 'string'
        elif char == "'":
            state = 'char'
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        cursor += 1
    if depth:
        raise ValueError('Unterminated Java production fragment: ' + marker)
    text = source[begin:cursor]
    return text, {'marker': marker, 'byte_start': len(source[:begin].encode('utf-8')),
                  'byte_end': len(source[:cursor].encode('utf-8')), 'sha256': sha(text.encode('utf-8'))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--gson-jar', type=Path)
    parser.add_argument('--expected-activity-sha256', type=expected_sha)
    parser.add_argument('--expected-panel-sha256', type=expected_sha)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}', args.label):
        raise SystemExit('Fresh bounded evidence label required')
    root = Path(__file__).resolve().parents[1]
    java = root / 'app/src/main/java/com/baseer/freshchat'
    tests = root / 'tests/room-explore-hook'
    activity = java / 'OdooIdentityActivity.java'
    panel = java / 'BChatRoomExplorePanel.java'
    media_owner = java / 'sync/BChatConnectedMediaStore.java'
    actual = [java / 'RoomExploreProtocol.java', java / 'ReplyWireContract.java',
              java / 'sync/AccountScope.java', java / 'sync/OutboxPolicy.java']
    inputs = [activity, panel, media_owner, *actual, *sorted(tests.iterdir()), Path(__file__).resolve()]
    output = root / 'artifacts/room-explore-hook' / args.label
    output.mkdir(parents=True, exist_ok=False)
    result = {'passed': False, 'scope': 'Verbatim frozen Activity orchestration on JVM with explicit adapters; '
              'not full Activity/Android/auth/HTTP/SQLite/actual viewport/ACK/performance acceptance'}
    source_hashes, copied_hashes = {}, {}
    try:
        if args.gson_jar is not None and not args.gson_jar.is_file():
            raise RuntimeError('Explicit Gson jar missing; no fallback/download')
        candidates = [args.gson_jar] if args.gson_jar else []
        if os.environ.get('BCHAT_TEST_GSON_JAR'):
            candidates.append(Path(os.environ['BCHAT_TEST_GSON_JAR']))
        if os.environ.get('GRADLE_HOME'):
            candidates += sorted((Path(os.environ['GRADLE_HOME']) / 'lib').glob('gson-*.jar'))
        gradle = shutil.which('gradle')
        if gradle:
            candidates += sorted((Path(gradle).resolve().parents[1] / 'lib').glob('gson-*.jar'))
        candidates += sorted(Path('D:/Codex/tools/gradle-8.11.1/lib').glob('gson-*.jar'))
        gson = next((path.resolve() for path in candidates if path and path.is_file()), None)
        if gson is None:
            raise RuntimeError('Existing explicit test-only Gson jar required; no download')
        java_home = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else None
        suffix = '.exe' if os.name == 'nt' else ''
        javac = java_home / 'bin' / ('javac' + suffix) if java_home else shutil.which('javac')
        jvm = java_home / 'bin' / ('java' + suffix) if java_home else shutil.which('java')
        if not javac or not jvm:
            raise RuntimeError('Existing JDK17 required')
        project, archive, classes = output / 'project', output / 'inputs', output / 'classes'
        compiled, captured = [], {}
        for path in inputs:
            raw = path.read_bytes()
            if path == activity and args.expected_activity_sha256 and sha(raw) != args.expected_activity_sha256:
                raise RuntimeError('Approved Activity changed during capture')
            if path == panel and args.expected_panel_sha256 and sha(raw) != args.expected_panel_sha256:
                raise RuntimeError('Approved Panel changed during capture')
            captured[path] = raw
            name = path.relative_to(root).as_posix()
            source_hashes[name] = sha(raw)
            target = archive / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            copied_hashes[target.relative_to(output).as_posix()] = sha(raw)
            if path in actual or path in (tests / 'JSONObject.java', tests / 'JSONArray.java'):
                destination = project / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                compiled.append(destination)
                copied_hashes[destination.relative_to(output).as_posix()] = sha(raw)

        # Generate only from the same bytes archived above, never from a second live read.
        source = captured[activity].decode('utf-8')
        markers = [
            'private void closeRoomExplore(', 'private boolean exploreBindingCurrent(',
            'private void showRoomExplore(', 'private void jumpToCanonicalMessage(',
            'private Room currentInfoRoom(', 'private int messagePosition(',
            'private void requireReceiptEpoch(', 'private List<JSONObject> validateMessageList(',
            'private static long positiveId(', 'private static final class Room {',
            'private static final class MediaRecord {', 'private static final class ScrollAnchor {',
            'private long beginTimelinePositionIntent(', 'private void jumpToLatest(',
            'private void loadMessages(',
        ]
        fragments, metadata = [], []
        for index, marker in enumerate(markers):
            text, entry = fragment(source, marker)
            target = output / 'fragments' / ('%02d.java.txt' % index)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode('utf-8'))
            entry.update({'source': activity.relative_to(root).as_posix(), 'archive': target.relative_to(output).as_posix()})
            metadata.append(entry)
            fragments.append(text)
            copied_hashes[target.relative_to(output).as_posix()] = entry['sha256']
        panel_fragments = []
        for index, marker in enumerate(('interface Reply {', 'interface Host {')):
            text, entry = fragment(captured[panel].decode('utf-8'), marker)
            target = output / 'fragments' / ('panel-%02d.java.txt' % index)
            target.write_bytes(text.encode('utf-8'))
            entry.update({'source': panel.relative_to(root).as_posix(), 'archive': target.relative_to(output).as_posix()})
            metadata.append(entry)
            panel_fragments.append(text)
            copied_hashes[target.relative_to(output).as_posix()] = entry['sha256']
        template = captured[tests / 'OdooIdentityActivity.java.in'].decode('utf-8')
        if template.count('@@PRODUCTION@@') != 1 or template.count('@@PANEL_INTERFACES@@') != 1:
            raise RuntimeError('Exactly one explicit insertion point required')
        generated = template.replace('@@PRODUCTION@@', '\n\n'.join(fragments)).replace('@@PANEL_INTERFACES@@', '\n'.join(panel_fragments))
        target = project / 'extracted/com/baseer/freshchat/OdooIdentityActivity.java'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(generated.encode('utf-8'))
        compiled.append(target)
        copied_hashes[target.relative_to(output).as_posix()] = sha(target.read_bytes())
        constants = []
        for name in ('IMAGE_LIMIT', 'AUDIO_LIMIT', 'PDF_LIMIT'):
            matches = re.findall(r'public static final int ' + name + r' = ([0-9* ]+);', captured[media_owner].decode('utf-8'))
            if len(matches) != 1:
                raise RuntimeError('Media constants source changed: ' + name)
            value = 1
            for factor in matches[0].split('*'):
                value *= int(factor.strip())
            constants.append('public static final int %s = %d;' % (name, value))
        shim = project / 'constants/com/baseer/freshchat/sync/BChatConnectedMediaStore.java'
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.write_bytes(('package com.baseer.freshchat.sync; public final class BChatConnectedMediaStore {'
                          + ''.join(constants) + '}\n').encode('utf-8'))
        compiled.append(shim)
        copied_hashes[shim.relative_to(output).as_posix()] = sha(shim.read_bytes())
        gson_hash = sha(gson.read_bytes())
        activity_hash = source_hashes[activity.relative_to(root).as_posix()]
        panel_hash = source_hashes[panel.relative_to(root).as_posix()]
        manifest = {'schema': 1, 'activity_sha256': activity_hash, 'panel_sha256': panel_hash,
                    'expected_activity_sha256': args.expected_activity_sha256,
                    'expected_panel_sha256': args.expected_panel_sha256,
                    'scope': result['scope'], 'source_sha256': source_hashes, 'copied_sha256': copied_hashes,
                    'production_fragments': metadata, 'gson_path': str(gson), 'gson_sha256': gson_hash,
                    'adapters': ['Gson JSONObject/JSONArray API (not Android parser/coercion)',
                                 'Panel wrapper with verbatim Reply/Host interfaces, no UI',
                                 'UI controls/layout/postOnAnimation queue and formatter/dp',
                                 'chat/media booleans and identity-map repository generation',
                                 'presentation-admission boolean adapter, not actual TimelineWindowOwner authority',
                                 'held GET/POST transport with declared admission failures, no WebView',
                                 'persistence/render counters and window/draft/reply/outbox sentinels, no disk',
                                 'scan invocation counter only, no geometry/durability/read ACK',
                                 'three media limit constants extracted from actual storage owner, no storage execution']}
        manifest_path = output / 'source-manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        manifest_hash = sha(manifest_path.read_bytes())

        def frozen():
            for name, digest in source_hashes.items():
                if sha((root / name).read_bytes()) != digest:
                    raise RuntimeError('Live source changed: ' + name)
            for name, digest in copied_hashes.items():
                if sha((output / name).read_bytes()) != digest:
                    raise RuntimeError('Copied/generated input changed: ' + name)
            if sha(gson.read_bytes()) != gson_hash or sha(manifest_path.read_bytes()) != manifest_hash:
                raise RuntimeError('Dependency/manifest changed')

        def run(command):
            executed = subprocess.run([str(value) for value in command], text=True, encoding='utf-8',
                                      errors='replace', capture_output=True, timeout=90)
            with (output / 'test.log').open('a', encoding='utf-8') as log:
                log.write(executed.stdout + executed.stderr)
            if executed.returncode:
                raise RuntimeError('Compile/test exit %d; see preserved test.log' % executed.returncode)
            return executed.stdout + executed.stderr

        frozen()
        version = run([javac, '-version'])
        if not re.search(r'javac 17\.', version):
            raise RuntimeError('JDK17 required, actual: ' + version.strip())
        classes.mkdir()
        run([javac, '--release', '8', '-encoding', 'UTF-8', '-cp', gson, '-d', classes, *compiled])
        frozen()
        raw = run([jvm, '-cp', os.pathsep.join((str(classes), str(gson))), 'com.baseer.freshchat.OdooIdentityActivity'])
        frozen()
        match = re.search(r'PASS (\d+) extracted Activity C16/C21 orchestration checks across (\d+) deterministic cases', raw)
        if not match:
            raise RuntimeError('Missing explicit PASS counter')
        result.update({'passed': True, 'checks': int(match[1]), 'cases': int(match[2]),
                       'activity_sha256': activity_hash, 'source_manifest_sha256': manifest_hash,
                       'source_before_after_equal': True, 'copied_inputs_before_after_equal': True,
                       'production_fragment_count': len(metadata), 'jdk': version.strip()})
        print(raw.strip())
    except BaseException as error:
        result['failure'] = str(error)
        print('FAIL: ' + str(error), file=sys.stderr)
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    if not result['passed']:
        raise SystemExit(1)
    print('Evidence: ' + str(output))


if __name__ == '__main__':
    main()
