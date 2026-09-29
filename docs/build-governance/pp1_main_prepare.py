"""Prepare the scoped PP1 release runner from the established BP1 release process."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'docs/build-governance/bp1_release.py').read_text(encoding='utf8')
replacements = {
    'Freeze BP1 on the accepted SD4 source': 'Freeze reviewed PP1 on the accepted BP1 source',
    "MODULE = 'baseer_browser_print'": "MODULE = 'baseer_partner_priority'",
    "OLD_RELEASE = '2026-09-09-sales-dashboard-application-share'": "OLD_RELEASE = '2026-09-09-browser-print'",
    "NEW_RELEASE = '2026-09-09-browser-print'": "NEW_RELEASE = '2026-09-10-partner-priority-main'",
    "OLD_FOLDER = 'sales-dashboard-application-share-20260909'": "OLD_FOLDER = 'browser-print-20260909'",
    "NEW_FOLDER = 'browser-print-20260909'": "NEW_FOLDER = 'partner-priority-main-20260910'",
    '1108f2a8fc0edee2f61d728135feee02590a8f46': '80ab864153b9e337090d5a1286150e7a64ad6319',
    "EVIDENCE = ('bp1-ui-checks.json', 'bp1-report-checks.json')": "REVIEWED = b.ROOT / 'docs/releases/2026-09-09-partner-priority/candidate.json'",
    '1118': '1126',
    'accepted SD4': 'accepted BP1',
    "manifest.get('depends') == ['web']": "manifest.get('depends') == ['account', 'baseer_purchase_batch']",
    'Expected browser print 19.0.1.0.0 with web dependency only': 'Expected reviewed partner priority manifest',
    "'codex/browser-print'": "'codex/partner-priority-main'",
    'Native PDF browser printing with separate download': 'Company supplier favorites and recent usage on current BP1 source',
    'BP1 publish ': 'PP1 MAIN publish ',
    'Browser printing frontend module installation only; no business seed, schema or transaction migration': 'Added company-dependent res_partner.baseer_is_favorite JSONB; no business seed or transaction migration',
    'Browser print': 'Partner priority',
    'browser print addon': 'partner priority addon',
}
# Replace simultaneously so the new OLD values are not replaced a second time.
import re
source = re.sub('|'.join(map(re.escape, replacements)), lambda m: replacements[m.group()], source)
start = source.index('    evidence = {name:')
end = source.index('    require(not SOURCE.exists()', start)
source = source[:start] + '''    reviewed = read_json(REVIEWED)
    require(reviewed['candidate'] == '9424da9a50ecda8d0462dc44ce2e7f0ab4012427', 'Reviewed PP1 identity differs')
    approved = {item['path']: item['sha256'] for item in reviewed['files']}
    require(len(approved) == 9 and all(b.sha(b.ROOT / r) == h for r, h in approved.items()),
            'Working addon must match all nine independently approved files')
''' + source[end:]
start = source.index('    for name in EVIDENCE +')
end = source.index("    print('FROZEN'", start)
source = source[:start] + '''    require({r: files[r] for r in added} == approved, 'Composite delta must be exactly the reviewed nine files')
    b.save(OUT / 'integration.json', dict(reviewed_candidate=reviewed['candidate'],
        main_parent=previous['commit'], main_files_preserved=1126, reviewed_files_identical=9))
''' + source[end:]
needle = "    require(candidate['module'] == MODULE"
pos = source.index(needle)
source = source[:pos] + '''    reviewed = read_json(REVIEWED)
    require({r: h for r, h in candidate['files'].items() if r.startswith(PREFIX)} ==
            {item['path']: item['sha256'] for item in reviewed['files']}, 'Reviewed PP1 hashes differ')
''' + source[pos:]
needle = "    b.save(OUT / 'runtime.json', dict(http=200"
pos = source.index(needle)
source = source[:pos] + '''    require(read_sql("SELECT state || '|' || latest_version FROM ir_module_module WHERE name='baseer_browser_print'")
            == 'installed|19.0.1.0.0', 'Existing browser printing must remain installed')
    require(read_sql("SELECT count(*) FROM res_partner WHERE coalesce(baseer_is_favorite, '{}'::jsonb) <> '{}'::jsonb")
            == '0', 'Unexpected favorite seed in MAIN')
''' + source[pos:]
target = root / 'docs/build-governance/pp1_main_release.py'
assert not target.exists(), 'Do not replace an existing release runner'
target.write_text(source, encoding='utf8')
print(target)
