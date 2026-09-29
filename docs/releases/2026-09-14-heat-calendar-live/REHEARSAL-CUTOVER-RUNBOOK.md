# Runbook — التقويم الحراري إلى الإنتاج

## قاعدة الأمان

- لا يُنفَّذ هذا الدليل على `baseer_prod` إلا بعد قرار **GO** مستقل لفريق ألفا للتسليم.
- البروفة تستخدم اسم مشروع وDB وvolumes وnetwork ومنفذ جديدة تبدأ بـ`baseer-odoo-heat-rehearsal-<candidate>`؛ لا تشارك أي مورد مع `baseer-odoo-prod`.
- لا تُطبع ملفات `.env` ولا كلمات مرورها. تحفظ في ملفات بصلاحية `0600` على المضيف فقط.
- المعرفات (لوحة البيانات والشركات) تستخرج من **قاعدة البروفة نفسها**، ولا تُثبت داخل أي اختبار.

## مدخلات الإصدار

احتفظ بالقيم التالية في سجل الإثبات دون أسرار: `CANDIDATE_TAG` و`CANDIDATE_COMMIT` و`ARCHIVE_SHA256` و`PAYLOAD_SHA256` ووقت snapshot. يبنى الـarchive حصراً من الـtag، لا من worktree.

## بروفة معزولة قابلة لإعادة التنفيذ

نفّذ الأوامر التالية من مستخدم تشغيل مخول على Hostinger بعد استبدال `<candidate>` بالوسم القصير و`<port>` بمنفذ loopback غير مستخدم:

```bash
set -euo pipefail
candidate='<candidate>'
root="/srv/abroj-baseer-production/rehearsals/heat-calendar-${candidate}"
db="baseer_heat_rehearsal_${candidate}"
project="baseer-odoo-heat-rehearsal-${candidate}"
mkdir -p "$root"/{source,config,evidence}
install -m 600 /srv/abroj-baseer-production/current/.env "$root/.env"
install -m 644 /srv/abroj-baseer-production/current/config/odoo.conf "$root/config/odoo.conf"
sha256sum "$root/baseer-heat-calendar-candidate-${candidate}.tar.gz"
tar -xzf "$root/baseer-heat-calendar-candidate-${candidate}.tar.gz" -C "$root/source"
```

أنشئ compose خاصاً بالـcandidate من قالب `outputs/heat-calendar-live/rehearsal-compose.yaml`: حدّث فقط `name` و`POSTGRES_DB` و`--database` و`--db-filter` واسم الـport وvolumes/networks لكي تتضمن `<candidate>`. ثم:

```bash
docker compose --env-file "$root/.env" -f "$root/compose.yaml" config --quiet
docker compose --env-file "$root/.env" -f "$root/compose.yaml" up -d db
docker compose --env-file "$root/.env" -f "$root/compose.yaml" exec -T db \
  sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

خذ snapshot جديداً **للبروفة فقط** من الإنتاج قبل الاستعادة، مع حفظ الـhash والوقت، ثم انسخ filestore قراءةً من volume الإنتاج إلى volume البروفة:

```bash
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose -p baseer-odoo-prod -f /srv/abroj-baseer-production/current/compose.production.yaml \
  exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" baseer_prod' > "$root/evidence/baseer_prod_${timestamp}.dump"
sha256sum "$root/evidence/baseer_prod_${timestamp}.dump" | tee "$root/evidence/source-db.sha256"
# أسماء volumes أدناه تستخرج من compose المرشح؛ الإنتاج لا يشارك volume أو network مع البروفة.
docker run --rm --volumes-from baseer-odoo-prod-odoo-1:ro \
  -v "${project}_odoo-data:/target" \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc "set -euo pipefail; src=/var/lib/odoo/filestore/baseer_prod; dst=/target/filestore/${db}; test -d \"\$src\"; install -d -o 100 -g 101 -m 0755 \"\$dst\"; cp -a \"\$src\"/. \"\$dst\"/; chown -R 100:101 \"\$dst\""
docker run --rm --volumes-from baseer-odoo-prod-odoo-1:ro \
  -v "${project}_odoo-data:/target" \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc "set -euo pipefail; for d in /var/lib/odoo/filestore/baseer_prod /target/filestore/${db}; do printf '%s|files=' \"\$d\"; find \"\$d\" -type f | wc -l; printf '%s|manifest=' \"\$d\"; (cd \"\$d\"; find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum) | sha256sum | awk '{print \$1}'; done" | tee "$root/evidence/filestore-manifest.txt"
# PostgreSQL أنشأ قاعدة $db الفارغة من POSTGRES_DB عند تشغيل خدمة db؛ لا تنشئها مرة ثانية.
docker compose --env-file "$root/.env" -f "$root/compose.yaml" exec -T db \
  sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' < "$root/evidence/baseer_prod_${timestamp}.dump"
