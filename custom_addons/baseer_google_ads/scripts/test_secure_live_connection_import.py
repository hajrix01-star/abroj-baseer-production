import base64
import importlib.util
import io
import json
import os
import sys
import types
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


fake_odoo = types.ModuleType("odoo")
fake_odoo.SUPERUSER_ID = 1
fake_odoo.api = types.SimpleNamespace()
sys.modules.setdefault("odoo", fake_odoo)
SCRIPT = Path(__file__).with_name("secure_live_connection_import.py")
SPEC = importlib.util.spec_from_file_location("secure_live_connection_import", SCRIPT)
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


class EnvelopeContractTest(unittest.TestCase):
    def setUp(self):
        self.plan = IMPORTER.PLANS["ads_arz"]
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        private_pem = self.private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        self.private_b64 = base64.b64encode(private_pem).decode("ascii")

    def envelope(self, aad=None):
        aad = aad or IMPORTER._aad(self.plan)
        aad_bytes = IMPORTER._canonical(aad)
        payload = json.dumps({"provider": self.plan["provider"], "legacy_connection_id": self.plan["legacy_connection_id"], "customer_id": self.plan["customer_id"], "refresh_token": "test-refresh-token", "login_customer_id": ""}).encode("utf-8")
        data_key, nonce = b"x" * 32, b"y" * 12
        encrypted = AESGCM(data_key).encrypt(nonce, payload, aad_bytes)
        public_pem = self.private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        wrapped = serialization.load_pem_public_key(public_pem).encrypt(data_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        return {"aad": base64.b64encode(aad_bytes).decode(), "wrapped_key": base64.b64encode(wrapped).decode(), "nonce": base64.b64encode(nonce).decode(), "ciphertext": base64.b64encode(encrypted[:-16]).decode(), "tag": base64.b64encode(encrypted[-16:]).decode()}

    def read(self, envelope):
        previous = sys.stdin
        try:
            frame = {"plan": "ads_arz", "private_key_b64": self.private_b64, "envelope": envelope}
            sys.stdin = io.TextIOWrapper(io.BytesIO(json.dumps(frame).encode("utf-8")), encoding="utf-8")
            parsed, plan = IMPORTER._read_frame()
            return IMPORTER._open_envelope(plan, parsed)
        finally:
            sys.stdin = previous

    def test_accepts_exactly_bound_envelope(self):
        self.assertEqual(self.read(self.envelope())["refresh_token"], "test-refresh-token")

    def test_rejects_other_company_binding(self):
        wrong = IMPORTER._aad(self.plan)
        wrong["company_id"] = "2"
        with self.assertRaisesRegex(RuntimeError, "binding_rejected"):
            self.read(self.envelope(wrong))


if __name__ == "__main__":
    unittest.main()
