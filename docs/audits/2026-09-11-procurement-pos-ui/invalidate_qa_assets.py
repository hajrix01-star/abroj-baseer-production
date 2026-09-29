"""Invalidate only generated Odoo web-asset attachments in procurement QA."""

import os
import xmlrpc.client


url = os.environ.get("BASEER_QA_URL", "http://127.0.0.1:18081")
db = "baseer_procurement_qa_20260911"
username = os.environ.get("BASEER_QA_USER", "admin")
password = os.environ["BASEER_QA_PASSWORD"]
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
domain = ["|", ["url", "like", "/web/assets/%"], ["name", "like", "web.assets_%"]]
ids = models.execute_kw(db, uid, password, "ir.attachment", "search", [domain])
if ids:
    models.execute_kw(db, uid, password, "ir.attachment", "unlink", [ids])
print(f"invalidated_generated_assets={len(ids)}")
