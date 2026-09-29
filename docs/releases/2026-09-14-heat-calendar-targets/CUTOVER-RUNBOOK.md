# دليل إطلاق مرشح أهداف التقويم الحراري

ينفذ فقط بعد قرار **GO** مستقل من فريق ألفا للتسليم، ومن جلسة shell موثوقة
على Hostinger. لا تطبع `.env` أو أي كلمة مرور.

## هوية الحزمة

- الوسم: `heat-calendar-targets-candidate-2026-09-14.8`
- المرجع: `19237ce44b22efcd942b9ee677678989ceb32a97`
- الأرشيف: `baseer-heat-calendar-targets-19237ce.tar.gz`
- SHA-256: `ad52bd619399001af7259df452cd0bfc5ca6ad6c94f0982058847e29494967de`
- إصدار الإضافة: `19.0.1.0.8`

المصدر الوحيد المسموح هو الأرشيف المبني في لينكس من الوسم، والمرفوع في GitHub
Release. لا تستخدم حزمة من محطة التطوير.

## 1. تجهيز المصدر بلا لمس `current`

```bash
set -euo pipefail
base=/srv/abroj-baseer-production
candidate=19237ce
archive_name=baseer-heat-calendar-targets-19237ce.tar.gz
expected_sha=ad52bd619399001af7259df452cd0bfc5ca6ad6c94f0982058847e29494967de
rehearsal="$base/rehearsals/heat-calendar-$candidate"
archive="$base/incoming/$archive_name"
release="$base/releases/$candidate"
previous="$(readlink -f "$base/current")"
rehearsal_evidence="$rehearsal/acceptance.json"

test -f "$rehearsal/$archive_name"
test -s "$rehearsal_evidence"
test -n "$(find "$rehearsal_evidence" -mmin -1440 -print -quit)"
test "$(jq -r '.candidate.tag' "$rehearsal_evidence")" = "heat-calendar-targets-candidate-2026-09-14.8"
test "$(jq -r '.candidate.commit' "$rehearsal_evidence")" = "19237ce44b22efcd942b9ee677678989ceb32a97"
test "$(jq -r '.candidate.archive_sha256' "$rehearsal_evidence")" = "$expected_sha"
jq -e '.decision == "GO" and .source.database_backup_sha256 and .source.filestore_backup_sha256 and .checks.protected_snapshot_match == true and .checks.ui_84_cells == true and .checks.pos_denied == true and .checks.rpc_measurement_ms' "$rehearsal_evidence" >/dev/null
test -f "$previous/compose.production.yaml"
test ! -e "$release"
install -d -m 0755 "$base/incoming"
install -m 0644 "$rehearsal/$archive_name" "$archive"
test "$(sha256sum "$archive" | awk '{print $1}')" = "$expected_sha"

extract_root="$(mktemp -d "$base/releases/.extract-$candidate.XXXXXX")"
tar -xzf "$archive" -C "$extract_root"
payload="$extract_root/baseer-heat-calendar-targets"
test -d "$payload/custom_addons/baseer_sales_heat_calendar"
mv "$payload" "$release"
rmdir "$extract_root"
install -m 600 "$previous/.env" "$release/.env"
install -d -m 0755 "$release/config"
install -m 644 "$previous/config/odoo.conf" "$release/config/odoo.conf"
release_compose=(docker compose --project-name baseer-odoo-prod --env-file "$release/.env" -f "$release/compose.production.yaml")
"${release_compose[@]}" config --quiet
```

## 2. تجميد قصير ونسخة رجوع متسقة

أوقف Odoo فقط؛ تبقى PostgreSQL متاحة لأخذ dump. لا توقف مشروعاً آخر ولا تحذف
أي volume.

