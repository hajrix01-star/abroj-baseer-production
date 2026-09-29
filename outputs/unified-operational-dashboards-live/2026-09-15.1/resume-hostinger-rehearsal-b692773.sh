#!/usr/bin/env bash
set -euo pipefail

root=/srv/abroj-baseer-production/rehearsals/unified-operational-dashboards-b692773
db=baseer_unified_rehearsal_b692773
project=baseer-unified-rehearsal-b692773
image=odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd
compose=(docker compose --project-name "$project" --env-file "$root/.env" -f "$root/compose.yaml" --project-directory "$root")

"${compose[@]}" config --quiet
"${compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$root/evidence/baseer_prod.dump"
cat "$root/evidence/filestore-baseer_prod.tar" | docker run --rm -i --user 0:0 \
  -v baseer-unified-rehearsal-b692773-odoo-data:/target "$image" \
  bash -lc 'set -euo pipefail; install -d -o 100 -g 101 -m 0755 /target/filestore; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod'

snapshot_sql="SELECT jsonb_build_object('account.move',(SELECT count(*) FROM account_move),'account.move.line',(SELECT count(*) FROM account_move_line),'account.payment',(SELECT count(*) FROM account_payment),'hr.employee',(SELECT count(*) FROM hr_employee),'hr.payslip',(SELECT count(*) FROM hr_payslip),'res.partner',(SELECT count(*) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id=p.id)),'baseer.pos.summary',(SELECT count(*) FROM baseer_pos_summary),'baseer.pos.summary.allocation',(SELECT count(*) FROM baseer_pos_summary_allocation),'baseer.heat.target',(SELECT count(*) FROM baseer_heat_calendar_target),'baseer.occasion',(SELECT count(*) FROM baseer_official_occasion));"
snapshot() { printf '%s\n' "$snapshot_sql" | "${compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atq'; }
snapshot > "$root/evidence/protected-before.json"

"${compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_unified_rehearsal_b692773 -u baseer_access_roles,baseer_procurement_requests,baseer_purchase_batch,baseer_sales_heat_calendar,baseer_sales_dashboard,baseer_purchase_expense_dashboard,baseer_basser_workspace --stop-after-init --workers=0 --max-cron-threads=0 --test-enable --test-tags /baseer_access_roles,/baseer_procurement_requests,/baseer_purchase_batch,/baseer_sales_heat_calendar,/baseer_sales_dashboard,/baseer_purchase_expense_dashboard,/baseer_basser_workspace' \
  > "$root/evidence/module-upgrade-and-tests.log" 2>&1
grep -Eq '0 failed, 0 error\(s\) of [0-9]+ tests' "$root/evidence/module-upgrade-and-tests.log"
snapshot > "$root/evidence/protected-after.json"
cmp "$root/evidence/protected-before.json" "$root/evidence/protected-after.json"

"${compose[@]}" up -d odoo_data_init
for attempt in $(seq 1 30); do
  status="$("${compose[@]}" ps -a --format json odoo_data_init 2>/dev/null | jq -r '.State // empty' || true)"
  test "$status" = exited && break
  sleep 1
done
test "$("${compose[@]}" ps -a --format json odoo_data_init | jq -r '.ExitCode // empty')" = 0
"${compose[@]}" up -d odoo
for attempt in $(seq 1 90); do
  curl -fsS --max-time 10 http://127.0.0.1:18126/web/login >/dev/null && break
  sleep 1
done
curl -fsS --max-time 10 http://127.0.0.1:18126/web/login >/dev/null

"${compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c "select name,state,latest_version from ir_module_module where name in ('\''baseer_access_roles'\'','\''baseer_procurement_requests'\'','\''baseer_purchase_batch'\'','\''baseer_sales_heat_calendar'\'','\''baseer_sales_dashboard'\'','\''baseer_purchase_expense_dashboard'\'','\''baseer_basser_workspace'\'') order by name"' > "$root/evidence/module-state.txt"
grep -Fx 'baseer_access_roles|installed|19.0.1.0.6' "$root/evidence/module-state.txt"
grep -Fx 'baseer_procurement_requests|installed|19.0.11.0.3' "$root/evidence/module-state.txt"
grep -Fx 'baseer_purchase_batch|installed|19.0.1.2.3' "$root/evidence/module-state.txt"
grep -Fx 'baseer_sales_heat_calendar|installed|19.0.1.0.8' "$root/evidence/module-state.txt"
grep -Fx 'baseer_sales_dashboard|installed|19.0.1.1.6' "$root/evidence/module-state.txt"
grep -Fx 'baseer_purchase_expense_dashboard|installed|19.0.1.0.1' "$root/evidence/module-state.txt"
grep -Fx 'baseer_basser_workspace|installed|19.0.1.0.3' "$root/evidence/module-state.txt"
"${compose[@]}" logs --no-color --tail=200 odoo > "$root/evidence/odoo-smoke.log"
! grep -Eq 'Traceback \(most recent call last\)|CRITICAL|FATAL' "$root/evidence/odoo-smoke.log"
printf 'REHEARSAL=GO\nROOT=%s\n' "$root"
