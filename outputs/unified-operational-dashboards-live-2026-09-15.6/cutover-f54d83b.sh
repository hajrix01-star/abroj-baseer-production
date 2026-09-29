#!/usr/bin/env bash
# Production cutover for the approved dashboard-only candidate f54d83b.
set -euo pipefail

ROOT=/srv/abroj-baseer-production
CANDIDATE=f54d83b
ARCHIVE="$ROOT/incoming/baseer-unified-operational-dashboards-f54d83b.tar.gz"
ARCHIVE_SHA=88eb2311be33b5ff72e3f571e23ab636a4ba49f60a798b56f6dea2b4a47f7ecb
CURRENT="$ROOT/current"
PREVIOUS=$(readlink -f "$CURRENT")
RELEASE="$ROOT/releases/$CANDIDATE"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP="$ROOT/backups/unified-operational-dashboards-$STAMP"
COMPOSE_FILE=compose.production.yaml
DB=baseer_prod
DB_USER=baseer
MODULES=baseer_purchase_expense_dashboard,baseer_sales_dashboard
ROLLED_BACK=0

previous_compose() { docker compose --env-file "$PREVIOUS/.env" -f "$PREVIOUS/$COMPOSE_FILE" "$@"; }
release_compose() { docker compose --env-file "$RELEASE/.env" -f "$RELEASE/$COMPOSE_FILE" "$@"; }

snapshot() {
  local compose_dir=$1
  docker compose --env-file "$compose_dir/.env" -f "$compose_dir/$COMPOSE_FILE" exec -T db \
    psql -U "$DB_USER" -d "$DB" -At -c "SELECT json_build_object(
      'account_move', (SELECT count(*) FROM account_move),
      'account_move_line', (SELECT count(*) FROM account_move_line),
      'account_payment', (SELECT count(*) FROM account_payment),
      'hr_employee', (SELECT count(*) FROM hr_employee),
      'hr_payslip', (SELECT count(*) FROM hr_payslip),
      'res_partner', (SELECT count(*) FROM res_partner),
      'baseer_pos_summary', (SELECT count(*) FROM baseer_pos_summary),
      'baseer_pos_summary_allocation', (SELECT count(*) FROM baseer_pos_summary_allocation)
    )::text" > "$2"
}

restore_previous() {
  rc=$?
  trap - ERR
  if [ "$ROLLED_BACK" -eq 0 ] && [ -f "$BACKUP/baseer_prod.dump" ] && [ -f "$BACKUP/filestore-baseer_prod.tar" ]; then
    ROLLED_BACK=1
    echo "Cutover failed (exit $rc); restoring previous release." >&2
    previous_compose up -d db
    previous_compose exec -T db dropdb -U "$DB_USER" --if-exists "$DB" || true
    previous_compose exec -T db createdb -U "$DB_USER" "$DB"
    previous_compose exec -T db pg_restore -U "$DB_USER" -d "$DB" --clean --if-exists < "$BACKUP/baseer_prod.dump"
    docker run --rm -v baseer-odoo-prod-odoo-data:/target alpine:3.20 \
      sh -c 'rm -rf /target/filestore/baseer_prod && mkdir -p /target/filestore/baseer_prod'
    docker run --rm -i -v baseer-odoo-prod-odoo-data:/target alpine:3.20 \
      tar -C /target -xf - < "$BACKUP/filestore-baseer_prod.tar"
    ln -sfn "$PREVIOUS" "$CURRENT"
    previous_compose up -d odoo
  fi
  exit "$rc"
}
trap restore_previous ERR

[ "$(basename "$PREVIOUS")" = 62c1cb9 ]
[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" = "$ARCHIVE_SHA" ]
[ ! -e "$RELEASE" ]
previous_compose exec -T db psql -U "$DB_USER" -d "$DB" -At -c \
  "SELECT name || ':' || latest_version FROM ir_module_module WHERE name IN ('baseer_purchase_expense_dashboard','baseer_sales_dashboard') ORDER BY name" \
  | grep -Fx 'baseer_purchase_expense_dashboard:19.0.1.0.1'
previous_compose exec -T db psql -U "$DB_USER" -d "$DB" -At -c \
  "SELECT name || ':' || latest_version FROM ir_module_module WHERE name IN ('baseer_purchase_expense_dashboard','baseer_sales_dashboard') ORDER BY name" \
  | grep -Fx 'baseer_sales_dashboard:19.0.1.1.6'

mkdir -p "$RELEASE" "$BACKUP"
tar -xzf "$ARCHIVE" -C "$RELEASE" --strip-components=1
mkdir -p "$RELEASE/config"
cp "$PREVIOUS/.env" "$RELEASE/.env"
cp "$PREVIOUS/config/odoo.conf" "$RELEASE/config/odoo.conf"
release_compose config -q
snapshot "$PREVIOUS" "$BACKUP/protected-pre.json"
previous_compose stop odoo
previous_compose exec -T db pg_dump -U "$DB_USER" -Fc "$DB" > "$BACKUP/baseer_prod.dump"
sha256sum "$BACKUP/baseer_prod.dump" > "$BACKUP/baseer_prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro alpine:3.20 \
  tar -C /source -cf - filestore/baseer_prod > "$BACKUP/filestore-baseer_prod.tar"
sha256sum "$BACKUP/filestore-baseer_prod.tar" > "$BACKUP/filestore-baseer_prod.tar.sha256"

release_compose run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 -d baseer_prod -u baseer_purchase_expense_dashboard,baseer_sales_dashboard --stop-after-init --workers=0 --max-cron-threads=0'
snapshot "$RELEASE" "$BACKUP/protected-post.json"
cmp "$BACKUP/protected-pre.json" "$BACKUP/protected-post.json"
release_compose exec -T db psql -U "$DB_USER" -d "$DB" -At -c \
  "SELECT count(*) FROM ir_module_module WHERE name IN ('baseer_purchase_expense_dashboard','baseer_sales_dashboard') AND state = 'installed'" | grep -Fx 2

ln -sfn "$RELEASE" "$CURRENT"
release_compose up -d odoo
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:18069/web/login >/dev/null; then break; fi
  sleep 2
done
curl -fsS http://127.0.0.1:18069/web/login >/dev/null
curl -fsS https://baseer.abroj.sa/web/login >/dev/null
! release_compose logs --tail=120 odoo | grep -Eqi 'Traceback|CRITICAL|FATAL'

printf '{"candidate":"%s","previous":"%s","backup":"%s","protected_snapshot":"match","status":"deployed"}\n' \
  "$CANDIDATE" "$(basename "$PREVIOUS")" "$BACKUP" > "$BACKUP/cutover-evidence.json"
trap - ERR
echo "DEPLOYED:$CANDIDATE"
