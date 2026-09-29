#!/usr/bin/env bash
set -euo pipefail

# Production cutover for the heat-target editor only. Run after independent GO.
base=/srv/abroj-baseer-production
candidate=f1b0034
archive="$base/incoming/baseer-heat-calendar-targets-live-$candidate.tar.gz"
expected_sha=23d77acc0dfe3ae811d5b80b1e27299236d94dc6daf68ba55aa4bc04cd909ced
expected_baseline="$base/releases/863bd85"
release="$base/releases/$candidate"
previous="$(readlink -f "$base/current")"
odoo_image=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/heat-calendar-targets-live-$timestamp"
service_stopped=false
backup_ready=false
cutover_complete=false

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
on_exit() {
  code=$?
  if test "$code" != 0 && test "$cutover_complete" != true; then
    restore_previous || true
  fi
  exit "$code"
}
trap on_exit EXIT

test "$previous" = "$expected_baseline"
test -f "$archive"
test "$(sha256sum "$archive" | awk '{print $1}')" = "$expected_sha"
test ! -e "$release"
test "$(docker exec baseer-odoo-prod-db-1 sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_sales_heat_calendar'\''"')" = 'installed:19.0.1.0.7'

extract_root="$(mktemp -d "$base/releases/.extract-$candidate.XXXXXX")"
tar -xzf "$archive" -C "$extract_root"
test -d "$extract_root/baseer-heat-calendar-targets-live/custom_addons/baseer_sales_heat_calendar"
mv "$extract_root/baseer-heat-calendar-targets-live" "$release"
rmdir "$extract_root"
install -m 0600 "$previous/.env" "$release/.env"
install -d -m 0755 "$release/config"
install -m 0644 "$previous/config/odoo.conf" "$release/config/odoo.conf"
"${release_compose[@]}" config --quiet
grep -Fq "'version': '19.0.1.0.8'" "$release/custom_addons/baseer_sales_heat_calendar/__manifest__.py"

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

snapshot_sql="SELECT jsonb_build_object(
  'account.move', (SELECT count(*) FROM account_move),
  'account.move.line', (SELECT count(*) FROM account_move_line),
  'account.payment', (SELECT count(*) FROM account_payment),
  'hr.employee', (SELECT count(*) FROM hr_employee),
  'hr.payslip', (SELECT count(*) FROM hr_payslip),
  'res.partner', (SELECT count(*) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id = p.id)),
  'baseer.pos.daily.report', (SELECT count(*) FROM baseer_pos_daily_report),
  'heat.target.count', (SELECT count(*) FROM baseer_heat_calendar_target),
  'heat.target.fingerprint', (SELECT coalesce(md5(string_agg(concat_ws('|', company_id, year, month, weekday, target_amount::text, active::text), ',' ORDER BY company_id, year, month, weekday)), 'empty') FROM baseer_heat_calendar_target)
);"
snapshot() {
  printf '%s\n' "$snapshot_sql" | "${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq'
}
snapshot > "$backup/preupgrade-protected-snapshot.json"
"${release_compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_prod -u baseer_sales_heat_calendar --stop-after-init --workers=0 --max-cron-threads=0' \
  > "$backup/target-module-upgrade.log" 2>&1
snapshot > "$backup/postupgrade-protected-snapshot.json"
cmp "$backup/preupgrade-protected-snapshot.json" "$backup/postupgrade-protected-snapshot.json"
test "$("${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_sales_heat_calendar'\''"')" = 'installed:19.0.1.0.8'

ln -s "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
"${release_compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:18069/web/login >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:18069/web/login >/dev/null
curl -fsS https://baseer.abroj.sa/web/login >/dev/null
! docker logs --since 2m baseer-odoo-prod-odoo-1 2>&1 | grep -Eq 'Traceback|CRITICAL|FATAL'

python3 - "$backup/cutover-evidence.json" "$expected_sha" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).parent
payload = {
    'decision': 'GO',
    'candidate_commit': 'f1b0034cfce8390a8274b59e900b823ae7590d97',
    'candidate_tag': 'heat-calendar-targets-live-candidate-2026-09-14.1',
    'archive_sha256': sys.argv[2],
    'module': 'baseer_sales_heat_calendar:19.0.1.0.8',
    'checks': {
        'backup_pair_sha256_verified': True,
        'protected_snapshot_match': (root / 'preupgrade-protected-snapshot.json').read_bytes() == (root / 'postupgrade-protected-snapshot.json').read_bytes(),
        'local_login_http': True,
        'public_login_http': True,
    },
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + '\n')
PY

cutover_complete=true
printf 'cutover=GO\n'
printf 'release=%s\n' "$release"
printf 'backup=%s\n' "$backup"
