WS3 current MAIN release: `40dee029c01cf51fa01d233185b3b63805754ce3` (2026-09-09), frozen `.local-backups/duration-display-20260909/candidate`, HH:MM schedule averages, module19.0.1.0.2. Current evidence: `docs/releases/2026-09-09-duration-display/HANDOFF.md`. Earlier releases below are historical.

WS2 current MAIN release: `c89de592ace16758ad67c4b69efd3a309cf6c950` (2026-09-09), frozen `.local-backups/work-schedule-time-picker-20260909/candidate`, 24-hour work schedule picker, module19.0.1.0.1. Evidence: `docs/releases/2026-09-09-work-schedule-time-picker/HANDOFF.md`. Earlier release descriptions below are historical.

WS1 current MAIN release (2026-09-09): `fd5dd15be755051edb0d695095aa02abc2fc18f0`, frozen source `.local-backups/simple-work-schedules-20260909/candidate`; adds native simple schedule templates and employee setup. Earlier PT1/BN1/MP3 descriptions below are historical. Current evidence: `docs/releases/2026-09-09-simple-work-schedules/HANDOFF.md`.

PT1 current MAIN release (2026-09-09): commit `9c43256987654c4d988cd29c05f5f967b457235a`, frozen source `.local-backups/payroll-company-tab-20260909/candidate`. One inherited company payroll tab disabled; Settings > Payroll remains the company-backed configuration authority. All 782 tables compared, only ir_ui_view changed. Details: `docs/releases/2026-09-09-payroll-company-tab/HANDOFF.md`. Prior BN1 entries below remain historical.

# Baseer ERP على Odoo 19 Community

## التشغيل المحلي

1. انسخ `.env.example` إلى `.env` وحدد كلمة مرور PostgreSQL محلية قوية، وانسخ `config/odoo.local.conf.example` إلى `config/odoo.local.conf` وحدد كلمة مرور Odoo الرئيسية مختلفة.
2. شغّل `docker compose up -d` من هذا المجلد.
3. افتح `http://localhost:18069` وأنشئ قاعدة تطوير. كلمة مرور المدير الرئيسية هي `admin_passwd` من `config/odoo.local.conf`.

تستخدم البيئة المجهزة قاعدة `baseer_dev`. تسجيل الدخول الأولي هو الاسم وكلمة المرور الموجودان في `BASEER_ADMIN_LOGIN` و`BASEER_ADMIN_PASSWORD` ضمن `.env`. هذه ملفات محلية مستبعدة من Git.

تعمل PostgreSQL على `127.0.0.1:15432` فقط لتجنب التعارض مع خدمات أخرى في الجهاز.

## ملكية الكود

- `odoo/`: المصدر الرسمي المنسوخ من Odoo، ولا تُجرى فيه تعديلات لتخصيص Baseer.
- `custom_addons/`: موديولات Baseer المخصصة، وهي المصدر الوحيد لتخصيص الواجهة والعمليات.
- `third_party_addons/`: موديولات خارجية خضعت للمراجعة.
- `compose.yaml` و`config/`: تشغيل محلي موحد للفريق.

## نقطة التثبيت الحالية

آخر تحديث للأصلية هو **BN1** بتاريخ 2026-09-09: حقلا الاسم العربي والإنجليزي للشركات والموردين، إصدار `baseer_service_seed 19.0.1.2.0`. المصدر الحي المجمد هو `.local-backups/bilingual-names-20260909/candidate`، وربط النسخ اليومي محدّث إليه. [توثيق BN1 والفحوص والرجوع](docs/releases/2026-09-09-bilingual-names/HANDOFF.md). المعلومات التالية سجل نقل MP3 السابق.

نُقلت التعديلات المعتمدة FA2 وPB2 إلى الأصلية بتاريخ 2026-09-09، بعد تجربة استعادة وترقية مستقلة ونسخة احتياطية حديثة ومراجعة قبول. التفاصيل والإصدارات والفحوص والرجوع في [توثيق MP3](docs/releases/2026-09-09-main-promotion/HANDOFF.md).

الأصلية `baseer_dev` على [18069](http://127.0.0.1:18069/odoo)، والتجريبية على 18070. يربط `compose.yaml` الأصلية بالمصدر المجمد في `.local-backups/main-promotion-20260909/candidate` للقراءة فقط. يبقى `custom_addons` مصدر التطوير للتجريبية؛ لا تحذف مجلد المرشح الذي تعتمد عليه الأصلية.

نُظمت البيئات بتاريخ 2026-09-09 للاحتفاظ بالأصلية والتجريبية فقط، بعد نسخ قواعد الاختبار الثلاث واختبار استعادتها ثم حذفها وحاويات المراجعة المتوقفة. أُضيف نسخ يومي محلي للأصلية الساعة 03:00 بتوقيت الرياض عبر Codex؛ يعتمد على توفر الكمبيوتر وDocker وCodex. تفاصيل النسخ والاستعادة وحدود النسخ الخارجي في [دليل البيئات والنسخ الاحتياطي](docs/operations/2026-09-09-environments/README.md).
