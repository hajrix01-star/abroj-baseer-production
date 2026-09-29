#!/usr/bin/env bash
set -euo pipefail

root=/srv/abroj-baseer-production/rehearsals/cashier-procurement-863bd85
db=baseer_cashier_rehearsal_863bd85
rcompose=(docker compose --env-file "$root/.env" -f "$root/compose.yaml")

"${rcompose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
    --http-port=8069 --gevent-port=8072 \
    --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
    -d baseer_cashier_rehearsal_863bd85 -u baseer_access_roles,baseer_procurement_requests \
    --stop-after-init --workers=0 --max-cron-threads=0 --test-enable \
    --test-tags /baseer_access_roles,/baseer_procurement_requests' \
  > "$root/evidence/module-upgrade-and-tests.log" 2>&1

"${rcompose[@]}" exec -T db sh -lc \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -AtF "|" -c "select name, state, latest_version from ir_module_module where name in ('"'"'baseer_access_roles'"'"','"'"'baseer_procurement_requests'"'"') order by name"' \
  > "$root/evidence/module-state.txt"

grep -Fx 'baseer_access_roles|installed|19.0.1.0.3' "$root/evidence/module-state.txt"
grep -Fx 'baseer_procurement_requests|installed|19.0.11.0.2' "$root/evidence/module-state.txt"

"${rcompose[@]}" up -d odoo
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:18190/web/login >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:18190/web/login >/dev/null
"${rcompose[@]}" logs --no-color --tail=200 odoo > "$root/evidence/odoo-smoke.log"
if grep -E 'Traceback \(most recent call last\)|CRITICAL|FATAL' "$root/evidence/odoo-smoke.log"; then
  exit 1
fi

printf '%s\n' REHEARSAL_UPGRADE_TEST_AND_SMOKE_PASSED > "$root/evidence/rehearsal-result.txt"
