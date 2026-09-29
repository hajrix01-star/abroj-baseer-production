# CAS1 — independent company accounting seed review

Reviewer: om_review. Date: 2026-09-08. Ownership: this review document only. No application/database mutation by reviewer. Baseline: accepted BP-S6 payroll 19.0.1.3.0.

## R1 — G0–G4 GO

**CASR-001: G0, G1, G2, G3 and G4 are explicitly GO.** Implementation may begin within COMPANY-ACCOUNTING-SEED.md as clarified by CAS-002. User authority covers automatic ready configuration for independent companies in QA. A companion `baseer_company_setup` using native localization and the existing seven Payroll Settings references is a reasonable minimum change; no modification of payroll arithmetic, vendor source or accounting authority is required. This gate is design approval, not final delivery approval.

Native source inspected: `account/models/company.py` create/precommit and localization loading; `account/models/chart_template.py` load/reload/branch behavior; `account/models/account_account.py` native code allocation and ancestor/descendant uniqueness; `odoo/tools/misc.py` callback FIFO behavior; current Baseer company configuration validation and Saudi exact template account rows. Parent continues implementation and native verification independently.

### Binding approved scope

1. **Root companies only.** Native branches retain their inherited charts/memberships untouched. Current Baseer payroll requires direct `company in account.company_ids`, so branch readiness is deliberately deferred, not falsely claimed or obtained by expanding shared account memberships. Lock the root/company before rereading seed identities and configuration. Native shared/ancestor code uniqueness remains authoritative.
2. **Destructive native chart load guarded.** An empty Saudi root means no chart and no accounts, journals, taxes or accounting moves anywhere in its child subtree, including inactive/shared accounts. Native `_existing_accounting()` only checks journal items and is insufficient: `_load` can delete manually prepared unused setup. Preserve any such setup and any established chart. Foreign/unknown uninitialized roots defer to native localization. Do not silently convert existing currency/country. The installed dependency resolves `l10n_sa` before callbacks; no module installation, transaction reset, explicit commit or swallowed partial failure inside a seed callback.
3. **Fill only missing references.** Preserve configured accounts/journals, their types/codes/reconciliation and user customization. Reuse known Saudi salary/deduction/EOS XML IDs only after company/type compatibility checks. Create dedicated reconcilable salary payable and advances receivable rather than retyping native accrued salary/prepaid accounts. Newly created identities are deterministic and noupdate; changed/archive identities must not result in duplicates or reactivation. Invalid existing configuration must not be silently replaced merely to advertise readiness.
4. **Journals and direct payment default are bounded.** Missing starter journals may use native creation. Fill an empty manual outbound payment account only for a fresh or wholly unused journal with no move/payment history, and only where its native liquidity is compatible `asset_cash` with `reconcile=False`. Do not flip a reconciliation flag, overwrite a configured method or touch used journals. Existing pending payment/receipt evidence must remain unchanged. No global partner accounting property changes.
5. **Atomic authority and hook behavior.** Company create first enforces native permissions; only the authorized returned company gets scoped privileged completion. Clean context defaults, explicitly select the company, and use private helpers that cannot be invoked by RPC. Completion after native chart callbacks and after native `_load` must be idempotent and recursion-safe. New callbacks added during precommit execute in the same native FIFO loop: avoid indefinitely rescheduling the same missing localization. Failure rolls back the encompassing create/install transaction rather than leaving partially ready bookkeeping. Opening screens never issues documents.

### Evidence required before G8

