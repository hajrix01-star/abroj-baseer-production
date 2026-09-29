WS3 current MAIN release: `40dee029c01cf51fa01d233185b3b63805754ce3` (2026-09-09), frozen `.local-backups/duration-display-20260909/candidate`, HH:MM schedule averages, module19.0.1.0.2. Current evidence: `docs/releases/2026-09-09-duration-display/HANDOFF.md`. Earlier releases below are historical.

WS2 current MAIN release: `c89de592ace16758ad67c4b69efd3a309cf6c950` (2026-09-09), frozen `.local-backups/work-schedule-time-picker-20260909/candidate`, 24-hour work schedule picker, module19.0.1.0.1. Evidence: `docs/releases/2026-09-09-work-schedule-time-picker/HANDOFF.md`. Earlier release descriptions below are historical.

WS1 current MAIN release (2026-09-09): `fd5dd15be755051edb0d695095aa02abc2fc18f0`, frozen source `.local-backups/simple-work-schedules-20260909/candidate`; adds native simple schedule templates and employee setup. Earlier PT1/BN1/MP3 descriptions below are historical. Current evidence: `docs/releases/2026-09-09-simple-work-schedules/HANDOFF.md`.

PT1 current MAIN release (2026-09-09): commit `9c43256987654c4d988cd29c05f5f967b457235a`, frozen source `.local-backups/payroll-company-tab-20260909/candidate`. One inherited company payroll tab disabled; Settings > Payroll remains the company-backed configuration authority. All 782 tables compared, only ir_ui_view changed. Details: `docs/releases/2026-09-09-payroll-company-tab/HANDOFF.md`. Prior BN1 entries below remain historical.

# تنظيم نسخ أودو والنسخ الاحتياطي — 9 سبتمبر 2026

تحديث لاحق في اليوم نفسه: نُشر [BN1 للأسماء الثنائية](../../releases/2026-09-09-bilingual-names/HANDOFF.md)، وحُدث ربط المصدر والأرشيف في البرنامج اليومي إليه واختُبر النسخ بعده. يبقى سجل MP3 أدناه تاريخيًا؛ مصدر الأصلية الحالي هو `.local-backups/bilingual-names-20260909/candidate`، ويُحتفظ بالمصدر السابق للرجوع.

## النطاق المعتمد

وافق المستخدم على الاحتفاظ بالأصلية والتجريبية، وأرشفة قواعد الاختبار الثلاث ثم حذفها، وتجهيز نسخ يومي. هذه عملية تشغيل وصيانة؛ لا تغيّر إضافات أودو أو الحسابات أو صلاحيات المستخدمين. مرجع البنية هو [إصدار MP3](../../releases/2026-09-09-main-promotion/HANDOFF.md).

