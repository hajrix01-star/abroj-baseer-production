# BP-S6 — departure award workflow and receipt independent review

Reviewer: om_review. Date: 2026-09-08. Ownership limited to this document. Accepted BP-S5 19.0.1.2.1 is the baseline. No reviewer application/database mutations.

## R1 — G0–G4 GO

Read `BASEER-EOS-WORKFLOW.md` and the existing EOS/native payment architecture. **G0, G1, G2, G3 and G4 are GO; implementation and the bounded report delegation may begin.** The user authorized a sequential employee departure/award/payment/print journey, reusing native departure and the existing independent EOS model. Keeping the original accounting API and adding wrappers/source-backed status/report is appropriate. No second settlement ledger, new benefit formula, loan offset, blanket rights waiver or automatic financial action on merely opening a screen is included.

Binding acceptance details:

1. Employee button resolves the actual recorded departure version and stable native reason XML IDs, locks and reuses the issued or latest matching draft. No departure, foreign company or insufficient role must be rejected. Reopen must not change an existing user's dates/reason/evidence/confirmation or recalculate an issued award. Unknown reasons route to explicit human review. New-request preparation calculates an estimate only; issuing remains a separate explicit approval.
2. Preserve existing EOS duplicate-event/reservation guards and native bill/payment authority. Received amount must use actual native payment reconciliation allocations to this bill, not whole-payment totals when a payment spans documents. Pending/in-process payments, write-offs and credit-note allocations cannot qualify as received cash. A final receipt requires the full award covered by valid native paid allocations, a posted bill and zero residual, with posted reversal/cancellation suppressing the final receipt. Show truthful entitlement statements otherwise; zero estimates never get artificial payments/bills.
3. Snapshot identity and calculation facts only through the private approval path, protecting effective create defaults and subsequent writes. Names/IDs/reason/dates/calculation facts are stable on reprint; native received/remaining/status remains live so a reversal does not retain a stale paid acknowledgement. Old awards without the snapshot must clearly use the documented fallback, with no silent historical backfill. Do not truncate monetary values or change source identity to fit the page.
4. Enforce read/company/payroll role checks in the report backend, including direct report-route calls with forged docids/context/data. Rendering must derive values from authorized records and native accounting, not client data claiming paid/amount/status. Native accountants may continue their allowed bill/payment workflow without being granted general payroll request access. No simulated employee/company signature or external transfer is implied by printing.
5. Use one native QWeb portrait A4 per award with bounded long text, readable Arabic/English and Western numerals, separate employee/company signature/date spaces and acknowledgement limited to the specified EOS sum. Keep outstanding salary/loan documents in their existing Financial Record paths; they need not be recopied onto this receipt. Verify long-name, partial, full, reversed and reprint cases by rendering the actual report, not a reconstructed document.
6. Focused tests must cover same-departure replay, known/unknown mapping, historical/archived employee, source/default spoofing, native partial/full/pending/write-off/credit/reversal conditions, report ACL/direct-route protection and no new bill on reprint. Preserve all original financial/employee/company rows, coherent QA backup and prior artifact. The 10,000-employee/100-company scale is a design assumption only; measured single-record/PDF durations do not establish that capacity or an SLA. QA only; no production promotion.

EWR-001: Explicit G0–G4 GO communicated before application edits. Reviewer owns only this document. G5–G8 await implementation and scoped independent delivery evidence.

## R2 — narrow generated-request uniqueness amendment

Executor identified the repeatable-read boundary: an advisory employee lock serializes execution but does not refresh a transaction's earlier database snapshot, so two first-time button calls could each see no draft. **G2 amendment GO** for an internal readonly `departure_entry` Boolean and partial unique index `(employee_id, service_end) WHERE departure_entry`. This is a source identity guard, not a new ledger, and is preferable to a dummy employee write merely to force a conflict.

Protect effective client create/default/write values; only the private employee-entry path may set the flag. Existing manual drafts are reused unchanged and need no marker backfill. Record the new schema/default-false field and preserve original columns when comparing existing records. Keep original approved-event uniqueness and durable bill reservation guards. The losing concurrent request may receive a clear native uniqueness/business message and reopen to the existing record; only claim automatic common-result retry if actually demonstrated in a fresh transaction. Final acceptance needs two real independent connections and proof that no second generated draft or bill survives.

