#!/usr/bin/env bash
set -euo pipefail

# Rehearsal only. It refuses to touch the live source or production database.
base=/srv/abroj-baseer-production
candidate=f1b0034
rehearsal="$base/rehearsals/heat-calendar-targets-live-$candidate"
archive="$base/incoming/baseer-heat-calendar-targets-live-$candidate.tar.gz"
compose_asset="$base/incoming/heat-calendar-targets-compose-rehearsal-$candidate.yaml"
expected_sha=23d77acc0dfe3ae811d5b80b1e27299236d94dc6daf68ba55aa4bc04cd909ced
expected_baseline=/srv/abroj-baseer-production/releases/863bd85
rehearsal_db=baseer_heat_targets_rehearsal_f1b0034
project=baseer-heat-targets-rehearsal-f1b0034
odoo_image=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd

test "$(readlink -f "$base/current")" = "$expected_baseline"
test -f "$archive"
test "$(sha256sum "$archive" | awk '{print $1}')" = "$expected_sha"
! ss -ltn | awk '{print $4}' | grep -q ':18106$'

if test -e "$rehearsal"; then
  # The only permitted resume point is before any isolated Docker volume exists.
  test -d "$rehearsal/source/custom_addons/baseer_sales_heat_calendar"
  ! docker volume inspect baseer-heat-targets-rehearsal-f1b0034-postgres-data >/dev/null 2>&1
  ! docker volume inspect baseer-heat-targets-rehearsal-f1b0034-odoo-data >/dev/null 2>&1
else
  install -d -m 0755 "$rehearsal"
  tar -xzf "$archive" -C "$rehearsal"
  mv "$rehearsal/baseer-heat-calendar-targets-live" "$rehearsal/source"
  install -m 0644 "$compose_asset" "$rehearsal/compose.rehearsal.yaml"
fi
install -m 0600 "$expected_baseline/.env" "$rehearsal/.env"
sed -i -E "s/^POSTGRES_DB=.*/POSTGRES_DB=$rehearsal_db/" "$rehearsal/.env"
install -m 0600 "$rehearsal/.env" "$rehearsal/source/.env"
install -d -m 0755 "$rehearsal/source/config"
install -m 0644 "$expected_baseline/config/odoo.conf" "$rehearsal/source/config/odoo.conf"

compose=(docker compose --project-name "$project" --env-file "$rehearsal/.env" -f "$rehearsal/compose.rehearsal.yaml" --project-directory "$rehearsal/source")
"${compose[@]}" config --quiet

docker exec baseer-odoo-prod-db-1 sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$rehearsal/source-baseer-prod.dump"
sha256sum "$rehearsal/source-baseer-prod.dump" > "$rehearsal/source-baseer-prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro "$odoo_image" \
  bash -lc 'set -euo pipefail; test -d /source/filestore/baseer_prod; tar -C /source -cf - filestore/baseer_prod' \
  > "$rehearsal/source-filestore-baseer-prod.tar"
sha256sum "$rehearsal/source-filestore-baseer-prod.tar" > "$rehearsal/source-filestore-baseer-prod.tar.sha256"

"${compose[@]}" up -d db
for attempt in $(seq 1 60); do
  if "${compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; then
    break
  fi
  sleep 1
done
"${compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
"${compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$rehearsal/source-baseer-prod.dump"
cat "$rehearsal/source-filestore-baseer-prod.tar" | docker run --rm -i --user 0:0 \
  -v baseer-heat-targets-rehearsal-f1b0034-odoo-data:/target "$odoo_image" \
  bash -lc 'set -euo pipefail; install -d -o 100 -g 101 -m 0755 /target/filestore; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod'

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

"${compose[@]}" up -d odoo_data_init
for attempt in $(seq 1 30); do
  status="$("${compose[@]}" ps -a --format json odoo_data_init 2>/dev/null | jq -r '.State // empty' || true)"
  test "$status" = exited && break
  sleep 1
done
test "$("${compose[@]}" ps -a --format json odoo_data_init | jq -r '.ExitCode // empty')" = 0
"${compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:18106/web/login >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:18106/web/login >/dev/null

module_state="$("${compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select state || chr(58) || latest_version from ir_module_module where name='\''baseer_sales_heat_calendar'\''"')"
test "$module_state" = 'installed:19.0.1.0.8'

python3 - "$rehearsal/acceptance.json" "$expected_sha" "$module_state" <<'PY'
import hashlib
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
    },
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + '\n')
PY

printf 'rehearsal=GO\n'
printf 'module=%s\n' "$module_state"
printf 'test='; grep -E '0 failed, 0 error\(s\) of [0-9]+ tests' "$rehearsal/target-module-test.log" | tail -n 1
