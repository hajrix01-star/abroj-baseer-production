#!/usr/bin/env bash
# Restore a fresh production recovery pair into isolated Docker/PostgreSQL
# targets.  It never points an Odoo process at baseer_prod or the live volume.
set -Eeuo pipefail
umask 027

readonly BASE=/srv/abroj-baseer-production
readonly DB_CONTAINER=baseer-odoo-prod-db-1
readonly ODOO_VOLUME=baseer-odoo-prod-odoo-data
readonly BACKUPS="$BASE/backups"

die() { printf 'REHEARSAL=FAILED\nREASON=%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die 'root is required'

old_release="$(readlink -f "$BASE/current")"
[ -d "$old_release" ] || die 'current release cannot be resolved'
[ -f "$old_release/.env" ] || die 'current .env is missing'
[ -f "$old_release/config/odoo.conf" ] || die 'current odoo.conf is missing'

snapshot_sql=$(cat <<'SQL'
SELECT jsonb_build_object(
  'account.move', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_move),
  'account.move.line', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_move_line),
  'account.payment', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_payment),
  'purchase.order', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM purchase_order),
  'purchase.order.line', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM purchase_order_line),
  'sale.order', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM sale_order),
  'sale.order.line', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM sale_order_line),
  'stock.picking', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM stock_picking),
  'stock.move', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM stock_move),
  'hr.employee', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM hr_employee),
  'hr.payslip', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM hr_payslip),
  'res.partner.non_user', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(p.id), 0), 'w', coalesce(max(p.write_date)::text, '')) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id = p.id)),
  'baseer.pos.summary', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_pos_summary),
  'baseer.pos.summary.allocation', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_pos_summary_allocation),
  'baseer.heat.target', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_heat_calendar_target),
  'baseer.occasion', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_official_occasion)
);
SQL
)

snapshot_for_db() {
    local database=$1
    printf '%s\n' "$snapshot_sql" | docker exec -i --env TARGET_DB="$database" "$DB_CONTAINER" sh -lc 'psql -U "$POSTGRES_USER" -d "$TARGET_DB" -Atq'
}

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
rehearsal_db="baseer_rehearsal_${stamp//[^0-9A-Za-z_]/_}"
rehearsal_volume="baseer-production-rehearsal-${stamp,,}"
backup="$BACKUPS/rehearsal-$stamp"
created_db=0
created_volume=0

cleanup() {
    local status=$?
    trap - EXIT
    set +e
    if [ "$created_db" -eq 1 ]; then
        docker exec "$DB_CONTAINER" sh -lc "dropdb -U \"\$POSTGRES_USER\" --if-exists '$rehearsal_db'" >/dev/null 2>&1 || true
    fi
    if [ "$created_volume" -eq 1 ] && [[ "$rehearsal_volume" == baseer-production-rehearsal-* ]]; then
        docker volume inspect "$rehearsal_volume" >/dev/null 2>&1 && docker volume rm "$rehearsal_volume" >/dev/null 2>&1 || true
    fi
    exit "$status"
}
trap cleanup EXIT

mkdir -p "$backup"
snapshot_for_db baseer_prod > "$backup/protected-live.json"
docker exec "$DB_CONTAINER" sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" -d baseer_prod' > "$backup/baseer_prod.dump"
docker run --rm --network none -v "$ODOO_VOLUME":/source:ro -v "$backup":/target alpine:3.20 sh -lc 'tar -C /source -cf /target/filestore-baseer_prod.tar filestore/baseer_prod'
sha256sum "$backup/baseer_prod.dump" "$backup/filestore-baseer_prod.tar" > "$backup/recovery.sha256"
sha256sum -c "$backup/recovery.sha256"

docker exec "$DB_CONTAINER" sh -lc "createdb -U \"\$POSTGRES_USER\" '$rehearsal_db'"
created_db=1
docker exec -i "$DB_CONTAINER" sh -lc "pg_restore -U \"\$POSTGRES_USER\" --no-owner --no-privileges -d '$rehearsal_db'" < "$backup/baseer_prod.dump"
snapshot_for_db "$rehearsal_db" > "$backup/protected-restored.json"
cmp "$backup/protected-live.json" "$backup/protected-restored.json"

docker volume create "$rehearsal_volume" >/dev/null
created_volume=1
docker run --rm --network none -v "$rehearsal_volume":/target -v "$backup":/backup:ro alpine:3.20 sh -lc '
    set -eu
    mkdir -p /target/filestore
    tar -xf /backup/filestore-baseer_prod.tar -C /target
    test -d /target/filestore/baseer_prod
'

odoo_image="$(docker inspect baseer-odoo-prod-odoo-1 --format '{{.Config.Image}}')"
docker run --rm --network baseer-odoo-prod-backend \
    --env-file "$old_release/.env" \
    -e REHEARSAL_DB="$rehearsal_db" \
    -v "$rehearsal_volume":/var/lib/odoo \
    -v "$old_release/config/odoo.conf":/etc/odoo/odoo.conf:ro \
    -v "$old_release/custom_addons":/mnt/baseer-addons:ro \
    -v "$old_release/third_party_addons":/mnt/third-party-addons:ro \
    --entrypoint sh "$odoo_image" -lc '
        odoo --config=/etc/odoo/odoo.conf --db_host=db --db_user="$POSTGRES_USER" --db_password="$POSTGRES_PASSWORD" \
          --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
          -d "$REHEARSAL_DB" --db-filter="^${REHEARSAL_DB}$" --stop-after-init --workers=0 --max-cron-threads=0
    ' > "$backup/odoo-rehearsal.log" 2>&1
snapshot_for_db "$rehearsal_db" > "$backup/protected-after-odoo.json"
cmp "$backup/protected-live.json" "$backup/protected-after-odoo.json"

printf 'REHEARSAL=GO\nBACKUP=%s\nDATABASE=%s\nVOLUME=%s\n' "$backup" "$rehearsal_db" "$rehearsal_volume" | tee "$backup/result.env"
