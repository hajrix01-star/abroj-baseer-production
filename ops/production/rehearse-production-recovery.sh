#!/usr/bin/env bash
# Restore a fresh production recovery pair into isolated Docker/PostgreSQL
# targets.  It never points an Odoo process at baseer_prod or the live volume.
set -Eeuo pipefail
umask 027

readonly BASE=/srv/abroj-baseer-production
readonly DB_CONTAINER=baseer-odoo-prod-db-1
readonly ODOO_VOLUME=baseer-odoo-prod-odoo-data
readonly BACKUPS="$BASE/backups"
readonly REHEARSAL_MODULES=baseer_purchase_batch,baseer_financial_correction,baseer_service_seed,baseer_hr_services

die() { printf 'REHEARSAL=FAILED\nREASON=%s\n' "$*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die 'root is required'

old_release="$(readlink -f "$BASE/current")"
[ -d "$old_release" ] || die 'current release cannot be resolved'
[ -f "$old_release/.env" ] || die 'current .env is missing'
[ -f "$old_release/config/odoo.conf" ] || die 'current odoo.conf is missing'
candidate_source="${1:-}"
[ -n "$candidate_source" ] || die 'expected one candidate source directory argument'
[ -d "$candidate_source" ] && [ ! -L "$candidate_source" ] || die 'candidate source directory is unsafe'
candidate_source="$(readlink -f "$candidate_source")"
for candidate_module in baseer_purchase_batch baseer_financial_correction baseer_service_seed baseer_hr_services; do
    [ -f "$candidate_source/custom_addons/$candidate_module/__manifest__.py" ] || die "candidate module is missing: $candidate_module"
done
compose_old=(docker compose --project-name baseer-odoo-prod --env-file "$old_release/.env" -f "$old_release/compose.production.yaml" --project-directory "$old_release")

wait_for_login() {
    local attempt
    for attempt in $(seq 1 90); do
        curl -fsS --max-time 10 http://127.0.0.1:18069/web/login >/dev/null && return 0
        sleep 1
    done
    return 1
}

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
  'product.template', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM product_template),
  'product.product', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM product_product),
  'product.category', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM product_category),
  'account.analytic.account', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_analytic_account),
  'account.analytic.plan', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_analytic_plan),
  'account.analytic.distribution.model', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM account_analytic_distribution_model),
  'baseer.purchase.category.map', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_purchase_category_map),
  'baseer.purchase.batch', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_purchase_batch),
  'baseer.hr.service', (SELECT jsonb_build_object('n', count(*), 'ids', coalesce(sum(id), 0), 'w', coalesce(max(write_date)::text, '')) FROM baseer_hr_service),
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
service_quiesced=0

cleanup() {
    local status=$?
    local restart_failed=0
    trap - EXIT
    set +e
    if [ "$service_quiesced" -eq 1 ]; then
        "${compose_old[@]}" up -d odoo_data_init >/dev/null 2>&1 || restart_failed=1
        "${compose_old[@]}" up -d odoo >/dev/null 2>&1 || restart_failed=1
        wait_for_login >/dev/null 2>&1 || restart_failed=1
    fi
    if [ "$created_db" -eq 1 ]; then
        docker exec "$DB_CONTAINER" sh -lc "dropdb -U \"\$POSTGRES_USER\" --if-exists '$rehearsal_db'" >/dev/null 2>&1 || true
    fi
    if [ "$created_volume" -eq 1 ] && [[ "$rehearsal_volume" == baseer-production-rehearsal-* ]]; then
        docker volume inspect "$rehearsal_volume" >/dev/null 2>&1 && docker volume rm "$rehearsal_volume" >/dev/null 2>&1 || true
    fi
    if [ "$restart_failed" -ne 0 ]; then
        [ -d "$backup" ] && printf 'REHEARSAL=SERVICE_RESTART_FAILED\n' >> "$backup/result.env"
        exit 70
    fi
    exit "$status"
}
trap cleanup EXIT

mkdir -p "$backup"
# Quiesce production only long enough to capture one consistent DB/filestore
# pair.  The isolated restore and Odoo boot happen after production is healthy
# again, so the rehearsal does not prolong customer downtime.
# Mark it before issuing stop so cleanup revives production even if Docker
# reports an error after having stopped the container.
service_quiesced=1
"${compose_old[@]}" stop odoo
snapshot_for_db baseer_prod > "$backup/protected-live.json"
docker exec "$DB_CONTAINER" sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" -d baseer_prod' > "$backup/baseer_prod.dump"
docker run --rm --network none -v "$ODOO_VOLUME":/source:ro -v "$backup":/target alpine:3.20 sh -lc 'tar -C /source -cf /target/filestore-baseer_prod.tar filestore/baseer_prod'
sha256sum "$backup/baseer_prod.dump" "$backup/filestore-baseer_prod.tar" > "$backup/recovery.sha256"
sha256sum -c "$backup/recovery.sha256"
"${compose_old[@]}" up -d odoo_data_init
"${compose_old[@]}" up -d odoo
wait_for_login
service_quiesced=0

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
    -v "$candidate_source/custom_addons":/mnt/baseer-addons:ro \
    -v "$old_release/third_party_addons":/mnt/third-party-addons:ro \
    --entrypoint sh "$odoo_image" -lc '
        odoo --config=/etc/odoo/odoo.conf --db_host=db --db_user="$POSTGRES_USER" --db_password="$POSTGRES_PASSWORD" \
          --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
          -d "$REHEARSAL_DB" --db-filter="^${REHEARSAL_DB}$" -u "$REHEARSAL_MODULES" --stop-after-init --workers=0 --max-cron-threads=0
    ' > "$backup/odoo-rehearsal.log" 2>&1
snapshot_for_db "$rehearsal_db" > "$backup/protected-after-odoo.json"
cmp "$backup/protected-live.json" "$backup/protected-after-odoo.json"

printf 'REHEARSAL=GO\nBACKUP=%s\nDATABASE=%s\nVOLUME=%s\n' "$backup" "$rehearsal_db" "$rehearsal_volume" | tee "$backup/result.env"
