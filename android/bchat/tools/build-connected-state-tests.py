#!/usr/bin/env python3
"""Compile a disposable instrumentation APK for real Android SQLite, without a product build.

No SDK/JDK install, network call or device install. Output is unsigned. The caller supplies
the existing signing identity and an explicit disposable emulator when executing acceptance.
"""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--order-policy-only', action='store_true', help='Build only the focused policy regression, not unchanged suites')
parser.add_argument('--before-policy-fix', action='store_true', help='Use the frozen pre-fix policy for a required failing regression demonstration')
args_cli = parser.parse_args()
if args_cli.before_policy_fix and not args_cli.order_policy_only:
    parser.error('--before-policy-fix requires --order-policy-only')
sdk = Path(os.environ.get('ANDROID_HOME', 'D:/Codex/AndroidSdk'))
tools = sdk / 'build-tools/35.0.0'
android = sdk / 'platforms/android-35/android.jar'
suffix = '.exe' if os.name == 'nt' else ''
javac = shutil.which('javac')
if not javac or not android.is_file():
    raise SystemExit('Existing JDK and Android SDK35 are required; nothing is downloaded.')
test_name = 'BChat-Order-Policy-Tests' if args_cli.order_policy_only else 'BChat-Connected-State-Tests'
if args_cli.before_policy_fix:
    test_name += '-BEFORE-FIX'
