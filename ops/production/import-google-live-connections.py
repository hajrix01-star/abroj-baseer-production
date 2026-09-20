#!/usr/bin/env python3
"""Operator-only, one-time production migration for approved Google links.

Run on the production host after the release containing this file is active.
It transfers only the fixed allowlist in the paired target importer.  Secrets
are read into process memory, never printed, never placed in Git, shell
arguments or temporary files.  The legacy container decrypts the refresh token
and sends an envelope encrypted to a new production-only RSA key.
"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path


SOURCE_WEB = "arzobs_prod_web"
SOURCE_DB = "arzobs_prod_postgres"
TARGET_ODOO = "baseer-odoo-prod-odoo-1"
TARGET_DB = "baseer-odoo-prod-db-1"
TARGET_DATABASE = "baseer_prod"
PLANS = ("ads_arz", "ads_shami", "gbp_arz", "gbp_shami")
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


def target_database_credentials():
    raw = run(["docker", "exec", TARGET_DB, "sh", "-lc", 'printf "%s\\n%s" "$POSTGRES_USER" "$POSTGRES_PASSWORD"'])
    user, password = raw.decode("utf-8").split("\n", 1)
    if not user or not password:
        raise RuntimeError("target_database_credentials_missing")
    return user, password


def read_dotenv(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            result[key] = value
    return result


def replace_dotenv(path, updates):
    backup = path.with_name(".env.before-google-live-import-%s" % time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    shutil.copy2(path, backup)
    os.chmod(backup, 0o600)
    existing = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rewritten = []
    for line in existing:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0]
            if key in remaining:
                rewritten.append(key + "=" + remaining.pop(key))
                continue
        rewritten.append(line)
    rewritten.extend(key + "=" + value for key, value in remaining.items())
    temporary = path.with_suffix(".next")
    temporary.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def make_key_pair():
    code = "from cryptography.hazmat.primitives.asymmetric import rsa;from cryptography.hazmat.primitives import serialization;import base64,json;k=rsa.generate_private_key(public_exponent=65537,key_size=3072);print(json.dumps({'private':base64.b64encode(k.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())).decode(),'public':k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()}))"
    return json.loads(run(["docker", "exec", TARGET_ODOO, "python3", "-c", code]).decode("utf-8"))


def public_key_for(env_values):
    private = env_values.get("BASEER_GINT_IMPORT_PRIVATE_KEY_B64")
    if not private:
        return make_key_pair()
    code = "from cryptography.hazmat.primitives import serialization;import base64,json,sys;k=serialization.load_pem_private_key(base64.b64decode(sys.stdin.buffer.read()),password=None);print(json.dumps({'private':None,'public':k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()}))"
    derived = json.loads(run(["docker", "exec", "-i", TARGET_ODOO, "python3", "-c", code], input_data=private.encode("ascii")).decode("utf-8"))
    return derived


def source_record(legacy_id):
    query = "SELECT i.id,i.external_account_id,c.encrypted_payload,c.initialization_vector,c.authentication_tag,c.key_version FROM integration_connections i JOIN integration_credentials c ON c.connection_id=i.id WHERE i.id='%s' AND i.status='active'" % legacy_id
    raw = run(["docker", "exec", SOURCE_DB, "sh", "-lc", 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "\\t" -c "%s"' % query])
    parts = raw.decode("utf-8").rstrip("\n").split("\t")
    if len(parts) != 6 or parts[0] != legacy_id:
        raise RuntimeError("approved_legacy_record_missing")
    return {"legacy_connection_id": parts[0], "external_account_id": parts[1], "encrypted_payload": parts[2], "initialization_vector": parts[3], "authentication_tag": parts[4], "key_version": parts[5]}


def import_one(plan, public_key, db_user, db_password, script_dir):
    record = source_record(LEGACY_IDS[plan])
    if record["external_account_id"] != PUBLIC_AAD[plan]["external_account_id"]:
        raise RuntimeError("legacy_account_mapping_rejected")
    payload = dict(record, public_key_pem=public_key, aad=PUBLIC_AAD[plan])
    legacy_script = script_dir / "legacy_google_envelope.js"
    run(["docker", "cp", str(legacy_script), SOURCE_WEB + ":/tmp/baseer-legacy-google-envelope.js"])
    try:
        envelope = run(["docker", "exec", "-i", SOURCE_WEB, "node", "/tmp/baseer-legacy-google-envelope.js"], input_data=json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    finally:
        run(["docker", "exec", SOURCE_WEB, "rm", "-f", "/tmp/baseer-legacy-google-envelope.js"])
    importer = "/mnt/baseer-addons/baseer_google_ads/scripts/secure_live_connection_import.py"
    result = run([
        "docker", "exec", "-i", "-e", "PGHOST=db", "-e", "PGPORT=5432", "-e", "PGDATABASE=" + TARGET_DATABASE,
        "-e", "PGUSER=" + db_user, "-e", "PGPASSWORD=" + db_password, TARGET_ODOO, "python3", importer, "--plan", plan,
    ], input_data=envelope)
    if result.strip() != b"secure_live_import_succeeded":
        raise RuntimeError("target_import_receipt_missing")


def main():
    if os.geteuid() != 0:
        raise RuntimeError("root_operator_required")
    release_dir = Path(__file__).resolve().parents[2]
    env_path = release_dir / ".env"
    compose_path = release_dir / "compose.production.yaml"
    if not env_path.is_file() or not compose_path.is_file():
        raise RuntimeError("current_release_configuration_missing")
    source = docker_env(SOURCE_WEB, ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_ADS_CLIENT_ID", "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_DEVELOPER_TOKEN"])
    current = read_dotenv(env_path)
    key_pair = public_key_for(current)
    updates = {
        # Master keys are generated only on first use.  A retry must retain a
        # key that already protects a successfully imported target row.
        "BASEER_GBP_CREDENTIAL_MASTER_KEY_B64": current.get("BASEER_GBP_CREDENTIAL_MASTER_KEY_B64") or base64.b64encode(secrets.token_bytes(48)).decode("ascii"),
        "BASEER_GBP_GOOGLE_CLIENT_ID_B64": base64.b64encode(source["GOOGLE_CLIENT_ID"].encode("utf-8")).decode("ascii"),
        "BASEER_GBP_GOOGLE_CLIENT_SECRET_B64": base64.b64encode(source["GOOGLE_CLIENT_SECRET"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_CREDENTIAL_MASTER_KEY_B64": current.get("BASEER_GADS_CREDENTIAL_MASTER_KEY_B64") or base64.b64encode(secrets.token_bytes(48)).decode("ascii"),
        "BASEER_GADS_GOOGLE_CLIENT_ID_B64": base64.b64encode(source["GOOGLE_ADS_CLIENT_ID"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_GOOGLE_CLIENT_SECRET_B64": base64.b64encode(source["GOOGLE_ADS_CLIENT_SECRET"].encode("utf-8")).decode("ascii"),
        "BASEER_GADS_DEVELOPER_TOKEN_B64": base64.b64encode(source["GOOGLE_ADS_DEVELOPER_TOKEN"].encode("utf-8")).decode("ascii"),
    }
    if key_pair["private"]:
        updates["BASEER_GINT_IMPORT_PRIVATE_KEY_B64"] = key_pair["private"]
    replace_dotenv(env_path, updates)
    run(["docker", "compose", "--env-file", ".env", "-f", str(compose_path), "up", "-d", "--force-recreate", "odoo"])
    db_user, db_password = target_database_credentials()
    script_dir = release_dir / "custom_addons" / "baseer_google_ads" / "scripts"
    for plan in PLANS:
        import_one(plan, key_pair["public"], db_user, db_password, script_dir)
    sync_file = "/mnt/baseer-addons/baseer_google_ads/scripts/live_google_read_sync.py"
    run([
        "docker", "exec", "-i", "-e", "PGPASSWORD=" + db_password, TARGET_ODOO, "odoo", "shell", "-d", TARGET_DATABASE, "--no-http", "--db_host=db",
        "--db_user=" + db_user,
        "--addons-path=/mnt/baseer-addons,/mnt/third-party-addons,/mnt/extra-addons", "--shell-interface=python", "--shell-file=" + sync_file,
    ], input_data=b"")
    print("google_live_connections_migrated_and_read_verified")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("google_live_connection_migration_failed", file=sys.stderr)
        raise SystemExit(1)