## R3 — G5–G8 / قرار التسليم المستقل: GO للقاعدة التجريبية فقط

**EWR-002: GO** لمرشح `baseer_payroll 19.0.1.3.0` في `baseer_reports_qa_20260907` بتاريخ 2026-09-08. لا توجد موانع مفتوحة في نطاق BP-S6. هذا اعتماد لمسار التجربة المحدد، وليس ترقية للأصلية أو اعتمادًا جديدًا لسياسة احتساب المكافأة القانونية. أُجريت المراجعة وفق alpha-delivery-team، بفحص عميق للسلطة المالية والصلاحيات والتزامن، وفحص موجّه للواجهة والتقرير. لم يعد المراجع تشغيل معاملات الاختبار أو يعدل التطبيق أو قاعدة البيانات.

خريطة الأثر المعتمدة في عقد BP-S6 امتداد محلي للبنية السابقة: الموظف/إصدار بياناته ومغادرته الأصلية ← إجراء محمي يعيد استخدام `baseer.hr.eos` ← اعتماد الفاتورة الأصلي ← تسجيل السداد الأصلي ← مطابقات الفاتورة ← بيان QWeb. هوية المستند تحفظ مرة عند الاعتماد، أما إثبات الاستلام فيقرأ المطابقات الحالية. لا يوجد دفتر سداد موازٍ أو تغيير في معادلة EOS أو خصم تلقائي للسلف. افتراض 100 شركة و10,000 موظف ليس سعة مثبتة بالقياس.

### نتيجة مراجعة المصدر والمسارات

| المسار | الدليل والحكم |
|---|---|
| المغادرة وفتح الطلب | فحص `models/eos_workflow.py`: صلاحية مدير الرواتب وقراءة HR والشركة الفعالة، مصدر المغادرة الأصلي، تعيين الأسباب بواسطة XML IDs، إعادة استخدام الطلب المعتمد/المسودة بلا إعادة اعتماد. القيد الجزئي يمنع طلبين مولدين لنفس الموظف/التاريخ. |
| الاعتماد والسداد | الغلاف يستدعي اعتماد EOS الموجود ثم يعيد نفس النموذج؛ الدفع يفتح معالج Odoo للفاتورة ذاتها. الاستلام يحسب `partial.amount` المخصص للفاتورة فقط، ويشترط سدادًا صادرًا أصليًا `paid` و`is_matched`، مع تطابق مبلغ المكافأة بالكامل وصفر المتبقي وغياب عكس مرحّل قبل طباعة إقرار الاستلام النهائي. |
| الحماية وإعادة الطباعة | القيم الافتراضية/كتابة snapshot وعلامة الطلب المولد محمية؛ التقرير يتجاهل قيم العميل ويفحص صلاحية السجلات ودور الرواتب. المسودة القديمة المصدر لا تطبع. هوية المعتمد لا تستبدل بإعادة الفتح، وحالة الدفع تتغير مع العكس. |
| الواجهة والطباعة | فحص وراثة العرض وQWeb، ومشاهدة مستقلة لزر الموظف وصورة الجوال وقوائم الاعتماد/الطباعة، ولصور PDF العربية والإنجليزية والطويلة العربية: مبالغ وأرقام غربية واضحة، مبلغ مستلم/متبقٍ، توقيعان وتاريخان ومساحة صالحة على صفحة A4. نص الإقرار مقصور على مبلغ المكافأة المعروض. |

