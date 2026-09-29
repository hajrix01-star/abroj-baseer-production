import json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[2]
folder=root/'docs/build-governance'
paths=[p for p in folder.glob('baseer_payroll_*') if p.suffix in ('.py','.json','.pdf','.png')]
index=[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(paths)]
(root/'docs/releases/2026-09-08-baseer-payroll/evidence.json').write_text(json.dumps(index,ensure_ascii=False,indent=2),encoding='utf-8')
print('Evidence files:',len(index))
