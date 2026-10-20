#!/usr/bin/env bash
# Synthetic Linux CI only. No deploy, service management, arbitrary hook or keys.
set -Eeuo pipefail
umask 022

readonly OLD_SOURCE=3b0feb1aafe41479e4f33378c1745a5b0a96b811
readonly ODOO_IMAGE=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
readonly PG_IMAGE=postgres@sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94
readonly PROBE=/mnt/current-addons/baseer_bwork/tests/canonical_upgrade_probe.py
readonly HOOK=/mnt/current-addons/baseer_bwork/tools/canonical_pre_upgrade.py
readonly FIXTURE_MARKER=BWORK_CANONICAL_EXPECTED_LATE_MODULE_FAILURE
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

die() { printf 'BCR_CI_FAIL: %s\n' "$*" >&2; exit 1; }
db_guard() { [[ "$1" =~ ^bwork_canonical_ci_[a-z0-9_]+$ && ${#1} -le 63 ]] || die 'disposable DB identity required'; }
# Never inherit a remote Docker context/DOCKER_HOST from an operator machine.
docker_local() { command docker --host unix:///var/run/docker.sock "$@"; }

# A syntax/API contract check only; never Docker execution or native acceptance.
check_sources() {
  git -C "$REPO" cat-file -e "$OLD_SOURCE^{commit}"
  for file in custom_addons/baseer_bwork/tests/canonical_upgrade_probe.py \
    custom_addons/baseer_bwork/tools/canonical_pre_upgrade.py \
    ops/tests/fixtures/bwork_canonical_failure/__manifest__.py \
    ops/tests/fixtures/bwork_canonical_failure/hooks.py; do
    [[ -f "$REPO/$file" ]] || die "required source missing: $file"
  done
  python3 - "$REPO" <<'PY'
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])
probe = ast.parse((root / 'custom_addons/baseer_bwork/tests/canonical_upgrade_probe.py').read_text())
names = {n.name for n in probe.body if isinstance(n, ast.FunctionDef)}
required = {'prepare_legacy', 'prepare_legacy_procurement', 'exercise_legacy_rollback', 'verify_upgraded', 'verify_upgraded_procurement', 'verify_fresh', 'verify_legacy_restored'}
assert required <= names, 'Fixed producer/consumer probe API missing: ' + repr(required - names)
for file in (root / 'ops/tests/fixtures/bwork_canonical_failure').glob('*.py'):
    ast.parse(file.read_text(), filename=str(file))
manifest = ast.literal_eval((root / 'ops/tests/fixtures/bwork_canonical_failure/__manifest__.py').read_text())
assert manifest['depends'] == ['baseer_bwork_admin'] and manifest['auto_install'] is False
print('BCR_CI_SOURCE_CHECK_PASS (not a database/runtime result)')
PY
}

if [[ "${1:-}" == --check && $# == 1 ]]; then check_sources; exit 0; fi
[[ $# == 0 ]] || die 'no runtime arguments or arbitrary hooks allowed'
[[ "${BWORK_CANONICAL_SYNTHETIC:-}" == 1 ]] || die 'explicit synthetic marker required'
[[ "$(uname -s)" == Linux ]] || die 'host-network runner is Linux-only'
for command in docker git tar python3 tee grep cmp sha256sum mktemp; do command -v "$command" >/dev/null || die "required command absent: $command"; done
check_sources

readonly RUN_ID="$(date -u +%Y%m%d%H%M%S)_$$"
readonly UPGRADE_DB="bwork_canonical_ci_${RUN_ID}_upgrade"
readonly FRESH_DB="bwork_canonical_ci_${RUN_ID}_fresh"
db_guard "$UPGRADE_DB"; db_guard "$FRESH_DB"
mkdir -p "$REPO/output/bwork-canonical-rename-20261020"
readonly EVIDENCE="$(mktemp -d "$REPO/output/bwork-canonical-rename-20261020/native-ci.XXXXXXXX")"
readonly WORK="$(mktemp -d "${TMPDIR:-/tmp}/bwork-canonical-ci.XXXXXXXX")"
readonly OLD="$WORK/old-source"
readonly DATA="$WORK/odoo-data"
mkdir -p "$OLD" "$DATA/filestore" "$DATA/quarantine"
# Only this newly-created disposable mount needs the Odoo container UID to write.
chmod 0777 "$DATA" "$DATA/filestore" "$DATA/quarantine"
trap 'status=$?; printf "BCR_CI_EXIT=%s EVIDENCE=%s WORK=%s\n" "$status" "$EVIDENCE" "$WORK"; exit "$status"' EXIT
git -C "$REPO" archive "$OLD_SOURCE" custom_addons third_party_addons/odoomates_19 third_party_addons/erp_heritage_19 | tar -xf - -C "$OLD"
[[ -f "$OLD/custom_addons/baseer_bchat/__manifest__.py" ]] || die 'real old addon missing from exact archive'
[[ -f "$OLD/custom_addons/baseer_bwork_admin/__manifest__.py" ]] || die 'real old administration addon missing'
printf '%s\n' "$OLD_SOURCE" > "$EVIDENCE/old-source.txt"
git -C "$REPO" rev-parse HEAD > "$EVIDENCE/current-base.txt"
git -C "$REPO" diff --binary -- custom_addons > "$EVIDENCE/current-addons.patch"
printf 'UPGRADE_DB=%s\nFRESH_DB=%s\nODOO_IMAGE=%s\nPG_IMAGE=%s\n' "$UPGRADE_DB" "$FRESH_DB" "$ODOO_IMAGE" "$PG_IMAGE" > "$EVIDENCE/fixture-identities.txt"

# Fixed dummy CI service credentials only, never sourced from owner configuration.
pg() {
  local program="$1"; shift
  docker_local run --rm -i --network host -e PGHOST=127.0.0.1 -e PGPORT=5432 \
    -e PGUSER=odoo -e PGPASSWORD=odoo \
    --mount "type=bind,src=$EVIDENCE,dst=/evidence,readonly" \
    --entrypoint "$program" "$PG_IMAGE" "$@"
}
odoo_run() {
  local source="$1" db="$2"; shift 2
  db_guard "$db"
  local addons=/mnt/current-addons
  local vendor="$REPO"
  [[ "$source" == current || "$source" == old ]] || die 'unrecognized source profile'
  [[ "$source" != old ]] || addons=/mnt/old-addons
  [[ "$source" != old ]] || vendor="$OLD"
  docker_local run --rm -i --network host \
    -e HOST=127.0.0.1 -e PORT=5432 -e USER=odoo -e PASSWORD=odoo \
    -e BWORK_CANONICAL_SYNTHETIC=1 -e PYTHONDONTWRITEBYTECODE=1 \
    --mount "type=bind,src=$OLD/custom_addons,dst=/mnt/old-addons,readonly" \
    --mount "type=bind,src=$REPO/custom_addons,dst=/mnt/current-addons,readonly" \
    --mount "type=bind,src=$SCRIPT_DIR/fixtures,dst=/mnt/failure-addons,readonly" \
    --mount "type=bind,src=$vendor/third_party_addons/odoomates_19,dst=/mnt/odoomates,readonly" \
    --mount "type=bind,src=$vendor/third_party_addons/erp_heritage_19,dst=/mnt/erp-heritage,readonly" \
    --mount "type=bind,src=$DATA,dst=/var/lib/odoo" \
    "$ODOO_IMAGE" odoo "$@" --db_host=127.0.0.1 --db_port=5432 --db_user=odoo --db_password=odoo \
    --data-dir=/var/lib/odoo --addons-path="/usr/lib/python3/dist-packages/odoo/addons,$addons,/mnt/odoomates,/mnt/erp-heritage,/mnt/failure-addons" \
    -d "$db" --without-demo=all --max-cron-threads=0 --workers=0
}
require_marker() { grep -Fqx "$2" "$1" || die "missing real execution marker: $2"; }
clean_log() {
  if grep -Eiq 'Traceback \(most recent call last\)|CRITICAL|[1-9][0-9]* failed,|[1-9][0-9]* error\(s\)|: skipped .+ : ' "$1"; then die "unexpected error/skip in $1"; fi
}
probe() {
  local source="$1" db="$2" method="$3" log="$4"
  # Fixed API allowlist; function name is not an arbitrary Python or hook input.
  case "$method" in prepare_legacy|exercise_legacy_rollback|verify_upgraded|verify_upgraded_procurement|verify_fresh|verify_legacy_restored) ;; *) die 'unknown probe API';; esac
  odoo_run "$source" "$db" shell --no-http --log-level=info <<PY 2>&1 | tee "$EVIDENCE/$log"
import importlib.util, json, os
assert os.environ.get('BWORK_CANONICAL_SYNTHETIC') == '1'
assert env.cr.dbname == '$db' and env.cr.dbname.startswith('bwork_canonical_ci_')
spec = importlib.util.spec_from_file_location('bwork_fixed_ci_probe', '$PROBE')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.$method(env)
assert isinstance(result, dict) and result
if '$method' == 'prepare_legacy':
    assert result.get('fixture') == 'BCR_SYNTHETIC_ONLY' and result.get('prepared') is True
    procurement = module.prepare_legacy_procurement(env)
    assert procurement.get('legacy_procurement_prepared') == 'PASS'
    print('BCR_PROCUREMENT_PREPARE_RESULT ' + json.dumps(procurement, sort_keys=True))
    # Core and procurement fixture writes commit together, never probe internals.
    env.cr.commit()
elif '$method' == 'exercise_legacy_rollback':
    assert result.get('rollback_after_ddl') == 'PASS' and result.get('old_source_identity_unchanged') is True
elif '$method' == 'verify_upgraded':
    assert all(result.get(k) == 'PASS' for k in ('real_old_install_upgrade','lineage','replay','cyclic_reply_and_media','bytes','nonmember_denial','idempotency','collision_rollback'))
    assert result.get('readiness_off') is True
elif '$method' == 'verify_fresh':
    assert all(result.get(k) == 'PASS' for k in ('real_fresh_install','fresh_core_only_ledger','uninstalled_siblings_not_installed','next_callback_noop'))
elif '$method' == 'verify_upgraded_procurement':
    assert result.get('procurement_upgrade') == 'PASS'
elif '$method' == 'verify_legacy_restored':
    assert result.get('legacy_restored') == 'PASS' and result.get('bytes') == 'PASS'
print('BCR_PROBE_RESULT ' + json.dumps(result, sort_keys=True))
print('BCR_${method}_GO')
PY
  clean_log "$EVIDENCE/$log"
  require_marker "$EVIDENCE/$log" "BCR_${method}_GO"
}
filestore_index() {
  docker_local run --rm --network none --mount "type=bind,src=$DATA,dst=/data,readonly" \
    --entrypoint sh "$PG_IMAGE" -eu -c 'cd "/data/filestore/$1"; find . -type f -print0 | sort -z | xargs -0 -r sha256sum' sh "$UPGRADE_DB"
}
backup_pair() {
  pg pg_dump --format=custom --no-owner --no-acl --dbname="$UPGRADE_DB" > "$EVIDENCE/legacy.dump"
  [[ -s "$EVIDENCE/legacy.dump" ]] || die 'empty database backup'
  docker_local run --rm --network none --mount "type=bind,src=$DATA,dst=/data,readonly" \
    --mount "type=bind,src=$EVIDENCE,dst=/evidence" --entrypoint tar "$PG_IMAGE" \
    -C /data/filestore -cpf /evidence/legacy-filestore.tar "$UPGRADE_DB"
  filestore_index > "$EVIDENCE/legacy-filestore.sha256"
  [[ -s "$EVIDENCE/legacy-filestore.sha256" ]] || die 'synthetic media was not stored in real filestore'
  sha256sum "$EVIDENCE/legacy.dump" "$EVIDENCE/legacy-filestore.tar" > "$EVIDENCE/paired-backup.sha256"
}
restore_pair() {
  local label="$1"; [[ "$label" == after_upgrade || "$label" == after_late_failure ]] || die 'unknown recovery phase'
  db_guard "$UPGRADE_DB"
  sha256sum --check "$EVIDENCE/paired-backup.sha256"
  # Never broad-delete filestore bytes: quarantine the exact disposable DB tree.
  docker_local run --rm --network none --mount "type=bind,src=$DATA,dst=/data" \
    --entrypoint mv "$PG_IMAGE" "/data/filestore/$UPGRADE_DB" "/data/quarantine/${UPGRADE_DB}_$label"
  pg dropdb --force "$UPGRADE_DB"
  pg createdb --template=template0 "$UPGRADE_DB"
  pg pg_restore --exit-on-error --no-owner --no-acl --dbname="$UPGRADE_DB" /evidence/legacy.dump
  docker_local run --rm --network none --mount "type=bind,src=$DATA,dst=/data" \
    --mount "type=bind,src=$EVIDENCE,dst=/evidence,readonly" --entrypoint tar "$PG_IMAGE" \
    -C /data/filestore -xpf /evidence/legacy-filestore.tar
  filestore_index > "$EVIDENCE/filestore-$label.sha256"
  cmp "$EVIDENCE/legacy-filestore.sha256" "$EVIDENCE/filestore-$label.sha256"
}

pg createdb --template=template0 "$UPGRADE_DB"
odoo_run old "$UPGRADE_DB" -i baseer_bchat,baseer_bwork_admin,baseer_bchat_procurement,baseer_access_roles --stop-after-init --no-http 2>&1 | tee "$EVIDENCE/01-old-install.log"
clean_log "$EVIDENCE/01-old-install.log"
probe old "$UPGRADE_DB" prepare_legacy 02-old-prepare.log
probe old "$UPGRADE_DB" exercise_legacy_rollback 03-transaction-rollback.log
backup_pair
odoo_run current "$UPGRADE_DB" -u baseer_bwork,baseer_bwork_admin,baseer_bwork_procurement,baseer_procurement_requests,baseer_access_roles --pre-upgrade-scripts="$HOOK" --stop-after-init --no-http 2>&1 | tee "$EVIDENCE/04-native-upgrade.log"
clean_log "$EVIDENCE/04-native-upgrade.log"
probe current "$UPGRADE_DB" verify_upgraded 05-upgrade-verify.log
probe current "$UPGRADE_DB" verify_upgraded_procurement 05b-procurement-verify.log

# Rewind the disposable fixture using the real paired backup, then intentionally
# fail a later addon in the SAME native upgrade command, not an atomicity claim.
restore_pair after_upgrade
set +e
odoo_run current "$UPGRADE_DB" -u baseer_bwork,baseer_bwork_admin,baseer_bwork_procurement,baseer_procurement_requests,baseer_access_roles -i bwork_canonical_failure --pre-upgrade-scripts="$HOOK" --stop-after-init --no-http 2>&1 | tee "$EVIDENCE/06-expected-late-failure.log"
failure_status=${PIPESTATUS[0]}
set -e
[[ "$failure_status" -ne 0 ]] || die 'negative fixture unexpectedly succeeded'
grep -F "RuntimeError: $FIXTURE_MARKER" "$EVIDENCE/06-expected-late-failure.log" >/dev/null || die 'wrong failure; intended late hook was not reached'
# Independent connection proves state was already committed, not just visible
# to the failing loader transaction. No registry workaround or code-only rollback.
pg psql -X --set ON_ERROR_STOP=1 --dbname="$UPGRADE_DB" -At <<'SQL' | tee "$EVIDENCE/07-committed-bootstrap.log"
SELECT CASE WHEN to_regclass('baseer_bwork_room') IS NOT NULL
 AND to_regclass('baseer_bchat_room') IS NULL
 AND EXISTS(SELECT 1 FROM ir_config_parameter WHERE key='baseer_bwork.canonical_rename.v1' AND value::jsonb->>'status'='complete')
 AND (SELECT count(*) FROM ir_module_module WHERE name IN ('baseer_bwork','baseer_bwork_admin') AND state='installed')=2
 THEN 'BCR_LATE_FAILURE_COMMITTED_BOOTSTRAP_GO' ELSE 'BCR_LATE_FAILURE_COMMITTED_BOOTSTRAP_FAIL' END;
SQL
require_marker "$EVIDENCE/07-committed-bootstrap.log" BCR_LATE_FAILURE_COMMITTED_BOOTSTRAP_GO
restore_pair after_late_failure
probe old "$UPGRADE_DB" verify_legacy_restored 08-paired-recovery-verify.log

pg createdb --template=template0 "$FRESH_DB"
odoo_run current "$FRESH_DB" -i baseer_bwork --stop-after-init --no-http 2>&1 | tee "$EVIDENCE/09-fresh-install.log"
clean_log "$EVIDENCE/09-fresh-install.log"
probe current "$FRESH_DB" verify_fresh 10-fresh-verify.log
odoo_run current "$FRESH_DB" -u baseer_bwork --pre-upgrade-scripts="$HOOK" --stop-after-init --no-http 2>&1 | tee "$EVIDENCE/11-fresh-next-upgrade.log"
clean_log "$EVIDENCE/11-fresh-next-upgrade.log"
probe current "$FRESH_DB" verify_fresh 12-fresh-next-verify.log
printf '%s\n' BCR_NATIVE_UPGRADE_GO BCR_FRESH_NEXT_UPGRADE_GO BCR_PAIRED_BACKUP_RECOVERY_GO > "$EVIDENCE/result.txt"
cat "$EVIDENCE/result.txt"
printf 'Synthetic disposable databases and quarantined work retained at %s; no production atomicity or deployment claim.\n' "$WORK"
