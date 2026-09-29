"""Record verified IC2 R2 delivery without modifying the frozen artifact."""
import json
from pathlib import Path
import ic2_recovery as recovery
r, b = recovery.r, recovery.b
candidate = r.read_json(r.OUT / 'candidate.json')
assert r.read_json(r.OUT / 'runtime.json')['candidate'] == candidate['commit']
assert r.read_json(r.OUT / 'main-smoke.json')['status'] == 'PASS'
public = {'commit': 'be89096027c823dbe5414bbf95ce97e9e354a5b6',
          'source_commit': candidate['commit'], 'remote_match': True, 'checkout_clean': True,
          'source_files': 1181, 'source_only': True, 'workflow_id': 34511962677,
          'workflow_status': 'completed', 'workflow_conclusion': 'success',
          'workflow_url': 'https://github.com/hajrix01-star/Odoo-Baseer/actions/runs/34511962677'}
b.save(r.OUT / 'github-publication.json', public)
draft = (b.ROOT / 'docs/build-governance/IC2-HANDOFF-DRAFT.md').read_text(encoding='utf8')
draft = draft.replace('Release identity and deployment outcome must be filled from candidate/runtime/preservation evidence after publication. This draft is not a release claim.',
    'Installed and verified on MAIN18069: `' + candidate['commit'] + '`, correction19.0.1.1.0 and summary19.0.1.5.1. '
    '1181 source files;1166 prior files preserved,11 modified and4 added within the two existing addons. '
    'GitHub main`' + public['commit'] + '` matches the verified source-only checkout; Actions34511962677 succeeded. '
    'MAIN read-only Arabic/English/native-mobile/settings smoke passed.')
draft = draft.replace('MAIN deployment must preserve', 'Verified MAIN deployment preserved').replace('Only reviewed additive fields/transient schema are allowed.', 'Only the reviewed additive fields/transient schema were added.')
draft += '\n\nThe first candidate31330640045c448f453f0430a9caa9fd66c74f5a installed its schema successfully but failed strict preservation: native translation export had included runtime company-record XMLIDs, adding stored translations to45 seeded names; native accountant share recomputation touched metadata on2 partners. No amount, mapping, posting, state or security differences occurred. The service remained stopped. R2 removed only45 dynamic PO references/12 entries, preserving451 static translations and all functional source. Independently approved ic2_recovery.py restored exactly those47 rows from the verified coherent backup in one guarded transaction, proving all372 old-column projections before commit. No second module update was run. Failed candidate/logs remain immutable.\n'
draft += '\nAll372 protected old-column rows, security memberships, company access, presets and unrelated versions are now exact. Coherent pre/post backups each verified661 attachment references. The cancelled legacy bill/payment example was not changed automatically. Original URL: http://127.0.0.1:18069.\n'
(r.OUT / 'HANDOFF.md').write_text(draft, encoding='utf8')
index = b.ROOT / 'docs/architecture/registry/INDEX.md'
current = index.read_text(encoding='utf8')
prefix = ('IC2 R2 current MAIN release (2026-09-10):`' + candidate['commit'] + '`, correction19.0.1.1.0/summary19.0.1.5.1. '
          'Unified eligible invoice/payment and per-purchase-row cancellation; atomic summary reverse/edit/reapprove or cancel. '
          'Shared owner/accountant toggle and unconditional cashier denial; native source/entry bypass guards. '
          '60core+38summary checks,2actualraces,AR/EN/480pxUI and actual-accounting verification PASS. '
          '372oldtable projections/security/presets/versions exact;661attachmentrefs pre/postbackups. '
          '1181files/15changed/1166preserved. First upgrade stopped on45translatednames+2partnermetadata drift; '
          'R2 removes dynamic PO records and restores exact old values under independent GO, no second upgrade. '
          'GitHubbe89096027c823dbe5414bbf95ce97e9e354a5b6,CI34511962677success. '
          '[Handoff](../../releases/2026-09-10-financial-source-lifecycle-r2/HANDOFF.md). Earlier entries historical.\n\n')
assert not current.startswith('IC2 R2 current')
index.write_text(prefix + current, encoding='utf8')
print('IC2 R2 handoff/publication/registry recorded')
