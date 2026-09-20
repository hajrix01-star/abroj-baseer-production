"""Trusted one-time production importer for approved Google connections.

It only accepts an authenticated envelope produced by ``legacy_google_envelope``.
The plan is an immutable allowlist; envelope metadata is authenticated as AES-GCM
AAD and therefore cannot be replayed to another company, provider or location.
No refresh token or OAuth client secret is printed or stored in this source.
"""
import argparse
import base64
import hashlib
import json
import os
import sys

import psycopg2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PLANS = {
    "ads_arz": {
        "provider": "google_ads", "company_id": 1, "name": "ARZ",
        "legacy_connection_id": "b0106731-9fc6-457d-9cc1-20b9d1d7356f",
        "external_account_id": "6990834484", "customer_id": "6990834484", "external_location_id": "",
    },
    "ads_shami": {
        "provider": "google_ads", "company_id": 2, "name": "SHAMI",
        "legacy_connection_id": "43859b29-a24f-4030-8e4e-24ce52c7cb7e",
        "external_account_id": "9359240648", "customer_id": "9359240648", "external_location_id": "",
    },
    "gbp_arz": {
        "provider": "google_business_profile", "company_id": 1, "name": "Arz restaurant",
        "legacy_connection_id": "9c90a65b-a8ee-42c1-8c18-41defe9ef755",
        "external_account_id": "accounts/112701280853663854745",
        "external_location_id": "locations/11624841135535258675",
        "google_location_name": "locations/11624841135535258675",
        "google_place_id": "ChIJ52--_KrnST4RUnHwNxwIhPQ",
    },
    "gbp_shami": {
        "provider": "google_business_profile", "company_id": 2, "name": "المعلم الشامي",
        "legacy_connection_id": "61b7f19f-ba8a-424b-bef6-1cbfa4861316",
        "external_account_id": "accounts/115474462827251375725",
        "external_location_id": "locations/4024938756867341253",
        "google_location_name": "locations/4024938756867341253",
        "google_place_id": "ChIJhaE1nEDnST4RfCKiTucdJGo",
    },
}


def _secret(name):
    encoded = os.environ.get(name + "_B64")
    if encoded:
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("required_runtime_secret_missing")
    return value