- New independent Saudi company: real native chart and all seven compatible settings, expected journals, and native payroll/advance/EOS/bill/payment paths proven on rollback fixtures. Confirm currency behavior and native company authority. No production records, real departure or financial transaction committed.
- Existing chart, manual uninitialized setup, shared/inactive accounts and branch cases: no replacement/deletion/membership expansion. Preserve populated mappings and configured/used bank methods. Foreign/unknown root remains explicitly deferred when not localized.
- Repeated seed/install, rename/archive, deterministic identity and code collision; polluted default context; unauthorized create/helper call; concurrent replay or native transaction-conflict recovery where applicable. No duplicate account/journal or partial callback state after failure.
- Separate coherent QA backup before install, source-only companion artifact plus immutable BP-S6 dependency identity, original financial/employee/EOS fingerprints, explicit whitelist for changed company references and any unused payment method defaults. Main unchanged. Account/journal additions and method changes must be enumerated, not hidden by checking only previous financial rows.
- Native existing Settings UI shows the completed references, including current company10 missing EOS fields; its existing award remains untouched. Single-company timing is evidence for that operation only, not proof of the assumed 100-company capacity.

No open design blocker remains after CAS-002. G5–G8 await implemented source, runtime evidence and final independent alpha-delivery review. Main promotion remains outside scope.

## R2 — initial G5 implementation review

Reviewed companion `models/company.py`, manifest and XML initializer. No change to application/DB by reviewer. Hook order is structurally bounded: native `_load` completes and sets the chart before its wrapper calls the seed; the nested prepare sees the established chart, so the empty-chart branch does not recurse indefinitely. Native callbacks execute in FIFO order in the same transaction. Existing-row lock invalidation and deterministic identities still need real transaction replay evidence; no dummy accounting write is requested.

Concrete findings sent to executor before final acceptance:

| ID | Priority | Finding / bounded correction | Status |
|---|---|---|---|
| CASR-002 | P1 | Initial code checks account-code collision only on direct company membership. A branch-only account may occupy a root seed code and cause native ancestor/descendant uniqueness to reject installation. Always invoke native `_search_new_account_code(code, cache=set())`, which tests the full native scope and preserves a free starting code. | Await fix/test |
| CASR-003 | P1 scope | Native `_pre_load_data` assigns the fiscal-country currency when accounting is empty. An existing uninitialized Saudi company intentionally in USD must not silently become SAR under the preservation promise. Defer conflicting existing companies or explicitly distinguish authorized native new-company initialization; verify preservation on an existing conflict fixture. | Await policy/guard/test |
| CASR-004 | P2 | Remembered journals are returned without validating their expected type. An unused seeded payroll journal changed to another type and then unassigned could be put back as the payroll mapping. Preserve customization but reject/defer incompatible or archived journals when filling required mappings; never retype/reactivate. Test the changed-type identity. | Await fix/test |

Final gate remains pending. These findings do not rescind the approved architecture; they are bounded implementation/preservation acceptance items.

## R3 — corrected source verified, final evidence pending

Source corrections independently verified: CASR-002 now always uses the native code allocator with an empty cache; CASR-003 loads an empty Saudi root only when its current currency equals Saudi currency; CASR-004 rejects changed journal types and prevents an archived payroll journal from being assigned into a missing mapping. An archived purchase journal is preserved and does not fill an empty EOS reference. These three source findings are resolved, subject to their final acceptance fixtures. Native company onboarding may independently choose SAR before the companion callback; the companion itself must not convert an existing currency conflict.

Reviewed the preservation operation's full original-row comparison and whitelist, not only its summary booleans. Current evidence enumerates six companies' formerly empty references, 14 new accounts, six new journals, two new method lines and one formerly unconfigured manual outbound method on an unused journal; existing financial/employee/EOS rows and populated mappings remain unchanged. Root remains responsible for refreshing this evidence after all tests. The race evidence reports 31 passing assertions with two separate database connections and a real `40001` transaction retry converging on one set of defaults, while native chart accounts/starter journals remain unchanged. Final test suite is still completing extra fixture cases; no G8 decision is made in R3.

## R4 — قرار التسليم المستقل G8: GO للقاعدة التجريبية

**CASR-005: GO** لمرشح `baseer_company_setup 19.0.1.0.0` في `baseer_reports_qa_20260907`، للشركات المستقلة فقط، بتاريخ 2026-09-08. أُغلقت CASR-002 وCASR-003 وCASR-004 بالمصدر المصحح وأدلة الاختبار النهائية. لا موانع مفتوحة في نطاق CAS1. هذا لا يجيز نقل الحزمة أو البيانات إلى الأصلية ولا يعلن جاهزية الفروع تلقائيًا.

