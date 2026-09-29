"""Bind completed, inspected FL3/FL3B browser evidence to final addon source."""
import json
from pathlib import Path

from fl3_release import PREFIX, b, inventory

root = b.ROOT / 'docs/build-governance'
ui = root / 'fl3-ui'
browser = json.loads((ui / 'browser-checks.json').read_text(encoding='utf8'))
platform = json.loads((ui / 'platform-browser-checks.json').read_text(encoding='utf8'))
frontend = json.loads((ui / 'frontend-checks.json').read_text(encoding='utf8'))
assert browser['status'] == platform['status'] == 'PASS'
assert frontend['result'] == 'PASS'
assert platform['mobile_direction'] == 'rtl'
assert platform['mobile_width'] == platform['mobile_scroll_width'] == 480
for name in ('incoming-july-ar.png', 'incoming-july-ar.txt', 'incoming-en.png',
             'incoming-en.txt', 'incoming-mobile-ar.png', 'incoming-mobile-ar.txt'):
    assert (ui / name).is_file(), name
result = {
    'status': 'PASS', 'database': 'baseer_ic1_20260910',
    'browser_checks': browser['checks'] + platform['checks'],
    'frontend_assertions': frontend['assertions'],
    'observations': {
        'FL3 All-mode invoices, native POS and reversals': browser,
        'FL3B Applications incoming and actual outgoing': platform,
    },
    'limitations': [
        'Incoming includes posted Applications sales and settlement adjustments; it is not a bank balance.',
        'Historical cash-july evidence records the unadjusted actual-cash baseline of 890.',
        'Mobile kanban is selected when opening the native action at mobile width.',
        'Browser checks use the existing isolated QA data; no production capacity claim.',
    ],
    'source_sha256': {PREFIX + rel: sha for rel, sha in inventory(b.ROOT / PREFIX).items()},
    'evidence_files': {p.name: b.sha(p) for p in sorted(ui.iterdir()) if p.is_file()},
}
b.save(root / 'fl3-ui-checks.json', result)
print('FL3 UI evidence bound:', len(result['browser_checks']), 'browser checks')