راجعت نص الاختبارات ونتائجها: **43** تحققًا جديدًا ناجحًا مع rollback، و**46** تحقق انحدار EOS سابقًا ناجحًا مع rollback، و**21** تحققًا في سباقين باتصالين مستقلين في نسخة مؤقتة. دليل السباق يسجل فعليًا تعارض `23505` عند الفتح و`40001` عند الاعتماد، ثم إعادة محاولة بمعاملة جديدة إلى طلب واحد وفاتورة واحدة. هذا لا يثبت أن واجهة Odoo تعيد محاولة `23505` تلقائيًا؛ رسالة إعادة الفتح هي السلوك المقبول الموثق. سبعة ملفات PDF أصلية موجودة بأحجام مطابقة للدليل: عربي مسودة/جزئي/نهائي/معكوس، إنجليزي نهائي، وعربي/إنجليزي نص طويل؛ كل منها صفحة A4 واحدة، نحو 2.2 ثانية محليًا. ليست هذه شهادة أداء إنتاجية.

### تثبيت المرشح والاستعادة

- تحققت مستقلًا من تطابق **30 ملف مصدر** مع `candidate.json` ومن محتوى **30 مدخل ZIP** مع الملفات نفسها، دون اختلاف.
- ZIP: `docs/releases/2026-09-08-baseer-eos-workflow/baseer_payroll-19.0.1.3.0.zip`؛ SHA256 `e5c0f62098ce846598c42621b0f514875643168d7e3b95c8b840de4f84ce21bd`.
- تحققت من ملف النسخة الاحتياطية المشار إليه في `backup.json`: `.local-backups/baseer-eos-workflow-20260908/database.dump`؛ SHA256 `fdac1aee887415c53d4933b9383477468a020e84274f5e2c7031fe13d7daf66a`.
- حزمة BP-S5 السابقة بقيت مطابقة SHA256 `9f97235af9b75ebf697140b082ed3eecfb5f38105afc1ee880678069fbd16479`. تحققت من **210 ملفات Odoo Mates** مقابل manifest المصدر السابق بلا اختلاف. لا يدّعي هذا التقرير commit جديدًا؛ هوية المرشح مصدر/ZIP مثبتان بالبصمة.
- راجعت كود حفظ البصمات قبل/بعد: يقارن الصفوف الأصلية بأعمدتها الأصلية، فلا تخفي أعمدة EOS الجديدة تغييرات قديمة. النتيجة `qa=true, main=true` ضمن الجداول التسعة المقاسة. تشمل QA: 101 قيد، 238 سطرًا، 37 دفعة، 8 موظفين، 10 إصدارات موظف، 6 شركات، 19 جدول عمل، 183 فترة وطلبَي EOS. هذه مطالبة حفظ محددة بهذه الجداول، وليست فحصًا شاملًا لكل جداول النظام.
- الاستعادة المحددة: قاعدة QA الاحتياطية مع مصدر BP-S5 أثناء صيانة؛ لا حذف/إزالة تثبيت للتاريخ المالي. تغييرات BP-S6 ليست إضافة مرفقات دائمة، ولذلك الاحتياط الجديد لقاعدة البيانات مع الحزمة السابقة مناسب لهذا الفرق المحدد. الأصلية خارج النشر.

### حدود مقبولة وغير مانعة

1. المعاملة التي تخلط دفعًا وشطبًا مستبعدة بالكامل من **المبلغ المؤكد** وتحتاج مراجعة محاسبية؛ هذا تحفظ مقصود، لا ادعاء أن الجزء النقدي لم يحدث. التسوية غير النقدية أو حساب وسيط غير مطابق لا ينتج عنها إقرار استلام نهائي، حتى لو سمّتها Community «مسدد».
2. الطلبات المعتمدة القديمة دون snapshot تستخدم بيانات الهوية الحالية مع المعتمد المسجل، دون backfill. النصوص الطويلة تختصر للعرض مع بقاء المصدر الكامل؛ المبالغ لا تختصر. بعض أسماء البيانات الأصلية قد تظهر بلغتها الأصلية.
3. سياسة EOS السابقة `/365` ومسؤولية مراجعة سبب الاستحقاق والإعدادات المحاسبية تبقى كما هي؛ لا إنهاء موظف فعلي ولا صرف حقيقي أو رفع للأصلية ضمن هذه الجولة.