output = root / ('artifacts/' + test_name + '-UNSIGNED.apk')
temporary_root = root / 'artifacts/test-runtime'
temporary_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='state-tests-', dir=temporary_root) as temp:
    folder = Path(temp)
    classes, dex = folder / 'classes', folder / 'dex'
    classes.mkdir()
    dex.mkdir()
    base = folder / 'base.apk'
    manifest = root / 'tests/outbox-android/AndroidManifest.xml'
    if args_cli.order_policy_only:
        manifest = folder / 'AndroidManifest.xml'
        manifest.write_text((root / 'tests/outbox-android/AndroidManifest.xml').read_text(encoding='utf-8')
                            .replace('OutboxInstrumentation', 'OrderPolicyInstrumentation'), encoding='utf-8')
    subprocess.run([str(tools / ('aapt2' + suffix)), 'link', '-o', str(base), '-I', str(android),
                    '--manifest', str(manifest)], check=True)
    sources = list((root / 'app/src/main/java/com/baseer/freshchat/sync').glob('*.java'))
    activity = (root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java').read_text(encoding='utf-8')
    def production_block(marker):
        start = activity.index(marker)
        opening = activity.index('{', start)
        depth, end = 1, opening + 1
        while depth:
            depth += (activity[end] == '{') - (activity[end] == '}')
            end += 1
        return activity[start:end]

    permission_set = production_block('private static final class PermissionSet {')
    probe = folder / 'PermissionPolicyProbe.java'
    template = (root / 'tests/outbox-android/PermissionPolicyProbe.java.in').read_text(encoding='utf-8')
    probe.write_text(template.replace('%PRODUCTION_PERMISSION_SET%', permission_set), encoding='utf-8')
    sources.extend([probe, root / 'app/src/main/java/com/baseer/freshchat/MediaRights.java'])
    refresh_probe = folder / 'PermissionRefreshProbe.java'
    refresh_template = (root / 'tests/outbox-android/PermissionRefreshProbe.java.in').read_text(encoding='utf-8')
    for token, source in {
        '%PRODUCTION_PERMISSION_SET%': permission_set,
        '%PRODUCTION_POSITIVE_ID%': production_block('private static long positiveId('),
        '%PRODUCTION_REFRESH%': production_block('private void refreshPermissionSet('),
        '%PRODUCTION_DENY%': production_block('private void closeDeniedPermissionView('),
    }.items():
        refresh_template = refresh_template.replace(token, source)
    refresh_probe.write_text(refresh_template, encoding='utf-8')
    sources.append(refresh_probe)
    audio_probe = folder / 'ConnectedAudioProbe.java'
    audio_template = (root / 'tests/outbox-android/ConnectedAudioProbe.java.in').read_text(encoding='utf-8')
    for token, marker in {
        '%PRODUCTION_AUDIO_TIME%': 'private static String audioTime(',
        '%PRODUCTION_STOP_INLINE%': 'private void stopInlineAudio(',
        '%PRODUCTION_TOGGLE_INLINE%': 'private void toggleInlineAudio(',
        '%PRODUCTION_AUDIO_ATTRIBUTES%': 'private AudioAttributes connectedAudioAttributes(',
        '%PRODUCTION_STOP_OWNED%': 'private void stopOwnedInlineAudio(',
    }.items():
        audio_template = audio_template.replace(token, production_block(marker))
    audio_probe.write_text(audio_template, encoding='utf-8')
    sources.extend([audio_probe, root / 'app/src/main/java/com/baseer/freshchat/AudioFocusLease.java'])
    intent_probe = folder / 'IntentDispatchProbe.java'
    intent_template = (root / 'tests/outbox-android/IntentDispatchProbe.java.in').read_text(encoding='utf-8')
    for token, marker in {
        '%LOCAL%': 'private <T> void local(',
        '%INTENT_KEY%': 'private String intentWriteKey(',
        '%INTENT_BUSY%': 'private boolean intentBusy(',
        '%INTENT_WORK%': 'private boolean intentWork(',
        '%PERSIST_INTENT%': 'private boolean persistIntent(',
        '%CONTEXT%': 'private boolean currentIntentContext(',
        '%MEMBERSHIP%': 'private long intentMembership(',
        '%ORDER_DISPATCH%': 'private void sendPendingOrder(',
        '%RECEIPT_DISPATCH%': 'private void sendPendingReceipt(',
        '%SHARE_DISPATCH%': 'private void shareConfirmedReceipt(',
    }.items():
        intent_template = intent_template.replace(token, production_block(marker))
    intent_probe.write_text(intent_template, encoding='utf-8')
    sources.extend([intent_probe, root / 'tests/outbox-android/com/baseer/freshchat/sync/test/IntentPersistenceChecks.java'])
    policy_probe = folder / 'OrderPolicyPersistenceProbe.java'
    policy_template = (root / 'tests/outbox-android/OrderPolicyPersistenceProbe.java.in').read_text(encoding='utf-8')
    for token, marker in {
        '%APPLY%': 'private void applyOrderRights(',
        '%PERSIST%': 'private void persistOrderPolicy(',
        '%READY%': 'private void offlinePolicyReady(',
        '%LOCAL%': 'private <T> void local(',
    }.items():
        value = production_block(marker)
        if token == '%APPLY%' and args_cli.before_policy_fix:
            value = (root / 'tests/outbox-android/OrderPolicyBeforeFix.java.in').read_text(encoding='utf-8')
        policy_template = policy_template.replace(token, value)
    policy_probe.write_text(policy_template, encoding='utf-8')
    if args_cli.order_policy_only:
        sources = [root / 'app/src/main/java/com/baseer/freshchat/sync/AccountScope.java',
                   root / 'app/src/main/java/com/baseer/freshchat/sync/OutboxPolicy.java',
                   root / 'app/src/main/java/com/baseer/freshchat/sync/BChatStorageRepository.java', policy_probe,
                   root / 'tests/outbox-android/com/baseer/freshchat/sync/test/OrderPolicyInstrumentation.java']
    else:
        sources.append(root / 'tests/outbox-android/com/baseer/freshchat/sync/test/OutboxInstrumentation.java')
    subprocess.run([javac, '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-Xlint:-options',
                    '-cp', str(android), '-d', str(classes), *map(str, sources)], check=True)
    args = folder / 'classes.txt'
    # D8 argument files contain one raw path per line; quote characters become path characters.
    args.write_text('\n'.join(str(file).replace('\\', '/') for file in classes.rglob('*.class')), encoding='utf-8')
    d8 = tools / ('d8.bat' if os.name == 'nt' else 'd8')
    subprocess.run([str(d8), '--min-api', '26', '--lib', str(android), '--output', str(dex), '@' + str(args)], check=True)
    with zipfile.ZipFile(base, 'a', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in dex.glob('classes*.dex'):
            archive.write(file, file.name)
    subprocess.run([str(tools / ('zipalign' + suffix)), '-f', '4', str(base), str(output)], check=True)
print(output)
print('Unsigned disposable test APK compiled; no product APK, device or Android execution claimed.')
