#!/usr/bin/env bash
set -euo pipefail

# This resets only the named disposable rehearsal database and filestore after a failed probe.
base=/srv/abroj-baseer-production
rehearsal="$base/rehearsals/heat-calendar-targets-live-f1b0034"
project=baseer-heat-targets-rehearsal-f1b0034
rehearsal_db=baseer_heat_targets_rehearsal_f1b0034
odoo_image=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
expected_sha=23d77acc0dfe3ae811d5b80b1e27299236d94dc6daf68ba55aa4bc04cd909ced
target_volume=baseer-heat-targets-rehearsal-f1b0034-odoo-data

test -s "$rehearsal/source-baseer-prod.dump"
test -s "$rehearsal/source-filestore-baseer-prod.tar"
test ! -e "$rehearsal/acceptance.json"
compose=(docker compose --project-name "$project" --env-file "$rehearsal/.env" -f "$rehearsal/compose.rehearsal.yaml" --project-directory "$rehearsal/source")
"${compose[@]}" config --quiet
"${compose[@]}" stop odoo || true
"${compose[@]}" exec -T db sh -lc 'dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
"${compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$rehearsal/source-baseer-prod.dump"
docker run --rm --user 0:0 -v "$target_volume:/target" "$odoo_image" bash -lc '
  set -euo pipefail
  source_dir=/target/filestore/baseer_prod
  target_dir=/target/filestore/baseer_heat_targets_rehearsal_f1b0034
  test -d "$source_dir"
  test "$(dirname "$target_dir")" = /target/filestore
  rm -rf -- "$target_dir"
  cp -a "$source_dir" "$target_dir"
  chown -R 100:101 "$target_dir"
'

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
  printf '%s\n' "$snapshot_sql" | "${compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq'
}
snapshot > "$rehearsal/preupgrade-protected-snapshot.json"
"${compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_heat_targets_rehearsal_f1b0034 -u baseer_sales_heat_calendar --stop-after-init --workers=0 --max-cron-threads=0 --test-enable --test-tags /baseer_sales_heat_calendar' \
  > "$rehearsal/target-module-test.log" 2>&1
grep -Eq '0 failed, 0 error\(s\) of [0-9]+ tests' "$rehearsal/target-module-test.log"
snapshot > "$rehearsal/postupgrade-protected-snapshot.json"
cmp "$rehearsal/preupgrade-protected-snapshot.json" "$rehearsal/postupgrade-protected-snapshot.json"

"${compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  if docker exec baseer-heat-targets-rehearsal-f1b0034-odoo-1 python3 -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8069/web/login", timeout=5).status == 200' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec baseer-heat-targets-rehearsal-f1b0034-odoo-1 python3 -c 'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8069/web/login", timeout=5).status == 200'

module_state="$("${compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_sales_heat_calendar'\''"')"
test "$module_state" = 'installed:19.0.1.0.8'

python3 - "$rehearsal/acceptance.json" "$expected_sha" "$module_state" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).parent
payload = {
    'decision': 'GO',
    'candidate': {
        'commit': 'f1b0034cfce8390a8274b59e900b823ae7590d97',
        'tag': 'heat-calendar-targets-live-candidate-2026-09-14.1',
        'archive_sha256': sys.argv[2],
        'module_state': sys.argv[3],
    },
    'source': {
        'database_backup_sha256': (root / 'source-baseer-prod.dump.sha256').read_text().split()[0],
        'filestore_backup_sha256': (root / 'source-filestore-baseer-prod.tar.sha256').read_text().split()[0],
    },
    'checks': {
        'module_tests': 'passed',
        'protected_snapshot_match': (root / 'preupgrade-protected-snapshot.json').read_bytes() == (root / 'postupgrade-protected-snapshot.json').read_bytes(),
        'isolated_login_http': True,
        'filestore_database_name_aligned': True,
    },
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + '\n')
PY

printf 'rehearsal=GO\n'
printf 'module=%s\n' "$module_state"
printf 'test='; grep -E '0 failed, 0 error\(s\) of [0-9]+ tests' "$rehearsal/target-module-test.log" | tail -n 1
