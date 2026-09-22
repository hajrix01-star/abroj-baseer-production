#!/usr/bin/env python3
"""Operator-only, one-time production migration for approved Google links.

Google secrets live in an Odoo-only, read-only mount.  The database container
never receives them.  The temporary RSA key crosses only a single stdin pipe.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

SOURCE_WEB = "arzobs_prod_web"
SOURCE_DB = "arzobs_prod_postgres"
TARGET_ODOO = "baseer-odoo-prod-odoo-1"
PLANS = ("ads_arz", "ads_shami", "gbp_arz", "gbp_shami")
SECRET_DIRECTORY = Path("/srv/abroj-baseer-production/secrets/google")
LEGACY_IDS = {
    "ads_arz": "b0106731-9fc6-457d-9cc1-20b9d1d7356f",
    "ads_shami": "43859b29-a24f-4030-8e4e-24ce52c7cb7e",
    "gbp_arz": "9c90a65b-a8ee-42c1-8c18-41defe9ef755",
    "gbp_shami": "61b7f19f-ba8a-424b-bef6-1cbfa4861316",
}
PUBLIC_AAD = {
    "ads_arz": {"company_id": "1", "environment": "production", "external_account_id": "6990834484", "external_location_id": "", "legacy_connection_id": LEGACY_IDS["ads_arz"], "provider": "google_ads", "customer_id": "6990834484"},
    "ads_shami": {"company_id": "2", "environment": "production", "external_account_id": "9359240648", "external_location_id": "", "legacy_connection_id": LEGACY_IDS["ads_shami"], "provider": "google_ads", "customer_id": "9359240648"},
    "gbp_arz": {"company_id": "1", "environment": "production", "external_account_id": "accounts/112701280853663854745", "external_location_id": "locations/11624841135535258675", "legacy_connection_id": LEGACY_IDS["gbp_arz"], "provider": "google_business_profile", "customer_id": ""},
    "gbp_shami": {"company_id": "2", "environment": "production", "external_account_id": "accounts/115474462827251375725", "external_location_id": "locations/4024938756867341253", "legacy_connection_id": LEGACY_IDS["gbp_shami"], "provider": "google_business_profile", "customer_id": ""},
}


def run(args, *, input_data=None):
    result = subprocess.run(args, input=input_data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError("production_migration_subprocess_failed")
    return result.stdout


def docker_env(container, names):
    expression = "const n=%s;const r={};for(const k of n){if(!process.env[k])process.exit(2);r[k]=process.env[k]}process.stdout.write(Buffer.from(JSON.stringify(r)).toString('base64'))" % json.dumps(names)
    raw = run(["docker", "exec", container, "node", "-e", expression]).decode("ascii")
    return json.loads(base64.b64decode(raw, validate=True).decode("utf-8"))


def _read_secret_file(name):
    path = SECRET_DIRECTORY / name
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def _write_secret_file(name, value):
    SECRET_DIRECTORY.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(SECRET_DIRECTORY, 0o700)
    target = SECRET_DIRECTORY / name
    temporary = SECRET_DIRECTORY / (".%s.next" % name)
    descriptor = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as secret_file:
            secret_file.write(value + "\n")
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _secret_value(name):
    current = _read_secret_file(name + "_B64")
    return current if current else base64.b64encode(secrets.token_bytes(48)).decode("ascii")


def configure_odoo_only_secrets(source):
    values = {
        "BASEER_GBP_CREDENTIAL_MASTER_KEY_B64": _secret_value("BASEER_GBP_CREDENTIAL_MASTER_KEY"),
        "BASEER_GBP_GOOGLE_CLIENT_ID_B64": base64.b64encode(source["GOOGLE_CLIENT_ID"].encode("utf-8")).decode("ascii"),
        "BASEER_GBP_GOOGLE_CLIENT_SECRET_B64": base64.b64encode(source["GOOGLE_CLIENT_SECRET"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_CREDENTIAL_MASTER_KEY_B64": _secret_value("BASEER_GADS_CREDENTIAL_MASTER_KEY"),
        "BASEER_GADS_GOOGLE_CLIENT_ID_B64": base64.b64encode(source["GOOGLE_ADS_CLIENT_ID"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_GOOGLE_CLIENT_SECRET_B64": base64.b64encode(source["GOOGLE_ADS_CLIENT_SECRET"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_DEVELOPER_TOKEN_B64": base64.b64encode(source["GOOGLE_ADS_DEVELOPER_TOKEN"].encode("utf-8")).decode("ascii"),
    }
    for name, value in values.items():
        _write_secret_file(name, value)


def make_key_pair():
    code = "from cryptography.hazmat.primitives.asymmetric import rsa;from cryptography.hazmat.primitives import serialization;import base64,json;k=rsa.generate_private_key(public_exponent=65537,key_size=3072);print(json.dumps({'private':base64.b64encode(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode(),'public':k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()}))"
    return json.loads(run(["docker", "exec", TARGET_ODOO, "python3", "-c", code]).decode("utf-8"))


def source_record(legacy_id):
    query = "SELECT i.id,i.external_account_id,c.encrypted_payload,c.initialization_vector,c.authentication_tag,c.key_version FROM integration_connections i JOIN integration_credentials c ON c.connection_id=i.id WHERE i.id='%s' AND i.status='active'" % legacy_id
    raw = run(["docker", "exec", SOURCE_DB, "sh", "-lc", 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "\\t" -c "%s"' % query])
    parts = raw.decode("utf-8").rstrip("\n").split("\t")
    if len(parts) != 6 or parts[0] != legacy_id:
        raise RuntimeError("approved_legacy_record_missing")
    return {"legacy_connection_id": parts[0], "external_account_id": parts[1], "encrypted_payload": parts[2], "initialization_vector": parts[3], "authentication_tag": parts[4], "key_version": parts[5]}


def run_odoo_shell(script, *, input_data=None):
    """Use a 0600 DB config constructed inside Odoo; no host-side secret argv."""
    command = (
        "set -eu; umask 077; cfg=$(mktemp /tmp/baseer-google-live.XXXXXX); "
        "trap 'rm -f \"$cfg\"' EXIT; "
        "printf '[options]\\ndb_host = %s\\ndb_port = 5432\\ndb_user = %s\\ndb_password = %s\\n' \"$HOST\" \"$USER\" \"$PASSWORD\" > \"$cfg\"; "
        "odoo shell --config=\"$cfg\" -d baseer_prod --no-http "
        "--addons-path=/mnt/baseer-addons,/mnt/third-party-addons,/mnt/extra-addons "
        "--shell-interface=python --shell-file=" + script
    )
    return run(["docker", "exec", "-i", TARGET_ODOO, "sh", "-lc", command], input_data=input_data)


def import_one(plan, key_pair, script_dir):
    record = source_record(LEGACY_IDS[plan])
    if record["external_account_id"] != PUBLIC_AAD[plan]["external_account_id"]:
        raise RuntimeError("legacy_account_mapping_rejected")
    payload = dict(record, public_key_pem=key_pair["public"], aad=PUBLIC_AAD[plan])
    legacy_script = script_dir / "legacy_google_envelope.js"
    run(["docker", "cp", str(legacy_script), SOURCE_WEB + ":/tmp/baseer-legacy-google-envelope.js"])
    try:
        envelope = run(["docker", "exec", "-i", SOURCE_WEB, "node", "/tmp/baseer-legacy-google-envelope.js"], input_data=json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    finally:
        run(["docker", "exec", SOURCE_WEB, "rm", "-f", "/tmp/baseer-legacy-google-envelope.js"])
    frame = json.dumps({"plan": plan, "private_key_b64": key_pair["private"], "envelope": json.loads(envelope.decode("utf-8"))}, separators=(",", ":")).encode("utf-8")
    importer = "/mnt/baseer-addons/baseer_google_ads/scripts/secure_live_connection_import.py"
    result = run_odoo_shell(importer, input_data=frame)
    if b"secure_live_import_succeeded" not in result:
        raise RuntimeError("target_import_receipt_missing")


def disable_all_imports():
    importer = "/mnt/baseer-addons/baseer_google_ads/scripts/secure_live_connection_import.py"
    for plan in PLANS:
        run_odoo_shell(importer, input_data=json.dumps({"plan": plan, "mode": "disable"}).encode("utf-8"))


def run_first_read_verification():
    result = run_odoo_shell("/mnt/baseer-addons/baseer_google_ads/scripts/live_google_read_sync.py")
    if b"live_google_read_sync_succeeded" not in result:
        raise RuntimeError("initial_read_receipt_missing")


def main():
    if os.geteuid() != 0:
        raise RuntimeError("root_operator_required")
    release_dir = Path(__file__).resolve().parents[2]
    compose_path = release_dir / "compose.production.yaml"
    if not compose_path.is_file():
        raise RuntimeError("current_release_configuration_missing")
    source = docker_env(SOURCE_WEB, ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_DEVELOPER_TOKEN"])
    try:
        configure_odoo_only_secrets(source)
        run(["docker", "compose", "--env-file", ".env", "-f", str(compose_path), "up", "-d", "--force-recreate", "odoo"])
        key_pair = make_key_pair()
        try:
            for plan in PLANS:
                import_one(plan, key_pair, release_dir / "custom_addons" / "baseer_google_ads" / "scripts")
            run_first_read_verification()
        finally:
            key_pair["private"] = None
    except Exception:
        disable_all_imports()
        raise
    finally:
        source.clear()
    print("google_live_connections_migrated_and_read_verified")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("google_live_connection_migration_failed", file=sys.stderr)
        raise SystemExit(1)
