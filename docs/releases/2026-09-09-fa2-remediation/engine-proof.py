"""Pin the actual engine and preserve its complete source independently of local Git."""
import hashlib,json,subprocess,tarfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import fa2_ops as f
archive=f.BACK/'odoo-runtime-source.tar.gz'
image='odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
paths=['orm/models.py','orm/environments.py','service/model.py','addons/account/models/account_move.py',
 'addons/account/models/account_payment.py','addons/account/wizard/account_payment_register.py','addons/web/static/src/webclient/actions/action_service.js']
with tarfile.open(archive) as tar:
 archived={p:hashlib.sha256(tar.extractfile('odoo/'+p).read()).hexdigest() for p in paths}
script="import json,hashlib;from pathlib import Path;root=Path('/usr/lib/python3/dist-packages/odoo');paths="+repr(paths)+";print(json.dumps({p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in paths}))"
actual=json.loads(f.o.run(['docker','exec',f.o.CONTAINER,'python3','-c',script],capture_output=True,text=True).stdout)
assert actual==archived
assert 'image: '+image in (f.o.ROOT/'compose.reports-qa.yaml').read_text()
f.save('engine-proof.json',{'image':image,'native_source_archive':str(archive),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
 'archive_bytes':archive.stat().st_size,'critical_file_sha256':archived,'matches_running_container':True,
 'authority':'Pinned image and archived source; the differently-versioned local odoo Git checkout is not this release engine.'})
print('Pinned runtime and archive verified',archive.stat().st_size)
