"""One-time server-side Google Ads credential bridge for QA.

The program accepts an authenticated sealed message on stdin, validates the
public source identity against a pending target row, then encrypts the refresh
token directly with the QA credential key. It never writes or prints a plain
credential, and it only opens a local connection to the QA database.
"""

import base64
import hashlib
import json
import os
import sys

import psycopg2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _decoded_environment(name):
    encoded = os.environ.get(name + "_B64")
    if not encoded:
        raise RuntimeError(name.lower() + "_missing")
    return base64.b64decode(encoded, validate=True).decode("utf-8")


def _bridge_key():
    key = base64.b64decode(os.environ["BASEER_GADS_IMPORT_BRIDGE_KEY_B64"], validate=True)
    if len(key) != 32:
        raise RuntimeError("bridge_key_invalid")
    return key


def _payload():
    raw = sys.stdin.buffer.read().decode("ascii").strip()
    nonce_b64, ciphertext_b64 = raw.split(".", 1)
    value = AESGCM(_bridge_key()).decrypt(
        base64.b64decode(nonce_b64, validate=True),
        base64.b64decode(ciphertext_b64, validate=True),
        None,
    )
    payload = json.loads(value.decode("utf-8"))
    required = ("legacy_connection_id", "customer_id", "refresh_token")
    if not all(isinstance(payload.get(key), str) and payload[key] for key in required):
        raise RuntimeError("bridge_payload_invalid")
    return payload


def _encrypt_refresh_token(value):
    key = hashlib.sha256(_decoded_environment("BASEER_GADS_CREDENTIAL_MASTER_KEY").encode("utf-8")).digest()
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce).decode("ascii"), base64.b64encode(ciphertext).decode("ascii")


def main():
    payload = _payload()
    nonce, ciphertext = _encrypt_refresh_token(payload["refresh_token"])
    database = os.environ["BASEER_GADS_IMPORT_DATABASE"]
    with psycopg2.connect(
        dbname=database,
        host=os.environ["HOST"],
        user=os.environ["USER"],
        password=os.environ["PASSWORD"],
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, company_id FROM baseer_gads_connection
                WHERE legacy_connection_id = %s AND customer_id = %s AND state = 'pending'
                FOR UPDATE
                """,
                (payload["legacy_connection_id"], payload["customer_id"]),
            )
            target = cursor.fetchone()
            if not target:
                raise RuntimeError("target_connection_not_pending")
            target_id, company_id = target
            cursor.execute(
                """
                UPDATE baseer_gads_connection
                   SET token_nonce = %s, token_ciphertext = %s,
                       token_key_version = 'qa-bridge-v1', state = 'active',
                       last_error_at = NULL, last_error_code = NULL,
                       login_customer_id = COALESCE(%s, login_customer_id),
                       write_uid = 1, write_date = NOW()
                 WHERE id = %s
                """,
                (nonce, ciphertext, payload.get("login_customer_id"), target_id),
            )
            cursor.execute(
                """
                INSERT INTO baseer_gads_audit
                    (company_id, connection_id, event, detail, create_uid, write_uid, create_date, write_date)
                VALUES (%s, %s, 'credential_imported', 'Server-side secure import completed.', 1, 1, NOW(), NOW())
                """,
                (company_id, target_id),
            )
    sys.stdout.write("secure_import_succeeded\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("secure_import_failed\n")
        raise SystemExit(1)
