#!/usr/bin/env bash
set -euo pipefail

root=/srv/abroj-baseer-production/rehearsals/cashier-procurement-863bd85
rcompose=(docker compose --env-file "$root/.env" -f "$root/compose.yaml")

# The only removal is the failed, isolated rehearsal Odoo container; volumes
# and production containers are not targeted.
"${rcompose[@]}" rm -sf odoo || true
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
