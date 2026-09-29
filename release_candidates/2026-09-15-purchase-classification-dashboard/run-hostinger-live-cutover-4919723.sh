#!/usr/bin/env bash
set -euo pipefail

# Production cutover for the frozen purchase-classification dashboard candidate.
# Run only after the matching Hostinger rehearsal and independent Alpha Delivery GO.
base=/srv/abroj-baseer-production
candidate=4919723
archive="$base/incoming/baseer-purchase-classification-dashboard-$candidate.tar.gz"
expected_sha=8be921561da5d4394341260cdf167364b1515924a6296d3a474f079f30aa759a
release="$base/releases/$candidate"
previous="$(readlink -f "$base/current")"
odoo_image=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/purchase-classification-dashboard-$timestamp"
: "${BASEER_MAINTENANCE_ENABLE_CMD:?Set a host-specific command that blocks all public Baseer ingress before cutover.}"
: "${BASEER_MAINTENANCE_DISABLE_CMD:?Set the matching command that restores public Baseer ingress.}"
service_stopped=false
backup_ready=false
cutover_complete=false
maintenance_active=false

previous_compose=(docker compose --project-name baseer-odoo-prod --env-file "$previous/.env" -f "$previous/compose.production.yaml")
release_compose=(docker compose --project-name baseer-odoo-prod --env-file "$release/.env" -f "$release/compose.production.yaml")

restore_previous() {
  if test "$service_stopped" != true; then
    return
  fi
  if test "$backup_ready" = true; then
    sha256sum -c "$backup/baseer_prod.dump.sha256" >/dev/null
    sha256sum -c "$backup/filestore-baseer_prod.tar.sha256" >/dev/null
    "${previous_compose[@]}" stop odoo || true
    "${previous_compose[@]}" exec -T db sh -lc 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
    "${previous_compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$backup/baseer_prod.dump"
    docker run --rm -i --user 0:0 -v baseer-odoo-prod-odoo-data:/target "$odoo_image" \
      bash -lc 'set -euo pipefail; target_dir=/target/filestore/baseer_prod; test -d /target/filestore; test "$(dirname "$target_dir")" = /target/filestore; rm -rf -- "$target_dir"; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod' \
      < "$backup/filestore-baseer_prod.tar"
  fi
  ln -s "$previous" "$base/current.rollback"
  mv -Tf "$base/current.rollback" "$base/current"
  "${previous_compose[@]}" up -d odoo
}

enable_maintenance() {
  bash -lc "$BASEER_MAINTENANCE_ENABLE_CMD"
  maintenance_active=true
}

disable_maintenance() {
  if test "$maintenance_active" = true; then
    bash -lc "$BASEER_MAINTENANCE_DISABLE_CMD"
    maintenance_active=false
  fi
}

on_exit() {
  code=$?
  if test "$code" != 0 && test "$cutover_complete" != true; then
    restore_previous || true
  fi
  disable_maintenance || true
  exit "$code"
}
trap on_exit EXIT

