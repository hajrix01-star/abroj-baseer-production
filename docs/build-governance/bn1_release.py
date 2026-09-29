"""BN1 scoped source freeze and authorized original promotion."""
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
import environment_backups as b

OUT = b.ROOT / 'docs/releases/2026-09-09-bilingual-names'
BACK = b.ROOT / '.local-backups/bilingual-names-20260909'
SOURCE = BACK / 'candidate'
MODULE = 'baseer_service_seed'

def freeze():
    previous = json.loads((b.ROOT / 'docs/releases/2026-09-09-main-promotion/candidate.json').read_text())
    origin = b.ROOT / '.local-backups/main-promotion-20260909/candidate'
    assert all(b.sha(origin / rel) == h for rel, h in previous['files'].items())
    SOURCE.mkdir(exist_ok=False)
    for rel in previous['files']:
        dest = SOURCE / rel; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin / rel, dest)
    for path in (b.ROOT / 'custom_addons' / MODULE).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            rel = path.relative_to(b.ROOT)
            dest = SOURCE / rel; dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    files = {p.relative_to(SOURCE).as_posix(): b.sha(p) for p in SOURCE.rglob('*') if p.is_file()}
    changed = [rel for rel,h in files.items() if previous['files'].get(rel) != h]
    assert all(rel.startswith('custom_addons/'+MODULE+'/') for rel in changed)
    archive = OUT / 'candidate-source.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files): z.write(SOURCE/rel, rel)
    b.run(['git','init','--initial-branch=codex/bn1-bilingual-names',str(SOURCE)],capture_output=True)
    b.run(['git','-C',str(SOURCE),'config','core.autocrlf','false'],capture_output=True)
    b.run(['git','-C',str(SOURCE),'add','.'],capture_output=True)
    b.run(['git','-C',str(SOURCE),'-c','user.name=Codex Release','-c','user.email=codex-release@localhost','commit','-qm','BN1 bilingual company and supplier names'],capture_output=True)
    commit=b.run(['git','-C',str(SOURCE),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    b.save(OUT/'candidate.json',{'commit':commit,'image':previous['image'],'parent':previous['commit'],'files':files,'changed_files':changed,'archive_sha256':b.sha(archive),'source_directory':str(SOURCE),'module':MODULE,'version':'19.0.1.2.0'})
    shutil.copy2(b.ROOT/'docs/build-governance/bn1-results.json',OUT/'tests.json')
    print('CANDIDATE',commit,len(files),'changed',len(changed))

def promote():
    assert (OUT/'PREDEPLOY-GO.md').is_file(), 'Independent release review required'
    c=json.loads((OUT/'candidate.json').read_text())
    assert all(b.sha(SOURCE/rel)==h for rel,h in c['files'].items())
    b.run(['docker','stop','--time','60',b.MAIN_CONTAINER],capture_output=True)
    compose=b.ROOT/'compose.yaml'; old=compose.read_text(encoding='utf8')
    backup=None
    try:
        backup=b.backup(b.MAIN)
        b.save(OUT/'main-backup.json',backup)
        before={r['name']:r for r in b.signatures(b.MAIN)}
        names=b.sql(b.MAIN,'SELECT json_agg(t ORDER BY id) FROM (SELECT id,name FROM res_partner)t')
        shutil.copy2(compose,BACK/'compose-before.yaml')
        new=old.replace('./.local-backups/main-promotion-20260909/candidate/', './.local-backups/bilingual-names-20260909/candidate/')
        assert new!=old and new.count('./.local-backups/bilingual-names-20260909/candidate/')==3
        compose.write_text(new,encoding='utf8')
        with (OUT/'main-upgrade.log').open('wb') as log:
            b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','run','--rm','--no-deps','odoo','odoo','--config=/etc/odoo/odoo.local.conf','--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19','--database='+b.MAIN,'--update='+MODULE,'--stop-after-init','--no-http','--max-cron-threads=0'],stdout=log,stderr=log)
        after={r['name']:r for r in b.signatures(b.MAIN)}
        protected=[t for t in before if t.startswith(('account_','hr_payslip','baseer_','pos_'))]
        assert all(before[t]==after[t] for t in protected)
        assert names==b.sql(b.MAIN,'SELECT json_agg(t ORDER BY id) FROM (SELECT id,name FROM res_partner)t')
        b.save(OUT/'main-preservation.json',{'protected_tables':len(protected),'changed_protected_tables':[],'native_partner_names_preserved':True,'candidate':c['commit']})
    except Exception:
        # Do not reopen with mixed code/schema. Keep backup and report for recovery.
        print('PROMOTION_STOPPED; original left stopped; see preserved backup',flush=True)
        raise
    b.run(['docker','compose','-p','baseer_odoo_dev','-f','compose.yaml','up','-d','--no-deps','odoo'],capture_output=True)
    print('MAIN_PROMOTED',flush=True)

if __name__=='__main__':
    if sys.argv[1]=='freeze': freeze()
    elif sys.argv[1]=='promote': promote()
    else: raise ValueError('Unknown operation')
