"""PT1: disable one duplicate inherited company view; preserve payroll settings/data."""
import json
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
import environment_backups as b

OUT = b.ROOT / 'docs/releases/2026-09-09-payroll-company-tab'
BACK = b.ROOT / '.local-backups/payroll-company-tab-20260909'
SOURCE = BACK / 'candidate'
OLD = b.ROOT / '.local-backups/bilingual-names-20260909/candidate'
REL = 'custom_addons/baseer_payroll/views/settings_views.xml'
OUT.mkdir(parents=True, exist_ok=True)

def shell_code(commit=False):
    return '''
import json
from lxml import etree
assert env.cr.dbname == 'baseer_dev'
view = env.ref('baseer_payroll.view_baseer_company_payroll')
assert view.model == 'res.company'
assert view.inherit_id == env.ref('base.view_company_form')
view.write({'active': False})
checks = []
for lang in ('ar_001', 'en_US'):
    company = etree.fromstring(env['res.company'].with_context(lang=lang).get_view(view_id=env.ref('base.view_company_form').id, view_type='form')['arch'])
    assert not company.xpath("//page[@name='baseer_payroll']")
    assert company.xpath("//field[@name='baseer_name_ar']") and company.xpath("//field[@name='baseer_name_en']")
    checks.append(lang + ': company payroll tab absent; bilingual names retained')
    settings = etree.fromstring(env['res.config.settings'].with_context(lang=lang).get_view(view_type='form')['arch'])
    for field in ('baseer_payroll_journal_id', 'baseer_salary_expense_id', 'baseer_salary_payable_id', 'baseer_deduction_account_id', 'baseer_loan_account_id', 'baseer_proration'):
        assert settings.xpath("//app[@name='om_hr_payroll']//field[@name='%s']" % field), field
        assert env['res.config.settings']._fields[field].related == 'company_id.' + field
    checks.append(lang + ': all six payroll settings retained with same company backing')
print('PT1_CHECKS ' + json.dumps(checks))
''' + ('env.cr.commit()\n' if commit else 'env.cr.rollback()\n')

def prepare():
    previous = json.loads((b.ROOT / 'docs/releases/2026-09-09-bilingual-names/candidate.json').read_text())
    assert all(b.sha(OLD / rel) == h for rel, h in previous['files'].items())
    working = b.ROOT / REL
    assert b.sha(working) == previous['files'][REL], 'Do not overwrite divergent user changes'
    content = working.read_text(encoding='utf8')
    marker = '<record id="view_baseer_company_payroll" model="ir.ui.view">'
    assert content.count(marker) == 1
    updated = content.replace(marker, marker + '<field name="active" eval="False"/>')
    working.write_text(updated, encoding='utf8')
    SOURCE.mkdir(parents=True, exist_ok=False)
    for rel in previous['files']:
        dest = SOURCE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(OLD / rel, dest)
    shutil.copy2(working, SOURCE / REL)
    files = {rel: b.sha(SOURCE / rel) for rel in previous['files']}
    assert [rel for rel in files if files[rel] != previous['files'][rel]] == [REL]
    b.run(['git', 'init', '--initial-branch=codex/pt1-company-payroll-tab', str(SOURCE)], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'config', 'core.autocrlf', 'false'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), 'add', '.'], capture_output=True)
    b.run(['git', '-C', str(SOURCE), '-c', 'user.name=Codex Release', '-c', 'user.email=codex-release@localhost', 'commit', '-qm', 'PT1 hide duplicate company payroll settings tab'], capture_output=True)
    commit = b.run(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    archive = OUT / 'candidate-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files): z.write(SOURCE / rel, rel)
    b.save(OUT / 'candidate.json', dict(commit=commit, parent=previous['commit'], image=previous['image'], files=files, changed_files=[REL], source_directory=str(SOURCE), archive_sha256=b.sha(archive)))
    # Native registry check in isolated transaction, no saved UI/business changes.
    result = b.run(['docker','exec','-i',b.MAIN_CONTAINER,'/entrypoint.sh','odoo','shell','--config=/etc/odoo/odoo.local.conf','--database='+b.MAIN,'--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--no-http','--max-cron-threads=0'], input=shell_code(), capture_output=True, text=True, encoding='utf8')
    (OUT / 'rollback-check.log').write_text(result.stdout + result.stderr, encoding='utf8')
    assert 'PT1_CHECKS ' in result.stdout
    print('PREPARED', commit, flush=True)

def publish():
    assert (OUT / 'PREDEPLOY-GO.md').is_file()
    candidate = json.loads((OUT / 'candidate.json').read_text())
    assert all(b.sha(SOURCE / rel) == h for rel, h in candidate['files'].items())
    b.run(['docker','stop','--time','60',b.MAIN_CONTAINER], capture_output=True)
    backup = b.backup(b.MAIN)
    b.save(OUT / 'main-backup.json', backup)
    before = b.signatures(b.MAIN)
    for filename in ('compose.yaml', 'compose.main-release.yaml'):
        path = b.ROOT / filename
        shutil.copy2(path, BACK / (filename + '.before'))
        content = path.read_text(encoding='utf8')
        assert content.count('./.local-backups/bilingual-names-20260909/candidate/') == 3
        path.write_text(content.replace('./.local-backups/bilingual-names-20260909/candidate/', './.local-backups/payroll-company-tab-20260909/candidate/'), encoding='utf8')
    result = b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','-T','odoo','odoo','shell','--config=/etc/odoo/odoo.local.conf','--database='+b.MAIN,'--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--no-http','--max-cron-threads=0'], input=shell_code(True), capture_output=True, text=True, encoding='utf8')
    (OUT / 'main-apply.log').write_text(result.stdout + result.stderr, encoding='utf8')
    assert 'PT1_CHECKS ' in result.stdout
    after = b.signatures(b.MAIN)
    differences = [r['name'] for r, a in zip(before, after) if r != a]
    assert len(before) == len(after) and differences == ['ir_ui_view'], differences
    b.save(OUT / 'preservation.json', dict(tables_checked=len(before), changed_tables=differences, all_other_tables_exact=True, candidate=candidate['commit']))
    helper = b.ROOT / 'docs/build-governance/environment_backups.py'
    shutil.copy2(helper, BACK / 'environment_backups.py.before')
    helper.write_text(helper.read_text(encoding='utf8').replace('2026-09-09-bilingual-names', '2026-09-09-payroll-company-tab').replace('bilingual-names-20260909', 'payroll-company-tab-20260909'), encoding='utf8')
    b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'], capture_output=True)
    for attempt in range(30):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3) as response:
                if response.status == 200: break
        except OSError: pass
        time.sleep(2)
    else: raise RuntimeError('MAIN healthcheck failed')
    b.save(OUT / 'runtime.json', dict(http=200, mounts=b.inspect(b.MAIN_CONTAINER)['Mounts'], candidate=candidate['commit']))
    print('PUBLISHED', flush=True)

if __name__ == '__main__':
    {'prepare': prepare, 'publish': publish}[sys.argv[1]]()