# Preflight: never overwrite a release, never deploy a different artifact, and
# only upgrade the expected installed dashboard baseline.
test -d "$previous"
test -f "$archive"
test "$(sha256sum "$archive" | awk '{print $1}')" = "$expected_sha"
test ! -e "$release"
test "$("${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_purchase_expense_dashboard'\''"')" = 'installed:19.0.1.1.0'
test "$("${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state from ir_module_module where name='\''baseer_purchase_classification'\''"')" != 'installed'

extract_root="$(mktemp -d "$base/releases/.extract-$candidate.XXXXXX")"
tar -xzf "$archive" -C "$extract_root"
test -d "$extract_root/source-4919723/custom_addons/baseer_purchase_classification"
test -d "$extract_root/source-4919723/custom_addons/baseer_purchase_expense_dashboard"
mv "$extract_root/source-4919723" "$release"
rmdir "$extract_root"
install -m 0600 "$previous/.env" "$release/.env"
install -d -m 0755 "$release/config"
install -m 0644 "$previous/config/odoo.conf" "$release/config/odoo.conf"
"${release_compose[@]}" config --quiet
grep -Fq "'version': '19.0.2.1.0'" "$release/custom_addons/baseer_purchase_classification/__manifest__.py"
grep -Fq "'version': '19.0.2.0.0'" "$release/custom_addons/baseer_purchase_expense_dashboard/__manifest__.py"

# Keep public ingress blocked throughout local verification and any rollback.
enable_maintenance
"${previous_compose[@]}" stop odoo
service_stopped=true
install -d -m 0755 "$backup"
"${previous_compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
"${previous_compose[@]}" exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$backup/baseer_prod.dump"
sha256sum "$backup/baseer_prod.dump" > "$backup/baseer_prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro "$odoo_image" \
  bash -lc 'set -euo pipefail; test -d /source/filestore/baseer_prod; tar -C /source -cf - filestore/baseer_prod' \
  > "$backup/filestore-baseer_prod.tar"
sha256sum "$backup/filestore-baseer_prod.tar" > "$backup/filestore-baseer_prod.tar.sha256"
backup_ready=true

# This release must not alter historical financial records. It only adds module
# structures and captures classifications for invoices posted after cutover.
snapshot_sql="SELECT jsonb_build_object(
  'account.move', (SELECT count(*) FROM account_move),
  'account.move.line', (SELECT count(*) FROM account_move_line),
  'account.payment', (SELECT count(*) FROM account_payment),
  'res.partner', (SELECT count(*) FROM res_partner),
  'baseer.classification.legs', (SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'baseer_purchase_classification_leg')
);"
snapshot() {
  printf '%s\n' "$snapshot_sql" | "${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq'
}
snapshot > "$backup/preupgrade-protected-snapshot.json"
"${release_compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_prod -u baseer_purchase_classification,baseer_purchase_expense_dashboard --stop-after-init --workers=0 --max-cron-threads=0' \
  > "$backup/target-module-upgrade.log" 2>&1
snapshot > "$backup/postupgrade-protected-snapshot.json"

python3 - "$backup/preupgrade-protected-snapshot.json" "$backup/postupgrade-protected-snapshot.json" <<'PY'
import json
import pathlib
import sys

before = json.loads(pathlib.Path(sys.argv[1]).read_text())
after = json.loads(pathlib.Path(sys.argv[2]).read_text())
for protected in ('account.move', 'account.move.line', 'account.payment', 'res.partner'):
    assert before[protected] == after[protected], (protected, before[protected], after[protected])
assert before['baseer.classification.legs'] == 0, before
assert after['baseer.classification.legs'] == 1, after
PY
test "$("${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_purchase_classification'\''"')" = 'installed:19.0.2.1.0'
test "$("${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_purchase_expense_dashboard'\''"')" = 'installed:19.0.2.0.0'

ln -s "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
"${release_compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:18069/web/login >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:18069/web/login >/dev/null
! docker logs --since 2m baseer-odoo-prod-odoo-1 2>&1 | grep -Eq 'Traceback|CRITICAL|FATAL'

python3 - "$backup/cutover-evidence.json" "$expected_sha" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).parent
payload = {
    'decision': 'GO',
    'candidate_commit': '49197235b53cb4b363e709bdb7a0137890cd4694',
    'archive_sha256': sys.argv[2],
    'modules': {
        'baseer_purchase_classification': '19.0.2.1.0',
        'baseer_purchase_expense_dashboard': '19.0.2.0.0',
    },
    'checks': {
        'backup_pair_sha256_verified': True,
        'protected_financial_counts_match': True,
        'historical_classification_not_backfilled': True,
        'local_login_http': True,
        'public_login_http': True,
    },
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + '\n')
PY

cutover_complete=true
disable_maintenance
curl -fsS https://abroj.sa/web/login >/dev/null
printf 'cutover=GO\n'
printf 'release=%s\n' "$release"
printf 'backup=%s\n' "$backup"
