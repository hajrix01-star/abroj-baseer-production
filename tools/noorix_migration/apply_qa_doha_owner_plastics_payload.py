import importlib.util,json,os
MONTH=os.environ.get('NOORIX_GENERAL_PURCHASE_MONTH','').strip()
if 'env' not in globals() or MONTH not in {'2026-04','2026-05','2026-06','2026-07','2026-08'}: raise RuntimeError('approved QA month required')
s=importlib.util.spec_from_file_location('w','/mnt/baseer-addons/baseer_noorix_migration/general_purchase_writer.py');w=importlib.util.module_from_spec(s);s.loader.exec_module(w)
try:r=w.apply_month(env,'/mnt/noorix-payload/runs/20260913-doha-owner-plastics-qa-1/doha-owner-plastics-payload.json','b7d4e55516499fe90ed917812504deb7cc801d8100867e03b813ad44173f0e04',MONTH);env.cr.commit()
except Exception: env.cr.rollback();raise
print(json.dumps(r,ensure_ascii=False,sort_keys=True))
