#!/usr/bin/env bash
set -euo pipefail

base=/srv/abroj-baseer-production
archive="$base/incoming/baseer-unified-operational-dashboards-2d6125e.tar.gz"
expected_sha=2de320c8fd9b6ab820a1b42895d32aa0568a976c9d6673780886d605f488c206
release="$base/releases/2d6125e"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/pre-2d6125e-$stamp"
old_release="$(readlink -f "$base/current")"
compose_old=(docker compose --project-name baseer-odoo-prod --env-file "$base/current/.env" -f "$base/current/compose.production.yaml" --project-directory "$base/current")

test "$(basename "$old_release")" = f1b0034
test "$(sha256sum "$archive" | awk '{print $1}')" = "$expected_sha"
mkdir -p "$backup" "$base/releases"

# Prepare and validate the immutable release before the live Odoo service stops.
staging="$base/releases/.staging-2d6125e-$stamp"
rm -rf "$staging"
mkdir -p "$staging"
tar -xzf "$archive" -C "$staging"
source_dir="$(find "$staging" -mindepth 1 -maxdepth 1 -type d -name 'source-*' -print -quit)"
test -n "$source_dir"
rm -rf "$release"
mv "$source_dir" "$release"
rmdir "$staging"
cp "$base/current/.env" "$release/.env"
cp "$base/current/config/odoo.conf" "$release/config/odoo.conf"
docker compose --project-name baseer-odoo-prod --env-file "$release/.env" -f "$release/compose.production.yaml" --project-directory "$release" config --quiet

# A recoverable pair is captured while the old live application remains online.
docker exec baseer-odoo-prod-db-1 sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" -d baseer_prod' > "$backup/baseer_prod.dump"
docker run --rm -v baseer-odoo-prod-odoo-data:/source -v "$backup":/target alpine:3.20 sh -lc 'tar -C /source -cf /target/filestore-baseer_prod.tar filestore/baseer_prod'
sha256sum "$backup/baseer_prod.dump" "$backup/filestore-baseer_prod.tar" > "$backup/recovery.sha256"

snapshot_sql="SELECT jsonb_build_object('account.move',(SELECT count(*) FROM account_move),'account.move.line',(SELECT count(*) FROM account_move_line),'account.payment',(SELECT count(*) FROM account_payment),'hr.employee',(SELECT count(*) FROM hr_employee),'hr.payslip',(SELECT count(*) FROM hr_payslip),'res.partner',(SELECT count(*) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id=p.id)),'baseer.pos.summary',(SELECT count(*) FROM baseer_pos_summary),'baseer.pos.summary.allocation',(SELECT count(*) FROM baseer_pos_summary_allocation),'baseer.heat.target',(SELECT count(*) FROM baseer_heat_calendar_target),'baseer.occasion',(SELECT count(*) FROM baseer_official_occasion));"
snapshot() { printf '%s\n' "$snapshot_sql" | docker exec -i baseer-odoo-prod-db-1 sh -lc 'psql -U "$POSTGRES_USER" -d baseer_prod -Atq'; }
snapshot > "$backup/protected-before.json"

# The app is stopped only for the schema/module step; PostgreSQL stays online.
"${compose_old[@]}" stop odoo
ln -sfn "$release" "$base/current"
compose=(docker compose --project-name baseer-odoo-prod --env-file "$base/current/.env" -f "$base/current/compose.production.yaml" --project-directory "$base/current")

"${compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_prod -i baseer_purchase_expense_dashboard,baseer_basser_workspace --stop-after-init --workers=0 --max-cron-threads=0' \
  > "$backup/module-install.log" 2>&1
"${compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_prod -u baseer_access_roles,baseer_procurement_requests,baseer_purchase_batch,baseer_sales_heat_calendar,baseer_sales_dashboard,baseer_purchase_expense_dashboard,baseer_basser_workspace --stop-after-init --workers=0 --max-cron-threads=0' \
  > "$backup/module-upgrade.log" 2>&1

snapshot > "$backup/protected-after.json"
cmp "$backup/protected-before.json" "$backup/protected-after.json"

"${compose[@]}" up -d odoo_data_init
for attempt in $(seq 1 30); do
  status="$("${compose[@]}" ps -a --format json odoo_data_init 2>/dev/null | jq -r '.State // empty' || true)"
  test "$status" = exited && break
  sleep 1
done
test "$("${compose[@]}" ps -a --format json odoo_data_init | jq -r '.ExitCode // empty')" = 0
"${compose[@]}" up -d odoo
for attempt in $(seq 1 90); do
  curl -fsS --max-time 10 http://127.0.0.1:18069/web/login >/dev/null && break
  sleep 1
done
curl -fsS --max-time 10 http://127.0.0.1:18069/web/login >/dev/null

docker exec baseer-odoo-prod-db-1 sh -lc 'psql -U "$POSTGRES_USER" -d baseer_prod -AtF "|" -c "select name,state,latest_version from ir_module_module where name in ('"'"'baseer_access_roles'"'"','"'"'baseer_procurement_requests'"'"','"'"'baseer_purchase_batch'"'"','"'"'baseer_sales_heat_calendar'"'"','"'"'baseer_sales_dashboard'"'"','"'"'baseer_purchase_expense_dashboard'"'"','"'"'baseer_basser_workspace'"'"') order by name"' > "$backup/module-state.txt"
grep -Fx 'baseer_access_roles|installed|19.0.1.0.6' "$backup/module-state.txt"
grep -Fx 'baseer_procurement_requests|installed|19.0.11.0.3' "$backup/module-state.txt"
grep -Fx 'baseer_purchase_batch|installed|19.0.1.2.3' "$backup/module-state.txt"
grep -Fx 'baseer_sales_heat_calendar|installed|19.0.1.0.8' "$backup/module-state.txt"
grep -Fx 'baseer_sales_dashboard|installed|19.0.1.1.6' "$backup/module-state.txt"
grep -Fx 'baseer_purchase_expense_dashboard|installed|19.0.1.0.1' "$backup/module-state.txt"
grep -Fx 'baseer_basser_workspace|installed|19.0.1.0.3' "$backup/module-state.txt"
"${compose[@]}" logs --no-color --tail=300 odoo > "$backup/odoo-smoke.log"
! grep -Eq 'Traceback \(most recent call last\)|CRITICAL|FATAL' "$backup/odoo-smoke.log"
printf 'LIVE=GO\nRELEASE=%s\nBACKUP=%s\n' "$release" "$backup"