```bash
previous_compose=(docker compose --project-name baseer-odoo-prod --env-file "$previous/.env" -f "$previous/compose.production.yaml")
"${previous_compose[@]}" stop odoo
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$base/backups/heat-calendar-targets-$timestamp"
mkdir -p "$backup"
"${previous_compose[@]}" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null
"${previous_compose[@]}" exec -T db sh -lc 'pg_dump -Fc -U "$POSTGRES_USER" baseer_prod' </dev/null > "$backup/baseer_prod.dump"
sha256sum "$backup/baseer_prod.dump" > "$backup/baseer_prod.dump.sha256"
docker run --rm -v baseer-odoo-prod-odoo-data:/source:ro \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; test -d /source/filestore/baseer_prod; tar -C /source -cf - filestore/baseer_prod' \
  > "$backup/filestore-baseer_prod.tar"
sha256sum "$backup/filestore-baseer_prod.tar" > "$backup/filestore-baseer_prod.tar.sha256"
```

## 3. ترقية الإضافة وقياس البيانات المحمية

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
  "${previous_compose[@]}" exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "$1"' -- "$snapshot_sql" </dev/null
}
snapshot > "$backup/preupgrade-protected-snapshot.json"
"${release_compose[@]}" run --rm --no-deps --entrypoint sh odoo -lc \
  'odoo --config=/etc/odoo/odoo.conf --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
   --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19 \
   -d baseer_prod -u baseer_sales_heat_calendar --stop-after-init --workers=0 --max-cron-threads=0'
snapshot > "$backup/postupgrade-protected-snapshot.json"
cmp "$backup/preupgrade-protected-snapshot.json" "$backup/postupgrade-protected-snapshot.json"
```

`-u` مقصود: الإضافة مثبّتة مسبقاً؛ لا تستخدم `-i`.

## 4. التحويل الذري وفحص الصحة

```bash
ln -s "$release" "$base/current.next"
mv -Tf "$base/current.next" "$base/current"
"${release_compose[@]}" up -d odoo
for attempt in $(seq 1 60); do
  curl -fsS http://127.0.0.1:18069/web/login >/dev/null && break
  sleep 1
done
curl -fsS http://127.0.0.1:18069/web/login >/dev/null
curl -fsS https://baseer.abroj.sa/web/login >/dev/null
```

بعد فحص HTTP، افتح الداشبورد كمستخدم مدير: اختر الشركة الفعالة، ثم اختبر حفظ
هدفين مختلفين لخميس وجمعة داخل الشهر نفسه، وحفظاً متعدد الخلايا عبر شهرين. تحقق
أن اللون/النسبة يتحدثان بعد الإغلاق، وأن ملخصات المبيعات نفسها لم تتغير. افتح
جلسة أخرى قبل الحفظ وتحقق أن نسخة قديمة تتطلب التحديث. لا تمنح SHAMI TAX لأي
مستخدم أثناء هذه العملية.

## 5. الرجوع قبل إعادة فتح الخدمة فقط

```bash
test -s "$backup/baseer_prod.dump" && test -s "$backup/filestore-baseer_prod.tar"
sha256sum -c "$backup/baseer_prod.dump.sha256"
sha256sum -c "$backup/filestore-baseer_prod.tar.sha256"
"${release_compose[@]}" stop odoo || true
"${previous_compose[@]}" exec -T db sh -lc 'dropdb -U "$POSTGRES_USER" --force baseer_prod && createdb -U "$POSTGRES_USER" baseer_prod' </dev/null
"${previous_compose[@]}" exec -T db sh -lc 'pg_restore -U "$POSTGRES_USER" -d baseer_prod --no-owner --no-privileges' < "$backup/baseer_prod.dump"
docker run --rm -i -v baseer-odoo-prod-odoo-data:/target \
  odoo@sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd \
  bash -lc 'set -euo pipefail; test -d /target/filestore; rm -rf /target/filestore/baseer_prod; tar -C /target -xf -; chown -R 100:101 /target/filestore/baseer_prod' \
  < "$backup/filestore-baseer_prod.tar"
ln -s "$previous" "$base/current.rollback"
mv -Tf "$base/current.rollback" "$base/current"
"${previous_compose[@]}" up -d odoo
```

لا تستعد قاعدة حية بعد عودة المستخدمين أو بعد عمليات جديدة؛ عندها يعالج الخلل
بإصلاح أمامي وخطة حادثة.
