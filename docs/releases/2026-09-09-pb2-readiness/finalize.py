"""Summarize only accepted, successful PB2 evidence after QA verification."""
import json,sys,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import pb2_ops as p
c=json.loads((p.OUT/'candidate.json').read_text())
assert all(json.loads((p.OUT/'postcheck.json').read_text()).values())
assert json.loads((p.OUT/'apply-result.json').read_text())['success']
results={}
for f in (p.OUT/'runtime').glob('*.json'):
 d=json.loads(f.read_text());checks=d.get('checks',[])
 assert d.get('status') in ('passed','completed') and all(x.get('pass') for x in checks),f.name
 results[f.stem]=len(checks)
p.save('test-summary.json',{'checks':results,'total':sum(results.values()),'candidate':c['commit'],'main_unchanged':True,'qa_updated':True})
text=f'''# PB2 — Employee payroll readiness

**QA applied and verified; MAIN was not updated.** Independent acceptance: [ACCEPTANCE.md](ACCEPTANCE.md).

Version `{c['version']}`, commit `{c['commit']}`, archiveSHA256 `{c['zip_sha256']}`. Overlay [baseer-payroll-pb2.zip](baseer-payroll-pb2.zip) replaces only baseer_payroll in the accepted FA2 source; all other FA2 source files match their baseline. Do not deploy the whole dirty workspace. QA's actual158 installed modules were used for testing.

New employees default to payroll inclusion, with explicit authorized exclusion preserved. Employees with incomplete contract start/salary remain visible in draft with zero effective amounts, a bilingual warning, and approval blocked until setup and refresh. Authorized HR changes invalidate derived draft amounts under employee locks; manual inputs and posted historical records are preserved. Native open-ended contracts remain start date plus empty end date, now with a clear hint. No new HR permissions, dependency, ledger or invented contract dates.

Tests: {sum(results.values())} assertions across {len(results)} suites; details in test-summary.json. Includes HR/Payroll roles, defaults and forged context, eligibility boundaries, repeat refresh, manual deductions, six-month financial regression,50mixed employees and concurrent requests. Browser proof: [UI-REVIEW.md](UI-REVIEW.md), Arabic/English desktop/mobile and default inclusion.

Deployment kept all93 discovered account_* tables exactly equal, all employee records and all salary/contract versions equal. Existing inclusion flags were not bulk enabled. A coherent PostgreSQL+filestore backup is retained under .local-backups/pb2-20260909/deployment/preinstall; backup configuration remains private. apply-result.json and postcheck.json bind QA verification to this source. The isolated clone was removed after acceptance; backup and evidence retained. No test-generated payroll postings were added to QA.

For older draft runs use Refresh Employees. Complete the real start date and salary before approval; missing start never becomes an inferred start. An ended or future contract is not made eligible merely to populate a row. Printable-contract capabilities and the current PDF attachment workflow are documented in [CONTRACTS.md](CONTRACTS.md); no legal template or automatic employment-contract PDF was added.
'''
(p.OUT/'HANDOFF.md').write_text(text,encoding='utf8')
files={f.relative_to(p.OUT).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in p.OUT.rglob('*') if f.is_file() and f.name!='evidence-index.json' and '__pycache__' not in f.parts}
p.save('evidence-index.json',{'commit':c['commit'],'files':files})
print('PB2 finalized',sum(results.values()),'assertions')