```

شغّل Odoo للبروفة واختبر المرشح فقط:

```bash
docker compose --env-file "$root/.env" -f "$root/compose.yaml" up -d odoo
docker compose --env-file "$root/.env" -f "$root/compose.yaml" exec -T -e POSTGRES_DB="$db" odoo sh -lc \
  'odoo shell --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d "$POSTGRES_DB"' < "$root/rehearsal-protected-snapshot.py" > "$root/evidence/preinstall-protected-snapshot.json"
docker compose --env-file "$root/.env" -f "$root/compose.yaml" run --rm --no-deps -e POSTGRES_DB="$db" --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d "$POSTGRES_DB" -i baseer_sales_heat_calendar \
   --stop-after-init --workers=0 --max-cron-threads=0 --test-enable --test-tags /baseer_sales_heat_calendar \
  ' | tee "$root/evidence/module-tests.log"
docker compose --env-file "$root/.env" -f "$root/compose.yaml" exec -T -e POSTGRES_DB="$db" odoo sh -lc \
  'odoo shell --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d "$POSTGRES_DB"' < "$root/rehearsal-protected-snapshot.py" > "$root/evidence/postinstall-protected-snapshot.json"
cmp "$root/evidence/preinstall-protected-snapshot.json" "$root/evidence/postinstall-protected-snapshot.json"
```

أنشئ `HC_REHEARSAL_PASSWORD` مؤقتاً في shell فقط، ثم شغّل فحص ORM بالمسار والـaddons الصريحين أدناه. يمرّر `-e` السر المؤقت إلى container دون تخزينه أو طباعته:

```bash
export HC_REHEARSAL_PASSWORD="$(openssl rand -hex 24)"
docker compose --env-file "$root/.env" -f "$root/compose.yaml" exec -T \
  -e HC_REHEARSAL_PASSWORD odoo sh -lc \
  'odoo shell --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d "$1"' -- "$db" < "$root/rehearsal-checks.py" | tee "$root/evidence/orm-checks.log"
grep '^HC_METADATA|' "$root/evidence/orm-checks.log" | sed 's/^HC_METADATA|//' > "$root/evidence/metadata.json"
unset HC_REHEARSAL_PASSWORD
```

يسجّل السكربت `HC_METADATA` (لوحة البيانات وIDs الشركات من قاعدة البروفة) وsnapshot قبل/بعد للنماذج المحمية، وفحص POS المحدود ومدير الشركة. مرّر القيم الناتجة إلى `rehearsal-performance.py` و`rehearsal-concurrent.py` بدلاً من أي IDs ثابتة. احفظ المخرجات JSON/log في `$root/evidence`.

معايير القبول: جميع اختبارات HC-T تمر؛ snapshots متساوية؛ أربع شركات (ARZ، المعلم الشامي، دوحة المستهلك، SHAMI TAX) تنجح؛ POS محدود يُمنع خارج شركته؛ المدير ينشئ هدفاً داخل شركته؛ p95 الدافئ ≤2s، و20 قارئاً مصادقاً ينجحون. بعد القياس احذف مستخدم البروفة المؤقت أو أتلف البروفة كلها.

## قطع الإنتاج بعد GO فقط

نفّذ هذا القسم فقط بعد قرار **GO** مستقل، وفي نافذة صيانة معلنة. لا تعيد استعمال snapshot البروفة.

### 1. تحضير مصدر الإصدار دون لمس `current`

انسخ الـarchive الذي تمت مطابقته مع GitHub إلى `incoming` (بـSCP من جهاز الإصدار أو قناة artifact موثقة)، ثم نفّذ التالي على المضيف. لا ينسخ `.env` أو `odoo.conf` من الـarchive؛ هما إعدادان محليان ينقلان من الإصدار الحي السابق فقط.

```bash
set -euo pipefail
base=/srv/abroj-baseer-production
candidate=52e9ff5
archive="$base/incoming/baseer-heat-calendar-candidate-52e9ff5-verified.tar.gz"
archive_sha=9be4c6ae1fd7957e29d28babbfb98ad28d0c9f00aa7e0792720e28574b3e97d7
release="$base/releases/$candidate"
previous="$(readlink -f "$base/current")"
test -n "$previous" && test -f "$previous/compose.production.yaml"
test ! -e "$release"
test "$(sha256sum "$archive" | awk '{print $1}')" = "$archive_sha"
mkdir -p "$release"
tar -xzf "$archive" -C "$release"
test -d "$release/custom_addons/baseer_sales_heat_calendar"
grep -F 'heat-calendar-candidate-2026-09-14.3' "$release/RELEASE-RECEIPT.md"
install -m 600 "$previous/.env" "$release/.env"
install -d -m 0755 "$release/config"
install -m 644 "$previous/config/odoo.conf" "$release/config/odoo.conf"
release_compose=(docker compose --project-name baseer-odoo-prod --env-file "$release/.env" -f "$release/compose.production.yaml")
"${release_compose[@]}" config --quiet
```

### 2. تجميد قصير ونسخة recovery متسقة

أوقف خدمة Odoo الحية فقط؛ تبقى قاعدة PostgreSQL جاهزة لأخذ dump. لا توقف مشروعاً آخر ولا تحذف volume.

```bash
previous_compose=(docker compose --project-name baseer-odoo-prod --env-file "$previous/.env" -f "$previous/compose.production.yaml")
"${previous_compose[@]}" stop odoo
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/heat-calendar-$timestamp"
mkdir -p "$backup"
"${previous_compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${previous_compose[@]}" exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" baseer_prod' > "$backup/baseer_prod.dump"
sha256sum "$backup/baseer_prod.dump" > "$backup/baseer_prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; test -d /source/filestore/baseer_prod; tar -C /source -cf - filestore/baseer_prod' \
  > "$backup/filestore-baseer_prod.tar"