| البيئة | قاعدة البيانات | الاستخدام |
|---|---|---|
| الأصلية | `baseer_dev` | العمل الفعلي، [المنفذ 18069](http://127.0.0.1:18069/odoo) |
| التجريبية | `baseer_reports_qa_20260907` | التطوير والاختبار على المنفذ 18070؛ متوقفة وتشغّل عند الحاجة |

قواعد التقاعد المحددة: `baseer_payroll_eval_20260908`، `baseer_promotion_rehearsal_20260908`، `baseer_release_rehearsal_20260907`. حاويات المراجعة المتوقفة المحددة: `pb2_review`، `fa2_review`، `promotion_rehearsal`، `reports_rehearsal` ضمن مشروع Docker `baseer_odoo_dev` فقط. لا يشمل النطاق مشاريع بصير القديم أو أي مشروع Docker آخر، ولا يشمل حذف volumes أو النسخ الاحتياطية السابقة أو ملفات المصدر المنشورة.

## الأدلة

- [نسخ قواعد الاختبار](retired-backups.json): المسارات والبصمات ومطابقة الاستعادة الفعلية لجميع الجداول، والتحقق من محتوى المرفقات وحجمها.
- [نتيجة التنظيف](cleanup-result.json): القواعد والحاويات المحذوفة وما بقي فعليًا.
- [آخر نسخة للأصلية](latest-main-backup.json): ملفات النسخ وبصماتها وحالة اختبار الاستعادة.
- [التحقق النهائي](verification.json): حالة الأصلية والتجريبية والقواعد بعد العمل.
- [المراجعة المستقلة](REVIEW.md).

الاختبار يحفظ إعدادات ترتيب النصوص `LC_COLLATE` و`LC_CTYPE` ويعيد إنشاء قاعدة التحقق بنفس الإعدادات. اكتشف الفحص الأول اختلاف ترتيب أسماء الجداول فقط بسبب اختلاف لغة قاعدة التحقق؛ لم تختلف الصفوف، ولم يُسمح بالحذف قبل تصحيح الفحص وإعادة اختباره.

## النسخ اليومي

البرنامج التشغيلي هو [environment_backups.py](../../build-governance/environment_backups.py)، والأمر المخصص للأصلية:

```powershell
& 'C:/Users/hp/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 docs/build-governance/environment_backups.py backup-main
```

تُحفظ كل نسخة في مجلد مستقل داخل `.local-backups/environment-maintenance/`، ويتضمن dump لقاعدة البيانات، ومرفقاتها، وإعدادات التشغيل المحلية الخاصة، وأرشيف المصدر الموافق للأصلية. لا تُكتب كلمات المرور في التقرير. هذا المجلد مستبعد من Git؛ يحتوي بيانات خاصة ويجب معاملته كذلك.

يتوقف خادم الأصلية مؤقتًا للحصول على قاعدة ومرفقات متسقة، ثم يعاد تشغيله حتى عند فشل النسخ، ويُفحص رابط الدخول. يرفض البرنامج وجود اتصالات أخرى بالقاعدة أو تشغيل نسختين من عملية الصيانة معًا. إذا كان الخادم متوقفًا أصلًا يبقيه متوقفًا. لا تُشغّل Python بخيار `-O`.

النسخ المعتاد يتحقق من قراءة dump ومحتوى المرفقات والبصمات؛ الاختبار الأول يستخدم `--restore-test` لاستعادة القاعدة ومطابقة جميع الصفوف. يمكن إعادة اختبار الاستعادة بنفس الخيار دوريًا. لا توجد سياسة حذف تلقائي للأرشيفات؛ تُراقب المساحة وتراجع سياسة الاحتفاظ لاحقًا.

الجدولة عبر مهمة Codex يومية الساعة 03:00 بتوقيت الرياض، ويُحفظ تعريفها في [automation.json](automation.json). تعتمد على توفر هذا الكمبيوتر وDocker وCodex؛ ليست خدمة نسخ مستقلة تعمل والكمبيوتر مغلق. تُبلّغ المهمة عند الفشل فقط. يلزم تحديث ربط مصدر النسخة الاحتياطية عند نشر إصدار جديد؛ البرنامج يرفض تغيّر المصدر المنشور أو المحرك عن MP3 حتى يُراجع هذا الربط.

قبل أي تحديث للأصلية، تُنفّذ نسخة جديدة بهذا الأمر ويُتحقق من نجاحها قبل الترقية. هذه قاعدة تشغيل موثقة؛ لا يوجد اعتراض تقني يمنع أي شخص من تحديث أودو يدويًا دون نسخة.

**النسخ خارج الكمبيوتر غير مفعّل بعد:** طُلب من المستخدم تحديد قرص خارجي أو مسار شبكة موثوق. لا يُعد النسخ في قسم آخر من القرص نفسه نسخة خارجية.

## الاستعادة والتشغيل

تُستعاد النسخة أولًا في قاعدة جديدة باسم منفصل، باستخدام PostgreSQL 16 وبيانات `database-metadata.json`، ثم تُستعاد المرفقات تحت اسم تلك القاعدة ومحرك أودو والمصدر المحفوظين. تُطابق البصمات والجداول والمرفقات وتُختبر الواجهة قبل التحويل إليها؛ لا تُكتب فوق الأصلية مباشرة. المجلد `main-promotion-20260909/candidate` ما زال المصدر الحي للأصلية ويجب عدم حذفه.

تشغيل التجريبية عند الحاجة:

```powershell
docker start baseer_odoo_dev-reports_qa-1
```

وإيقافها بعد الاختبار:

```powershell
docker stop baseer_odoo_dev-reports_qa-1
```

ملفات Compose القديمة للمراجعات تبقى كمرجع تاريخي لإعادة التجربة عند الحاجة، لكنها ليست بيئات تعمل. بقيت بعض مجلدات مرفقات اختبارات أقدم بلا قواعد بيانات خارج نطاق الحذف الثلاثي؛ لم تُحذف عشوائيًا ولا تمثل نسخ أودو إضافية.
