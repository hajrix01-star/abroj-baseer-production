#!/usr/bin/env bash
set -euo pipefail

# Cutover is deliberately limited to the immutable 863bd85 cashier-role
# release. It writes an exact recovery pair before upgrading only the two
# affected modules. This script is intended for the approved Hostinger window.
base=/srv/abroj-baseer-production
candidate=863bd85
previous="$(readlink -f "$base/current")"
release="$base/releases/$candidate"
test "$previous" = "$base/releases/4cd1258"
test -d "$release"
test -f "$release/.env"
test -f "$release/config/odoo.conf"
grep -F 'cashier-procurement-live-candidate-2026-09-14.2' "$release/RELEASE-RECEIPT.md" >/dev/null

previous_compose=(docker compose --project-name baseer-odoo-prod --env-file "$previous/.env" -f "$previous/compose.production.yaml")
release_compose=(docker compose --project-name baseer-odoo-prod --env-file "$release/.env" -f "$release/compose.production.yaml")

cutover_started=0
reopened=0
backup=

rollback_before_reopen() {
  status=$?
  trap - ERR
  set +e
  if test "$cutover_started" = 1 && test "$reopened" = 0; then
    "${release_compose[@]}" stop odoo
    if test -n "$backup" && test -s "$backup/baseer_prod.dump" && test -s "$backup/filestore-baseer_prod.tar" && \
       sha256sum -c "$backup/baseer_prod.dump.sha256" >/dev/null && \
       sha256sum -c "$backup/filestore-baseer_prod.tar.sha256" >/dev/null; then
      "${previous_compose[@]}" exec -T db sh -lc 'dropdb -U "$POSTGRES_USER" --force baseer_prod && createdb -U "$POSTGRES_USER" baseer_prod'
      "${previous_compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d baseer_prod --no-owner --no-privileges' < "$backup/baseer_prod.dump"
      docker run --rm -i -v baseer-odoo-prod-odoo-data:/target \
        odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
        bash -lc 'set -euo pipefail; test -d /target/filestore; rm -rf /target/filestore/baseer_prod; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod' \
        < "$backup/filestore-baseer_prod.tar"
    fi
    rollback_link="$base/current.rollback.$candidate.$BASHPID"
    ln -s "$previous" "$rollback_link"
    mv -Tf "$rollback_link" "$base/current"
    "${previous_compose[@]}" up -d odoo
  fi
  exit "$status"
}
trap rollback_before_reopen ERR

cutover_started=1
"${previous_compose[@]}" stop odoo

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/cashier-procurement-$timestamp"
install -d -m 0750 "$backup"
"${previous_compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${previous_compose[@]}" exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" baseer_prod' > "$backup/baseer_prod.dump"
test -s "$backup/baseer_prod.dump"
sha256sum "$backup/baseer_prod.dump" > "$backup/baseer_prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; test -d /source/filestore/baseer_prod; tar -C /source -cf - filestore/baseer_prod' \
  > "$backup/filestore-baseer_prod.tar"
test -s "$backup/filestore-baseer_prod.tar"
sha256sum "$backup/filestore-baseer_prod.tar" > "$backup/filestore-baseer_prod.tar.sha256"

snapshot() {
  "${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d baseer_prod -At' <<'SQL'
SELECT jsonb_build_object(
  'account.move', (SELECT count(*) FROM account_move),
  'account.move.line', (SELECT count(*) FROM account_move_line),
  'account.payment', (SELECT count(*) FROM account_payment),
  'hr.employee', (SELECT count(*) FROM hr_employee),
  'hr.payslip', (SELECT count(*) FROM hr_payslip),
  'res.partner', (SELECT count(*) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id = p.id)),
  'baseer.pos.daily.report', (SELECT count(*) FROM baseer_pos_daily_report),
  'baseer.procurement.request', (SELECT count(*) FROM baseer_procurement_request),
  'baseer.procurement.request.line', (SELECT count(*) FROM baseer_procurement_request_line)
);
SQL
}

snapshot > "$backup/preinstall-protected-snapshot.json"
"${release_compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
    --http-port=18069 --gevent-port=18070 \
    --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
    -d baseer_prod -u baseer_access_roles,baseer_procurement_requests \
    --stop-after-init --workers=0 --max-cron-threads=0' \
  > "$backup/module-upgrade.log" 2>&1
snapshot > "$backup/postinstall-protected-snapshot.json"
cmp "$backup/preinstall-protected-snapshot.json" "$backup/postinstall-protected-snapshot.json"

"${release_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d baseer_prod -AtF "|"' <<'SQL' > "$backup/module-state.txt"
SELECT name, state, latest_version
FROM ir_module_module
WHERE name IN ('baseer_access_roles', 'baseer_procurement_requests')
ORDER BY name;
SQL
grep -Fx 'baseer_access_roles|installed|19.0.1.0.3' "$backup/module-state.txt"
grep -Fx 'baseer_procurement_requests|installed|19.0.11.0.2' "$backup/module-state.txt"

next_link="$base/current.next.$candidate.$BASHPID"
ln -s "$release" "$next_link"
mv -Tf "$next_link" "$base/current"
"${release_compose[@]}" up -d odoo
for attempt in $(seq 1 90); do
  if curl -fsS --max-time 10 http://127.0.0.1:18069/web/login >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS --max-time 10 http://127.0.0.1:18069/web/login >/dev/null
curl -fsS --max-time 20 https://baseer.abroj.sa/web/login >/dev/null
"${release_compose[@]}" logs --no-color --tail=200 odoo > "$backup/odoo-smoke.log"
if grep -E 'Traceback \(most recent call last\)|CRITICAL|FATAL' "$backup/odoo-smoke.log"; then
  exit 1
fi

reopened=1
trap - ERR
printf 'LIVE_CUTOVER_SUCCESS=%s\n' "$backup"