المراجعة وفق مسار alpha-delivery-team موجهة للفرق المحاسبي عالي الأثر: السلطة الأصلية للشركة/الدليل، حفظ الإعدادات، التزامن، وربط مرشح المصدر بالأدلة. خريطة CAS1 السابقة معتمدة: إنشاء شركة مصرح به → تهيئة الدليل الأصلية للشركة المؤهلة → تعبئة الإعدادات الناقصة → مسارات الرواتب والسلف والمكافأة الأصلية. الحزمة إضافة مستقلة ولا تغير مصدر الأرصدة أو الحسابات المالية. لم ينفذ المراجع معاملات قواعد بيانات أو يعاود الاختبارات؛ راجع المصدر والاختبارات والنتائج وتحقق من الملفات والبصمات بصورة مستقلة.

### قبول الأعمال والدليل

| المطلوب | الدليل النهائي والنتيجة |
|---|---|
| شركة سعودية جديدة جاهزة | الاختبار ينشئ شركة فعلية ويمرر callbacks الأصلية قبل rollback، ويتحقق من الدليل والضريبة وSAR والمراجع السبعة ودفاتر المبيعات/المشتريات/البنك/النقد/الرواتب. لا مستندات مالية من التهيئة وحدها. |
| عمل الوظائف بالإعدادات | مسار أصلي كامل على بيانات مؤقتة: سلفة 100، مسير راتب 1000 وسداده، واعتماد مكافأة EOS وسداد فاتورتها بالإعدادات نفسها؛ لم تبدل الاختبارات المراجع لإنجاح الدفع. |
| حماية الموجود | 137 تحققًا ناجحًا دون traceback ومع rollback، تتضمن الأكواد المشغولة في الفروع، الحساب المشترك غير النشط، الضرائب اليدوية دون دليل، العملة المخالفة، الأرشفة وتغيير النوع، الدفاتر المستخدمة وطرق الدفع المهيأة، الصلاحيات وحقن context ومنع RPC الخاص. |
| التزامن | 31 تحققًا ناجحًا باتصالين مستقلين في نسخة مؤقتة، مع `40001` فعلي وإعادة محاولة بمعاملة جديدة؛ انتهى الاثنان إلى المراجع نفسها، حسابين إضافيين ودفتر رواتب واحد، بلا قيود مالية أو مضاعفة هويات. إزالة النسخة المؤقتة موثقة في تسليم المنفذ. |
| واجهة المستخدم | شاهد المراجع صورتَي Payroll Settings الأصلية بالعربية: إعدادات الرواتب السابقة للشركة10 باقية، وحساب EOS رقم400008 ودفتر المشتريات ظاهران. لا واجهة جديدة؛ قابلية استجابة Settings تعتمد خط الأساس الأصلي، ولم يدّع هذا الفحص لقطة جوال جديدة. |
| حفظ البيانات | راجع المراجع كود المقارنة النهائي ونتيجته: `main_unchanged=true` و`qa_preserved=true` دون issues. لا إضافة/تغيير في الجداول المالية/الموظفين/EOS المقاسة. الإضافات المعلنة14 حسابًا و6 دفاتر و2 أسطر طريقة دفع؛ التعبئة6 شركات ووسيلة دفع قديمة واحدة كانت فارغة ودفترها غير مستخدم. المراجع المعبأة سابقًا والسجلات الأصلية محفوظة. لا تعميم لهذه المقارنة على جداول غير واردة في عملية الفحص. |

الأرقام المقاسة: إنشاء شركة ودليلها وإكمال precommit نحو **1.90 ثانية**، وإعادة تشغيل التهيئة لست شركات نحو **0.088 ثانية** في QA. هذه قياسات موضعية، وليست إثبات سعة 100 شركة أو اتفاق مستوى خدمة. معادلات الرواتب/المكافآت وتقارير PDF لم تتغير؛ لم تكرر مراجعتها الشاملة.

