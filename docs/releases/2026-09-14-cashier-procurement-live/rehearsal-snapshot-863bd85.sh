#!/usr/bin/env bash
set -euo pipefail

root=/srv/abroj-baseer-production/rehearsals/cashier-procurement-863bd85
prod=/srv/abroj-baseer-production/current
db=baseer_cashier_rehearsal_863bd85
rcompose=(docker compose --env-file "$root/.env" -f "$root/compose.yaml")
pcompose=(docker compose --project-name baseer-odoo-prod --env-file "$prod/.env" -f "$prod/compose.production.yaml")

for attempt in $(seq 1 60); do
  if "${rcompose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${rcompose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$root/evidence/baseer_prod_${timestamp}.dump"
test ! -e "$backup"
"${pcompose[@]}" exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" baseer_prod' > "$backup"
test -s "$backup"
sha256sum "$backup" > "$root/evidence/source-db.sha256"

docker run --rm --volumes-from baseer-odoo-prod-odoo-1:ro \
  -v baseer-odoo-cashier-rehearsal-863bd85-odoo-data:/target \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc "set -euo pipefail; src=/var/lib/odoo/filestore/baseer_prod; dst=/target/filestore/${db}; test -d \"\$src\"; install -d -o 100 -g 101 -m 0755 \"\$dst\"; cp -a \"\$src\"/. \"\$dst\"/; chown -R 100:101 \"\$dst\""

docker run --rm --volumes-from baseer-odoo-prod-odoo-1:ro \
  -v baseer-odoo-cashier-rehearsal-863bd85-odoo-data:/target \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc "set -euo pipefail; for d in /var/lib/odoo/filestore/baseer_prod /target/filestore/${db}; do printf '%s|files=' \"\$d\"; find \"\$d\" -type f | wc -l; printf '%s|manifest=' \"\$d\"; (cd \"\$d\"; find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | awk '{print \$1}'; done" > "$root/evidence/filestore-manifest.txt"

"${rcompose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$backup"
"${rcompose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "select count(*) from ir_module_module"' > "$root/evidence/restored-module-count.txt"

printf 'REHEARSAL_SNAPSHOT_RESTORED=%s\n' "$timestamp"
