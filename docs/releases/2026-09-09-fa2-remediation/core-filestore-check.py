"""Verify restored attachment content by Odoo's stored content address."""
import hashlib,json,os
from pathlib import Path
assert env.cr.dbname=='baseer_fix_core_20260909'
env.cr.execute("SELECT DISTINCT store_fname,checksum FROM ir_attachment WHERE store_fname IS NOT NULL")
rows=env.cr.fetchall();missing=[];wrong=[];total=0
root=Path('/var/lib/odoo/filestore')/env.cr.dbname
for name,expected in rows:
 p=(root/name).resolve()
 assert p.is_relative_to(root.resolve())
 if not p.is_file():missing.append(name);continue
 data=p.read_bytes();total+=len(data)
 if expected and hashlib.sha1(data).hexdigest()!=expected:wrong.append(name)
result={'database':env.cr.dbname,'distinct_stored_contents':len(rows),'bytes_verified':total,'missing_content_paths':missing,'checksum_mismatches':wrong}
Path('/mnt/qa-evidence/core-filestore-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
env.cr.rollback()
print(json.dumps(result))
assert not missing and not wrong
