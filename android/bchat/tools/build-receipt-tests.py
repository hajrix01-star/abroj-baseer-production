#!/usr/bin/env python3
"""Build only a disposable real-SQLite receipt test APK. No network, install or product artifact."""
from pathlib import Path
import hashlib
import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
mutation = parser.add_mutually_exclusive_group()
mutation.add_argument('--simulate-old-invalidation', action='store_true', help='Negative regression only: omit the receipt reset from the extracted purge hook')
mutation.add_argument('--simulate-old-read-proof', action='store_true', help='Negative regression only: omit canonical revalidation after missing receipt evidence')
args_cli = parser.parse_args()
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
build = sdk / 'build-tools/35.0.0'
android = sdk / 'platforms/android-35/android.jar'
suffix = '.exe' if os.name == 'nt' else ''
javac = shutil.which('javac')
if not javac or not android.is_file():
    raise SystemExit('Existing JDK17 and SDK35 required; nothing is downloaded.')
name_suffix = '-OLD-INVALIDATION' if args_cli.simulate_old_invalidation else '-OLD-READ-PROOF' if args_cli.simulate_old_read_proof else ''
output = root / ('artifacts/BChat-Receipt-Tests' + name_suffix + '-UNSIGNED.apk')
temporary = root / 'artifacts/test-runtime'
temporary.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='receipt-tests-', dir=temporary) as name:
    folder = Path(name)
    classes, dex = folder / 'classes', folder / 'dex'
    classes.mkdir(); dex.mkdir()
    base = folder / 'base.apk'
    subprocess.run([str(build / ('aapt2' + suffix)), 'link', '-o', str(base), '-I', str(android),
                    '--manifest', str(root / 'tests/receipts-android/AndroidManifest.xml')], check=True)
    sources = [root / 'app/src/main/java/com/baseer/freshchat/sync' / name for name in
               ('AccountScope.java', 'OutboxPolicy.java', 'ConnectedHistoryCache.java', 'ReceiptDeliveryProtocol.java', 'BChatStorageRepository.java')]
    sources.append(root / 'tests/receipts-android/ReceiptInstrumentation.java')
    activity_path = root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java'
    activity_bytes = activity_path.read_bytes()
    activity = activity_bytes.decode('utf-8')
    template = (root / 'tests/receipts-android/ReceiptActivityProbe.java.in').read_text(encoding='utf-8')
    extracted = []
    for token, marker in {
        '%LIVE_REQUEST%': 'private static final class LiveRequest {',
        '%CANONICAL_VALIDATOR%': 'private List<JSONObject> validateMessageList(',
        '%REQUIRE_EPOCH%': 'private void requireReceiptEpoch(',
        '%RESET%': 'private void resetReceiptPass(',
        '%INVALIDATE%': 'private void invalidateReceiptRoomBinding(',
        '%ROOM_SNAPSHOT%': 'private void persistReceiptRooms(',
        '%PURGE_ROOM%': 'private void purgeCachedRoom(',
        '%DISK%': 'private <T> void receiptDisk(',
        '%PERSIST%': 'private void persistReceiptCanonical(',
        '%ROOM%': 'private Room receiptRoom(',
        '%READY%': 'private boolean receiptSyncReady(',
        '%SCHEDULE%': 'private void scheduleReceiptSync(',
        '%FINISH%': 'private void finishReceiptPass(',
        '%DRAIN%': 'private void drainReceiptSync(',
        '%NEXT%': 'private void nextReceiptWork(',
        '%PENDING%': 'private void requestPendingReceiptReferences(',
        '%FETCH%': 'private void fetchReceiptCanonical(',
        '%DISPATCH%': 'private void dispatchReceiptIntent(',
        '%UNREAD%': 'private void applyReceiptUnread(',
        '%READ%': 'private void acknowledgeMessage(',
    }.items():
        start = activity.index(marker)
        opening = activity.index('{', start)
        depth, end = 1, opening + 1
        while depth:
            depth += (activity[end] == '{') - (activity[end] == '}')
            end += 1
        body = activity[start:end]
        extracted.append(body)
        if args_cli.simulate_old_invalidation and token == '%PURGE_ROOM%':
            body = body.replace('        invalidateReceiptRoomBinding();', '')
        if args_cli.simulate_old_read_proof and token == '%READ%':
            before = body.index('            if (error instanceof ConnectedHistoryCache.MissingReceiptEvidence) {')
            after = body.index(' else if (error == null) scheduleReceiptSync(0);', before)
            body = body[:before] + '            if (error == null) scheduleReceiptSync(0);' + body[after + len(' else if (error == null) scheduleReceiptSync(0);'):]
        template = template.replace(token, body)
    probe = folder / 'ReceiptActivityProbe.java'
    probe.write_text(template, encoding='utf-8')
    sources.extend([probe, root / 'app/src/main/java/com/baseer/freshchat/ReplyWireContract.java'])
    source_sha = hashlib.sha256(activity_bytes).hexdigest()
    if hashlib.sha256(activity_path.read_bytes()).hexdigest() != source_sha:
        raise SystemExit('Activity changed during extraction; rerun against one frozen source.')
    print('Activity source SHA256:', source_sha)
    print('Extracted method bodies SHA256:', hashlib.sha256('\n'.join(extracted).encode()).hexdigest())
    if name_suffix: print('NEGATIVE FIXTURE ONLY:', name_suffix, 'is an explicit extracted-code mutation, not the product or a historical full-source build.')
    subprocess.run([javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
                    '-cp', str(android), '-d', str(classes), *map(str, sources)], check=True)
    args = folder / 'classes.txt'
    args.write_text('\n'.join(str(file).replace('\\', '/') for file in classes.rglob('*.class')), encoding='utf-8')
    subprocess.run([str(build / ('d8.bat' if os.name == 'nt' else 'd8')), '--min-api', '26',
                    '--lib', str(android), '--output', str(dex), '@' + str(args)], check=True)
    with zipfile.ZipFile(base, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in dex.glob('classes*.dex'): archive.write(file, file.name)
    subprocess.run([str(build / ('zipalign' + suffix)), '-f', '4', str(base), str(output)], check=True)
print(output)
print('Unsigned isolated test artifact only; no product APK, HTTP, FCM, UI or execution claim.')
