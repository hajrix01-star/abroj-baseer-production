#!/usr/bin/env bash
# Completes cold samples for the two companies not covered by the first run.
set -euo pipefail

root=/srv/abroj-baseer-production/rehearsals/heat-calendar-52e9ff5
export HC_REHEARSAL_PASSWORD="$(openssl rand -hex 24)"

compose() {
  docker compose --env-file "$root/.env" -f "$root/compose.yaml" "$@"
}

compose exec -T -e HC_REHEARSAL_PASSWORD odoo sh -lc \
  'odoo shell --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d baseer_heat_rehearsal_52e9ff5' \
  < "$root/rehearsal-checks.py" > "$root/evidence/orm-probe-cold-remaining.log" 2>&1

for company_id in 3 1; do
  for sample_id in 1 2 3 4 5; do
    compose restart odoo >/dev/null
    for attempt in $(seq 1 40); do
      if curl -fsS http://127.0.0.1:18189/web/login >/dev/null; then
        break
      fi
      sleep 1
    done
    curl -fsS http://127.0.0.1:18189/web/login >/dev/null
    python3 "$root/rehearsal-performance.py" \
      --base-url http://127.0.0.1:18189 \
      --database baseer_heat_rehearsal_52e9ff5 \
      --login hc_release_probe \
      --dashboard-id 9 \
      --sample-id "$sample_id" \
      cold "$company_id" >> "$root/evidence/cold-performance.jsonl"
    printf 'COLD_SAMPLE_OK|company=%s|sample=%s\n' "$company_id" "$sample_id"
  done
done
unset HC_REHEARSAL_PASSWORD
printf 'COLD_REHEARSAL_COMPLETE|samples=%s\n' "$(wc -l < "$root/evidence/cold-performance.jsonl")"