def _aad(plan):
    return {
        "company_id": str(plan["company_id"]), "environment": "production",
        "external_account_id": plan["external_account_id"],
        "external_location_id": plan["external_location_id"],
        "legacy_connection_id": plan["legacy_connection_id"],
        "provider": plan["provider"], "customer_id": plan.get("customer_id", ""),
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _open_envelope(plan):
    envelope = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    encoded_aad = base64.b64decode(envelope["aad"], validate=True)
    expected_aad = _canonical(_aad(plan))
    if encoded_aad != expected_aad:
        raise RuntimeError("envelope_binding_rejected")
    private_key = serialization.load_pem_private_key(
        base64.b64decode(os.environ["BASEER_GINT_IMPORT_PRIVATE_KEY_B64"], validate=True), password=None,
    )
    data_key = private_key.decrypt(
        base64.b64decode(envelope["wrapped_key"], validate=True),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    if len(data_key) != 32:
        raise RuntimeError("envelope_key_rejected")
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True) + base64.b64decode(envelope["tag"], validate=True)
    value = AESGCM(data_key).decrypt(base64.b64decode(envelope["nonce"], validate=True), ciphertext, expected_aad)
    payload = json.loads(value.decode("utf-8"))
    if payload.get("provider") != plan["provider"] or payload.get("legacy_connection_id") != plan["legacy_connection_id"]:
        raise RuntimeError("envelope_identity_rejected")
    if plan["provider"] == "google_ads" and payload.get("customer_id") != plan["customer_id"]:
        raise RuntimeError("envelope_customer_rejected")
    if not isinstance(payload.get("refresh_token"), str) or not payload["refresh_token"]:
        raise RuntimeError("envelope_payload_rejected")
    return payload


def _encrypt(token, env_key_name):
    key = hashlib.sha256(_secret(env_key_name).encode("utf-8")).digest()
    nonce = os.urandom(12)
    return base64.b64encode(nonce).decode("ascii"), base64.b64encode(AESGCM(key).encrypt(nonce, token.encode("utf-8"), None)).decode("ascii")


def _connection(cursor, plan, nonce, ciphertext, payload):
    cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [plan["legacy_connection_id"]])
    if plan["provider"] == "google_ads":
        cursor.execute("SELECT id, state, company_id, customer_id FROM baseer_gads_connection WHERE legacy_connection_id=%s FOR UPDATE", [plan["legacy_connection_id"]])
        existing = cursor.fetchone()
        if existing and (existing[1] != "pending" or existing[2] != plan["company_id"] or existing[3] != plan["customer_id"]):
            raise RuntimeError("target_replay_or_mapping_rejected")
        if existing:
            connection_id = existing[0]
            cursor.execute("UPDATE baseer_gads_connection SET token_nonce=%s, token_ciphertext=%s, token_key_version='live-envelope-r1', login_customer_id=%s, state='active', last_error_at=NULL, last_error_code=NULL, write_uid=1, write_date=NOW() WHERE id=%s", [nonce, ciphertext, payload.get("login_customer_id") or None, connection_id])
        else:
            cursor.execute("INSERT INTO baseer_gads_connection (company_id,create_uid,write_uid,name,legacy_connection_id,customer_id,login_customer_id,state,token_nonce,token_ciphertext,token_key_version,create_date,write_date) VALUES (%s,1,1,%s,%s,%s,%s,'active',%s,%s,'live-envelope-r1',NOW(),NOW()) RETURNING id", [plan["company_id"], plan["name"], plan["legacy_connection_id"], plan["customer_id"], payload.get("login_customer_id") or None, nonce, ciphertext])
            connection_id = cursor.fetchone()[0]
        return connection_id, "baseer_gads_audit"

    cursor.execute("SELECT id, state, company_id, external_account_id FROM baseer_gbp_connection WHERE external_connection_id=%s FOR UPDATE", [plan["legacy_connection_id"]])
    existing = cursor.fetchone()
    if existing and (existing[1] != "pending" or existing[2] != plan["company_id"] or existing[3] != plan["external_account_id"]):
        raise RuntimeError("target_replay_or_mapping_rejected")
    if existing:
        connection_id = existing[0]
        cursor.execute("UPDATE baseer_gbp_connection SET token_nonce=%s, token_ciphertext=%s, token_key_version='live-envelope-r1', state='active', writer_enabled=false, last_error_at=NULL, last_error_code=NULL, write_uid=1, write_date=NOW() WHERE id=%s", [nonce, ciphertext, connection_id])
    else:
        cursor.execute("INSERT INTO baseer_gbp_connection (company_id,create_uid,write_uid,name,external_connection_id,external_account_id,state,writer_enabled,token_nonce,token_ciphertext,token_key_version,create_date,write_date) VALUES (%s,1,1,%s,%s,%s,'active',false,%s,%s,'live-envelope-r1',NOW(),NOW()) RETURNING id", [plan["company_id"], plan["name"], plan["legacy_connection_id"], plan["external_account_id"], nonce, ciphertext])
        connection_id = cursor.fetchone()[0]
    cursor.execute("SELECT id, company_id, connection_id FROM baseer_gbp_location WHERE external_location_id=%s FOR UPDATE", [plan["external_location_id"]])
    location = cursor.fetchone()
    if location and (location[1] != plan["company_id"] or location[2] != connection_id):
        raise RuntimeError("target_location_mapping_rejected")
    if not location:
        cursor.execute("INSERT INTO baseer_gbp_location (company_id,connection_id,create_uid,write_uid,name,external_location_id,google_location_name,google_place_id,state,active,create_date,write_date) VALUES (%s,%s,1,1,%s,%s,%s,%s,'draft',true,NOW(),NOW())", [plan["company_id"], connection_id, plan["name"], plan["external_location_id"], plan["google_location_name"], plan["google_place_id"]])
    return connection_id, "baseer_gbp_audit"


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plan", choices=sorted(PLANS), required=True)
    plan = PLANS[parser.parse_args().plan]
    payload = _open_envelope(plan)
    secret_name = "BASEER_GADS_CREDENTIAL_MASTER_KEY" if plan["provider"] == "google_ads" else "BASEER_GBP_CREDENTIAL_MASTER_KEY"
    nonce, ciphertext = _encrypt(payload["refresh_token"], secret_name)
    conn = psycopg2.connect(host=os.environ["PGHOST"], port=os.environ.get("PGPORT", "5432"), dbname=os.environ["PGDATABASE"], user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"])
    try:
        with conn:
            with conn.cursor() as cursor:
                connection_id, audit_table = _connection(cursor, plan, nonce, ciphertext, payload)
                receipt = hashlib.sha256(_canonical(_aad(plan)) + str(connection_id).encode("ascii")).hexdigest()[:16]
                cursor.execute("INSERT INTO " + audit_table + " (company_id,connection_id,event,detail,create_uid,write_uid,create_date,write_date) VALUES (%s,%s,'credential_imported',%s,1,1,NOW(),NOW())", [plan["company_id"], connection_id, "Production envelope import receipt=" + receipt])
        sys.stdout.write("secure_live_import_succeeded\n")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stderr.write("secure_live_import_failed\n")
        raise SystemExit(1)
