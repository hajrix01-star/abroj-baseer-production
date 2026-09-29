# مرشح أبرج وبصير للإنتاج

هذا المستودع يحمل **الكود وإعدادات النشر فقط**. لا يضم قاعدة البيانات أو
filestore أو النسخ الاحتياطية أو أسرار التشغيل أو إضافة `baseer_noorix_rehearsal_replay`.

## نطاق الإصدار

- `abroj.sa` موقع أبرج.
- `www.abroj.sa` يعيد توجيهه إلى `abroj.sa`.
- `baseer.abroj.sa` يحول الجذر إلى صفحة دخول Odoo الأصلية `/web/login`.
- Odoo وPostgreSQL وvolumes وشبكة Docker تخص هذا الإصدار وحده. PostgreSQL بلا
  منفذ مضيف، وOdoo متاح محلياً فقط على `127.0.0.1:18069` وراء Nginx.

## تجهيز المضيف

1. انسخ `.env.example` إلى `.env` وأنشئ كلمات مرور طويلة عشوائية.
2. انسخ `config/odoo.conf.example` إلى `config/odoo.conf` واستبدل
   `admin_passwd` بقيمة عشوائية. لا ترفع هذين الملفين إلى Git.
3. شغّل `docker compose -f compose.production.yaml config -q` ثم
   `docker compose -f compose.production.yaml up -d`.
4. انقل dump المرشح وfilestore إلى `secure-input/` عبر قناة إدارية منفصلة؛ لا
   تضعهما في Git. استعد dump إلى `baseer_prod` ثم انسخ filestore إلى
   `baseer-odoo-prod-odoo-data:/var/lib/odoo/filestore/baseer_prod` مع المالك
   `100:101` قبل تشغيل Odoo النهائي.
5. ركب `deploy/nginx/abroj-baseer-bootstrap.conf`، احصل على شهادة تشمل
   `abroj.sa`, `www.abroj.sa`, `baseer.abroj.sa`، ثم استبدله بملف
   `abroj-baseer.conf`. نفذ `nginx -t` قبل كل reload.

## قبول التشغيل

- `https://abroj.sa/` يعرض واجهة أبرج.
- `https://www.abroj.sa/` يعيد إلى النطاق الأساسي.
- `https://baseer.abroj.sa/` يعيد `302` إلى `/web/login` ثم صفحة دخول بصير.
- `https://baseer.abroj.sa/web/database/manager` يعيد `404`.
- لا يستمع PostgreSQL علنًا، ولا يستمع Odoo إلا على loopback.

## الاستعادة والتراجع

قبل أي ترقية، أوقف compose الخاص بهذا الإصدار فقط وخذ dump ونسخة متسقة من
filestore. التراجع هو إعادة آخر زوج متسق DB+filestore ثم `docker compose up -d`؛
لا تعدل أو تعيد تشغيل مشاريع Hostinger الأخرى.