sha256sum "$backup/filestore-baseer_prod.tar" > "$backup/filestore-baseer_prod.tar.sha256"
```

### 3. قياس البيانات قبل/بعد وتثبيت one-off من المصدر الجديد

هذا الاستعلام لا يكتب بيانات؛ يثبت أن التثبيت لا يغير نماذج الأعمال المحمية. يبقى `current` مشيراً إلى المصدر السابق أثناء التثبيت، بينما `run` يحمّل الـadd-on فقط من `$release` عبر compose الخاص به.

```bash
snapshot_sql="SELECT jsonb_build_object(
  'account.move', (SELECT count(*) FROM account_move),
  'account.move.line', (SELECT count(*) FROM account_move_line),
  'account.payment', (SELECT count(*) FROM account_payment),
  'hr.employee', (SELECT count(*) FROM hr_employee),
  'hr.payslip', (SELECT count(*) FROM hr_payslip),
  'res.partner', (SELECT count(*) FROM res_partner p WHERE NOT EXISTS (SELECT 1 FROM res_users u WHERE u.partner_id = p.id)),
  'baseer.pos.daily.report', (SELECT count(*) FROM baseer_pos_daily_report)
);"
snapshot() {
  "${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "$1"' -- "$snapshot_sql"
}
snapshot > "$backup/preinstall-protected-snapshot.json"
"${release_compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --http-port=18069 --gevent-port=18070 \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d baseer_prod -i baseer_sales_heat_calendar --stop-after-init --workers=0 --max-cron-threads=0'
snapshot > "$backup/postinstall-protected-snapshot.json"
cmp "$backup/preinstall-protected-snapshot.json" "$backup/postinstall-protected-snapshot.json"
```

### 4. التحويل الذري وsmoke

لا تحرك `current` قبل نجاح الأمر السابق ومطابقة snapshot. يحل `mv -T` محل symlink فقط؛ لا يحذف الإصدار السابق.

```bash
ln -s "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
"${release_compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18069/web/login >/dev/null; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18069/web/login >/dev/null
```

بعد HTTP smoke، يتأكد مشغل مخوّل عبر `https://baseer.abroj.sa/web/login` من فتح الداشبورد واختيار الشركات المخوّلة له فقط. لا يضاف `SHAMI TAX` إلى أي مستخدم خلال cutover؛ ظهوره يظل تابعاً لـ`company_ids` الحالية للمستخدم.

### 5. تراجع قبل إعادة فتح الخدمة فقط

إذا فشل install أو snapshot أو HTTP smoke **قبل** إعادة فتح الخدمة للمستخدمين، استعد الزوج الذي أخذ في الخطوة 2 ثم أعد symlink السابق. هذه أوامر استرجاع مقصودة ومقيدة بالمسارات التي تحققت أعلاه:

```bash
test -s "$backup/baseer_prod.dump" && test -s "$backup/filestore-baseer_prod.tar"
sha256sum -c "$backup/baseer_prod.dump.sha256"
sha256sum -c "$backup/filestore-baseer_prod.tar.sha256"
docker run --rm -i \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; tar -tf - | grep -E "^filestore/baseer_prod/" >/dev/null' \
  < "$backup/filestore-baseer_prod.tar"
"${release_compose[@]}" stop odoo || true
"${previous_compose[@]}" exec -T db sh -lc 'dropdb -U "$POSTGRES_USER" --force baseer_prod && createdb -U "$POSTGRES_USER" baseer_prod'
"${previous_compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d baseer_prod --no-owner --no-privileges' < "$backup/baseer_prod.dump"
docker run --rm -i -v baseer-odoo-prod-odoo-data:/target \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; test -d /target/filestore; rm -rf /target/filestore/baseer_prod; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod' \
  < "$backup/filestore-baseer_prod.tar"
ln -s "$previous" "$base/current.rollback"
mv -Tf "$base/current.rollback" "$base/current"
"${previous_compose[@]}" up -d odoo
```

بعد إعادة فتح الخدمة أو تنفيذ أي عملية أعمال جديدة، لا تسترجع قاعدة حية فوق تلك العمليات؛ طبّق إصلاحاً أمامياً وخطة حادثة بدلاً من ذلك.