### سلسلة المرشح والرجوع

- تحققت مستقلًا من **7 ملفات مصدر و7 مداخل ZIP** مقابل `candidate.json` دون اختلاف. الحزمة `docs/releases/2026-09-08-company-accounting-seed/baseer_company_setup-19.0.1.0.0.zip`، SHA256: `14716ad9b693118569b5493c0469ed13604a1212e7f9dcddd8d8f21f808efc99`.
- النسخة الاحتياطية موجودة وتطابق `backup.json`: `.local-backups/company-accounting-seed-20260908/database.dump`، SHA256: `1c7f7020e179aaf46364a15ce6f34fd229e5fcdaac28ec74cbdd90bb155e7cd8`.
- مصدر BP-S6 المتطلب السابق **30 ملفًا** وحزمته لم يتغيرا؛ ZIP SHA256: `e5c0f62098ce846598c42621b0f514875643168d7e3b95c8b840de4f84ce21bd`. كذلك تحققت من **210 ملفات Odoo Mates** بلا اختلاف. الهوية هنا بالحزمة وبصمات المصدر، لا بادعاء Git commit جديد.
- الرجوع المنسق: قاعدة QA قبل التثبيت مع استبعاد companion من التشغيل أثناء الصيانة؛ لا إزالة دفاتر/حسابات قد أصبحت مستخدمة ولا uninstall للتاريخ المالي. الأصلية بقيت خارج النشر.

### الحدود المقبولة

الفروع مؤجلة وتحتفظ بالمشاركة الأصلية. الشركات غير المهيأة ذات البلد المجهول أو التوطين الأجنبي أو إعداد يدوي قائم أو العملة المخالفة لا تُحوّل تلقائيًا إلى الدليل السعودي. تهيئة أودو الأصلية للشركة الجديدة قد تحدد العملة قبل الإضافة. الإعدادات المعدلة/المؤرشفة وطرق الدفع المهيأة أو المستخدمة لا تُستبدل لإخفاء الحاجة إلى المراجعة. الشركة10 أصبح لديها إعداد EOS؛ طلبها الحالي لم يُعتمد أو يُصرف تلقائيًا. لا توسع في الفرق أو الاعتماديات مطلوب لهذا التسليم.

### بصمات دليل CASR-005

| ملف الدليل | SHA256 |
|---|---|
| company_accounting_seed_checks.py | 285cd482e5e58d99b41b5e546ac2f13fc4c85122f319b52ddf9de251e1eb60cf |
| company_accounting_seed_checks.json | da03d255f5011f90a20f5026d77f5aadac35f776e633f03c017420ce9161293c |
| company_accounting_seed_concurrency.py | 83df305a2e05407899fb0735fc56c087d1ecbf4ca996d907f0c4fccb4400d321 |
| company_accounting_seed_concurrency.json | fac6839104b02eb883a8f1b4eb4d436847b2c8562d16732b9e0f15968243d2fc |
| company_accounting_seed_ops.py | e6c04eee5f30ac89226dece888476ac14f45fe94091bc04aef669dab03467343 |
| company_accounting_seed_settings.png | f33dedf2cb8c1e6c2994b70a6c755810a5f6d9b5c4a1c8f2cde413e5a26a8295 |
| company_accounting_seed_eos_settings.png | 710bb4c809d167518f884f3f6d54bc23fc7281ab85429447a9c7d2f2b265f19b |
| preservation.json | ecd4ae8104ec95da07f786f59056e18c83b57f6615453a745fc306e2d8c32533 |
| qa-before.json | 59446648053545314dbbf9886bfce7bd97231dfd7b9f06259416bd3d00e756cf |
| main-before.json | b70ab423b9fdf6aed3e7ea0aa286e0baf2dfc0739cf47c992ba07f254b321ce2 |
| HANDOFF.md | 640db3727fbaf504f85731f0958861b5a923bc16489116b9f8c2af193a114c8d |
