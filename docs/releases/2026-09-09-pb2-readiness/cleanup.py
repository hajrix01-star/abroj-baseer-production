"""Remove only the isolated PB2 review runtime after evidence is retained."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'build-governance'))
import pb2_ops as p
assert p.TEST=='baseer_pb2_test_20260909' and p.TEST not in (p.o.QA,'baseer_dev')
assert all(json.loads((p.OUT/'postcheck.json').read_text()).values())
p.o.run(['docker','compose','-f','compose.yaml','-f','compose.pb2-review.yaml','stop','pb2_review'],capture_output=True)
p.o.run(['docker','exec',p.o.DB,'sh','-c','dropdb -U "$POSTGRES_USER" --force '+p.TEST],capture_output=True)
p.o.run(['docker','exec',p.o.CONTAINER,'rm','-rf','/var/lib/odoo/filestore/baseer_pb2_test_20260909'],capture_output=True)
remaining=p.o.sql('postgres',"SELECT count(*) FROM pg_database WHERE datname='baseer_pb2_test_20260909'")
assert remaining=='0'
p.save('cleanup.json',{'review_service_stopped':True,'clone_removed':True,'qa_and_main_retained':True,'backups_and_evidence_retained':True})
