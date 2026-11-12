"""One-use Odoo-shell importer for the approved production Google links.

This file is executed only by the root-owned operator through ``odoo shell``.
It relies on Odoo's ORM and SUPERUSER_ID, not direct SQL or database superuser
credentials.  Its input is an authenticated envelope plus a private RSA key
on stdin; neither value is persisted by this script.
"""
import base64
import hashlib
import json
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from odoo import SUPERUSER_ID, api


PLANS = {
    "ads_arz": {"provider": "google_ads", "company_id": 1, "name": "ARZ", "legacy_connection_id": "b0106731-9fc6-457d-9cc1-20b9d1d7356f", "external_account_id": "6990834484", "customer_id": "6990834484", "external_location_id": ""},
    "ads_shami": {"provider": "google_ads", "company_id": 2, "name": "SHAMI", "legacy_connection_id": "43859b29-a24f-4030-8e4e-24ce52c7cb7e", "external_account_id": "9359240648", "customer_id": "9359240648", "external_location_id": ""},
    "gbp_arz": {"provider": "google_business_profile", "company_id": 1, "name": "Arz restaurant", "legacy_connection_id": "9c90a65b-a8ee-42c1-8c18-41defe9ef755", "external_account_id": "accounts/112701280853663854745", "external_location_id": "locations/11624841135535258675", "google_location_name": "locations/11624841135535258675", "google_place_id": "ChIJ52--_KrnST4RUnHwNxwIhPQ"},
    "gbp_shami": {"provider": "google_business_profile", "company_id": 2, "name": "المعلم الشامي", "legacy_connection_id": "61b7f19f-ba8a-424b-bef6-1cbfa4861316", "external_account_id": "accounts/115474462827251375725", "external_location_id": "locations/4024938756867341253", "google_location_name": "locations/4024938756867341253", "google_place_id": "ChIJhaE1nEDnST4RfCKiTucdJGo"},
}


def _aad(plan):
    return {
        "company_id": str(plan["company_id"]), "environment": "production",
        "external_account_id": plan["external_account_id"], "external_location_id": plan["external_location_id"],
        "legacy_connection_id": plan["legacy_connection_id"], "provider": plan["provider"],
        "customer_id": plan.get("customer_id", ""),
    }


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _read_frame():
    frame = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    plan = PLANS.get(frame.get("plan"))
    if not plan:
        raise RuntimeError("migration_plan_rejected")
    return frame, plan


def _open_envelope(plan, frame):
    envelope = frame["envelope"]
    expected_aad = _canonical(_aad(plan))
    if base64.b64decode(envelope["aad"], validate=True) != expected_aad:
        raise RuntimeError("envelope_binding_rejected")
    private_key = serialization.load_pem_private_key(
        base64.b64decode(frame["private_key_b64"], validate=True), password=None,
    )
    data_key = private_key.decrypt(
        base64.b64decode(envelope["wrapped_key"], validate=True),
        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
    )
    if len(data_key) != 32:
        raise RuntimeError("envelope_key_rejected")
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True) + base64.b64decode(envelope["tag"], validate=True)
    payload = json.loads(AESGCM(data_key).decrypt(base64.b64decode(envelope["nonce"], validate=True), ciphertext, expected_aad).decode("utf-8"))
    if payload.get("provider") != plan["provider"] or payload.get("legacy_connection_id") != plan["legacy_connection_id"]:
        raise RuntimeError("envelope_identity_rejected")
    if plan["provider"] == "google_ads" and payload.get("customer_id") != plan["customer_id"]:
        raise RuntimeError("envelope_customer_rejected")
    if not isinstance(payload.get("refresh_token"), str) or not payload["refresh_token"]:
        raise RuntimeError("envelope_payload_rejected")
    return payload


def _import_ads(secure_env, plan, payload):
    Connection = secure_env["baseer.gads.connection"]
    record = Connection.search([("legacy_connection_id", "=", plan["legacy_connection_id"])], limit=1)
    if record and (record.state != "pending" or record.company_id.id != plan["company_id"] or record.customer_id != plan["customer_id"]):
        raise RuntimeError("target_replay_or_mapping_rejected")
    if not record:
        record = Connection.create({
            "company_id": plan["company_id"], "name": plan["name"],
            "legacy_connection_id": plan["legacy_connection_id"], "customer_id": plan["customer_id"],
            "login_customer_id": payload.get("login_customer_id") or False, "state": "pending",
        })
    record._secure_import_refresh_token(payload["refresh_token"], key_version="live-envelope-r1")
    return record


def _import_gbp(secure_env, plan, payload):
    Connection = secure_env["baseer.gbp.connection"]
    record = Connection.search([("external_connection_id", "=", plan["legacy_connection_id"])], limit=1)
    if record and (record.state != "pending" or record.company_id.id != plan["company_id"] or record.external_account_id != plan["external_account_id"]):
        raise RuntimeError("target_replay_or_mapping_rejected")
    if not record:
        record = Connection.create({
            "company_id": plan["company_id"], "name": plan["name"],
            "external_connection_id": plan["legacy_connection_id"], "external_account_id": plan["external_account_id"],
            "state": "pending", "writer_enabled": False,
        })
    Location = secure_env["baseer.gbp.location"]
    location = Location.search([("external_location_id", "=", plan["external_location_id"])], limit=1)
    if location and (location.company_id.id != plan["company_id"] or location.connection_id != record):
        raise RuntimeError("target_location_mapping_rejected")
    if not location:
        Location.create({
            "company_id": plan["company_id"], "connection_id": record.id, "name": plan["name"],
            "external_location_id": plan["external_location_id"], "google_location_name": plan["google_location_name"],
            "google_place_id": plan["google_place_id"], "state": "draft", "active": True,
        })
    record._secure_import_refresh_token(payload["refresh_token"], key_version="live-envelope-r1")
    return record


def _disable(secure_env, plan):
    field = "legacy_connection_id" if plan["provider"] == "google_ads" else "external_connection_id"
    model = "baseer.gads.connection" if plan["provider"] == "google_ads" else "baseer.gbp.connection"
    record = secure_env[model].search([(field, "=", plan["legacy_connection_id"]), ("token_key_version", "=", "live-envelope-r1")])
    if record:
        values = {"state": "attention", "token_nonce": False, "token_ciphertext": False, "token_key_version": False, "last_error_code": "initial_read_failed"}
        if plan["provider"] == "google_business_profile":
            values["writer_enabled"] = False
        context_key = "gads_internal_secret_write" if plan["provider"] == "google_ads" else "gbp_internal_secret_write"
        record.with_context(**{context_key: True, "gbp_internal_writer_audit": True}).write(values)


def main():
    frame, plan = _read_frame()
    secure_env = api.Environment(env.cr, SUPERUSER_ID, dict(env.context))
    if frame.get("mode") == "disable":
        _disable(secure_env, plan)
        env.cr.commit()
        print("secure_live_import_disabled")
        return
    payload = _open_envelope(plan, frame)
    record = _import_ads(secure_env, plan, payload) if plan["provider"] == "google_ads" else _import_gbp(secure_env, plan, payload)
    receipt = hashlib.sha256(_canonical(_aad(plan)) + str(record.id).encode("ascii")).hexdigest()[:16]
    # The model's audit entry contains no token; this receipt only binds the approved plan.
    print("secure_live_import_succeeded", receipt)
    env.cr.commit()


if "env" in globals():
    try:
        main()
    except Exception:
        env.cr.rollback()
        print("secure_live_import_failed", file=sys.stderr)
        raise