لا توسعة للفريق أو اعتماد مهارات إضافية مطلوبان لهذا الفرق. تغطية الرواتب/S5 غير المتأثرة اعتمدت خط الأساس المجاز سابقًا؛ أُعيدت فقط انحدارات EOS المتصلة بالمصدر والسداد والعكس. أمين التنفيذ سلّم HANDOFF والعقد والاختبارات والحزمة؛ المراجعة المستقلة تثبت القرار أعلاه فقط.

### بصمات الدليل المستقل

لأن candidate.json يثبت المصدر فقط، تحفظ هنا بصمات ملفات الدليل التي راجعها قرار EWR-002.

| ملف الدليل | SHA256 |
|---|---|
| baseer_eos_workflow_checks.py | 97997850c0b7fe108dd410305ec7e6dee08a372c0a6d65a6e25e12d6c88a90ee |
| baseer_eos_workflow_checks.json | 8aa668860d4ca4599ba449e9fc9d7a7de42f1ba7a0613e62e0a7a371c81ec66b |
| baseer_eos_workflow_regression.py | 7bbef6d3b3544ccacadf0d5d5c1ef64c10f7713005fa497991a19cf8832bc6c0 |
| baseer_eos_workflow_regression.json | c2cd41d30eaf0a12365b8aae804e027e5ae31321ca532957774d87bd05609a20 |
| baseer_eos_workflow_concurrency.py | d72b606cb7f24d0bd5718e72a8c44cea22f62e413c6f07055a42c4ab5f1374a1 |
| baseer_eos_workflow_concurrency.json | 7e7319e9b058ae885830d539a073d43db045b9012845539d1e946d0b769e67ff |
| baseer_eos_workflow_ops.py | d7a57d0fa7a31e6e31ad475f92968299388c25c1e60dd15d6cd7acef2d2efb1b |
| eos_employee_button.png | 556e6df16ecb6dc7d7cc9f195644cef294862b0c59d97446e5fcaeb8ef9802f7 |
| eos_workflow_desktop.png | fa9137204e0ddf27a8f49de82e883a1f450731ffbcdbbc83d1c48d34dff86396 |
| eos_workflow_mobile.png | e072c3a3800865e338902481cc45e44beccf46f672579842fb0249befea3b887 |
| eos_final_ar.png | a0955718cc4923cafbd83173f782e3c77cda8aab45e702efcbe8ad7f3c0a3be3 |
| eos_final_en.png | a3eb3e45db7464878ce29427dd14ed8fbd5e1f9f77fecc4b1988ffb1cf70292c |
| eos_long_ar.png | 056294726a7ff0a6f67ab633d1ca65f0e673d0d6b567a5dfe76eba0359c4823f |
| preservation.json | b85a48a8031bd263fd2b83de9cf837f47bf8da9081013881d567f46e782cb889 |
| qa-before.json | a7eddd43d283f728e414770f81b4891e05d7be5309097e05377dd7e39e586c08 |
| main-before.json | ced5342e5642adc0edf1728919fc050ec073f0646b55c7cbec7adb6092c34102 |
| HANDOFF.md | aa2b95bab1e8a226bb85f93a7aefad78a03462daa07744878d6c8614fb122f9e |
| eos_final_ar.pdf | 8c00398b3dfcf4fd08aaa4bc66b6641d8454cbebfa64c67a6b7e873bbafe2a5d |
| eos_final_en.pdf | 421d305b4fb57ba7554292f758f02813004a3191716d7cf7acc913c9a763dbb2 |
| eos_long_ar.pdf | 20be9d49dfe9012eb8c7490adcabb48cedba02cce56e1b66eaf8214492d387ab |
| eos_long_en.pdf | 10177d70cfede808e8cf448d930b256e999362d4e9dbccbf4ab5b80c5b82e32d |
| eos_partial_ar.pdf | 10134058276a743dd7914a290b0a6c85dd382cf8d31d87919da22481cb53b01a |
| eos_reversed_ar.pdf | d4eb4280925b9754d5bda2270570e8e32439f9e90e1bc7e6be0a7464d59981bf |
| eos_statement_ar.pdf | f06aa3341ce418a92fb98109786814bd7bbe48fe4fe5b01961346bd56f6fcfe2 |
