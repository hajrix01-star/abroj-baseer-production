#!/usr/bin/env python3
"""Execute unmodified Activity ownership/proof seams with explicit JVM host/JSON/platform adapters.

verifyV2 and notificationPresentationOwned are extracted in full. restrictCompanyScope is
extracted only through its first global-generation advance; applyPermissionSet only through
its notification reset/flush prefix, before repository invalidation. Trailing UI/cache work
is not executed or claimed. No HTTP, Android lifecycle, SQLite, FCM, or OS cancellation.
No old-code mutation/alternate source is used for RED: this always reads the current Activity.
"""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--case', choices=('all', 'company', 'bootstrap'), default='all')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
source = root / 'app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java'
template = root / 'tests/notification-rights-reset/NotificationRightsResetProbe.java.in'
source_bytes = source.read_bytes()
activity = source_bytes.decode('utf-8')


def method(marker):
    start = activity.index(marker)
    opening = activity.index('{', start)
    depth, end = 1, opening + 1
    while depth:
        depth += (activity[end] == '{') - (activity[end] == '}')
        end += 1
    return activity[start:end]


owned = method('private boolean notificationPresentationOwned(')
verify = method('private void verifyV2(')
company_full = method('private void restrictCompanyScope(')
company = company_full[:company_full.index('        ++mediaSessionGeneration;')]
permission_full = method('private void applyPermissionSet(')
permission = permission_full[:permission_full.index('            BChatStorageRepository.invalidate(scope);')]
parts = [('owned-full', owned), ('verifyV2-full', verify),
         ('company-generation-prefix', company), ('permission-revocation-prefix', permission)]
rendered = template.read_text(encoding='utf-8').replace('%OWNED%', owned).replace('%VERIFY%', verify)
rendered = rendered.replace('%COMPANY_PREFIX%', company + '    }')
# Host-only bookkeeping follows the unchanged prefix, not the remainder of applyPermissionSet.
rendered = rendered.replace('%PERMISSION_PREFIX%', permission
                            + '        }\n        permissionSet = next; ++permissionApplications;\n    }')
source_sha = hashlib.sha256(source_bytes).hexdigest()
print('Activity source SHA256:', source_sha, flush=True)
for name, body in parts:
    print(name, 'SHA256:', hashlib.sha256(body.encode()).hexdigest(), flush=True)
print('Extracted bodies SHA256:', hashlib.sha256('\n'.join(body for _, body in parts).encode()).hexdigest(), flush=True)
print('Template SHA256:', hashlib.sha256(template.read_bytes()).hexdigest(), flush=True)
print('Evidence scope: full verifyV2/owned methods plus unchanged company/permission prefixes; '
      'explicit host, JSON, transport, platform, and downstream cache/UI adapters.', flush=True)
temporary = root / 'artifacts/test-runtime'
temporary.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='notification-rights-', dir=temporary) as folder:
    target = Path(folder)
    probe = target / 'NotificationRightsResetProbe.java'
    probe.write_text(rendered, encoding='utf-8')
    classes = target / 'classes'
    classes.mkdir()
    sync = root / 'app/src/main/java/com/baseer/freshchat/sync'
    subprocess.run([shutil.which('javac') or 'javac', '-encoding', 'UTF-8', '-d', str(classes),
                    str(probe), str(sync / 'AccountScope.java'), str(sync / 'OutboxPolicy.java')], check=True)
    result = subprocess.run([shutil.which('java') or 'java', '-cp', str(classes),
                             'com.baseer.freshchat.NotificationRightsResetProbe', args.case])
if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha:
    raise SystemExit('Activity changed during verification; no frozen-source result claimed.')
raise SystemExit(result.returncode)
