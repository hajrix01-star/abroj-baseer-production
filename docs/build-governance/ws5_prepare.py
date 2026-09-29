"""Prepare the existing frozen-release harness for WS5 without changing MAIN."""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
folder = root / 'docs/build-governance'
release = (folder / 'pos_empty_shift_release.py').read_text(encoding='utf8')
for old, marker in [('2026-09-09-pos-empty-shift', 'NEW_RELEASE'), ('pos-empty-shift-20260909', 'NEW_BACK'), ('2026-09-09-current-schedules', 'OLD_RELEASE'), ('current-schedules-20260909', 'OLD_BACK')]:
    release = release.replace(old, marker)
for marker, value in [('NEW_RELEASE', '2026-09-09-unified-time-picker'), ('NEW_BACK', 'unified-time-picker-20260909'), ('OLD_RELEASE', '2026-09-09-pos-empty-shift'), ('OLD_BACK', 'pos-empty-shift-20260909')]:
    release = release.replace(marker, value)
release = release.replace('baseer_pos_summary', 'baseer_work_schedule').replace('19.0.1.4.1', '19.0.1.1.2')
release = release.replace('pos-empty-shift-ui.json', 'ws5-ui.json')
release = release.replace('codex/pos-empty-shift', 'codex/unified-time-picker')
release = release.replace('Require explicit initial POS shift selection and simplify entry copy', 'Unify schedule time selection and fix narrow modal layout')
release = release.replace('Transient day_schedule becomes nullable; explicit sales-save guard. Existing business rows unchanged', 'Frontend time widget and styles only; no business schema or row changes')
(folder / 'ws5_release.py').write_text(release, encoding='utf8')
print('WS5 release helper prepared; no runtime changed')
