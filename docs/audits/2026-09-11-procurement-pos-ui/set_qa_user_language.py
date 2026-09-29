"""Temporarily switch the QA Administrator language for bilingual UI proof."""

import os
import xmlrpc.client


url = os.environ.get("BASEER_QA_URL", "http://127.0.0.1:18081")
language = os.environ["BASEER_QA_LANGUAGE"]
db = "baseer_procurement_qa_20260911"
username = os.environ.get("BASEER_QA_USER", "admin")
password = os.environ["BASEER_QA_PASSWORD"]
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
before = models.execute_kw(db, uid, password, "res.users", "read", [[uid], ["lang"]])[0]["lang"]
models.execute_kw(db, uid, password, "res.users", "write", [[uid], {"lang": language}])
print(f"language={before}->{language}")
