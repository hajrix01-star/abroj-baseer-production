import json, hashlib
from pathlib import Path
from environment import OUT, BACK, DB, QA, OLD, run, signatures, save

before=sorted(json.loads((OUT/'main-before.json').read_text(encoding='utf8')),key=lambda r:r['name'])
after=signatures('baseer_dev')
save(OUT/'main-final.json',after)
assert before==after,'Original database fingerprint changed; investigate before claiming preservation'
with (BACK/'simulation-final.dump').open('wb') as handle:
    run(['docker','exec',DB,'pg_dump','-U','odoo','-Fc',OLD],stdout=handle)
run(['docker','exec',QA,'tar','-czf','/tmp/sim90-final-filestore.tar.gz','-C','/var/lib/odoo/filestore',OLD],capture_output=True)
run(['docker','cp',QA+':/tmp/sim90-final-filestore.tar.gz',str(BACK/'simulation-final-filestore.tar.gz')],capture_output=True)
result={'database':OLD,'port':18075,'main_tables_identical':len(after),'backup_files':{name:{'bytes':(BACK/name).stat().st_size,'sha256':hashlib.sha256((BACK/name).read_bytes()).hexdigest()} for name in ['simulation-final.dump','simulation-final-filestore.tar.gz']},'ui_png_count':len(list((OUT/'ui').glob('*.png'))),'source_code_changes':False,'github_changes':False}
save(OUT/'closeout.json',result)
print('FINAL_BACKUP_SAVED_MAIN_206_TABLES_IDENTICAL',flush=True)
