# NSI-1 — تضمين مبيعات نوركس في الداشبورد والتقويم (QA فقط)

## عقد G0 وخريطة الأثر

المستخدم فوّض التنفيذ في 2026-11-06 واختباره على QA أولًا. المفتاح «تضمين مبيعات نوركس / Include Noorix sales» افتراضيًا مغلق، ويغير العرض فقط في Sales dashboard وHeat calendar، بما يشمل العدد المسجل للعملاء. لا نشر LIVE ولا تعديل لفواتير أو قيود أو ضرائب أو إعدادات زاتكا أو مستندات EDI أو إرسال خارجي.

المصدر المجمد للبناء `official/main@f636d72ef`، فرع مستقل `codex/noorix-sales-toggle-qa-20261106` وشجرة معزولة `.w/noorix-sales-toggle`. المصدر المحلي القديم غير المستخدم للبناء هو HEAD85524d9. أعيد استخدام لجنة الفحص في `output/sales-source-committee-20261106/REVIEW.md` ودليل نوركس اللاحق بدل تكرار استكشاف سبتمبر.

**تصحيح الخريطة:** النسخة الحالية تملك بالفعل `models/unified_sales.py` يجمع الملخصات وPOS وفواتير Sales، والتقويم الحالي يستعمله. لا facade جديدة ولا تغيير في `daily_report.py` أو مركز القيادة التنفيذي.

الدورة: قيد نوركس الموجود والمرحل هو السلطة المالية ← دليل تقرير مرتبط بهوية المصدر الحقيقية يوفر العملاء/تغطية اليوم فقط ← قارئ يتحقق من الأصل والحالة والشركة والتاريخ والمبلغ ← الجامع الموحد الحالي ← الداشبورد والتقويم. فتح التقرير لا ينشئ أو يعتمد أو يرسل مستندًا. تُستخرج المبالغ من خطوط الإيراد والضريبة المسجلة، لا من العميل ولا من إعادة حساب ضريبة مفترضة.

معايير القبول: false يحافظ على النتائج القائمة؛ true يعرض خمس قيم الأيام 1–5 نوفمبر 2026 (8113،8167،8733،8293،11498) ومجموع المجموعة44804 وعدد العملاء126،123،129،131،149 ومجموع658؛ لا ادعاء أنها كامل إيراد الشركة قبل مصالحة بقية المصادر. روابط التفاصيل متطابقة، والحرارة والتاريخ والمقارنة يستعملون الاختيار نفسه. رقمDS-001 المتكرر ليس هوية مصدر. الأعداد عدادات يومية وليست عملاء فريدين عبر الأيام.

## G1 — السعة والاستمرارية

الحجم المثبت5ملخصات/5أيام، حتى5قنوات لكل يوم؛ التصميم يفترض حتى10000دليل تقرير للشركة/السنة و5قارئين متزامنين كتقدير غير مقاس. لا حركة مالية أو خلفية عند القراءة. تعاد الاستفادة من سقف100000صف للجامع، وتدخل أدلة وخطوط القيود ضمنه. الفهارس شركة/تاريخ وهوية مصدر فريدة، قراءة دفعية دون N+1، وحد أقصى واضح لاستيراد الأدلة. لا queue أو cache أو خدمة جديدة. هدف قراءة شهر مع تاريخ حرارة8أسابيع أقل3ثوانٍ كهدفQA لا وعد إنتاج. التراجع إغلاق المفتاح أو إعادة الإصدار السابق؛ الأدلة التشغيلية تبقىDB ولا تُخزن كبيانات أعمال فيGit.

مبرر اختبارQA: الفرق يضيف مصدرًا ماليًا وتغطية عملاء؛ الفحوص القائمة لا تغطي تداخل قيد نوركس وPOS/الفواتير أو فقد الهوية؛ الاستخدام المثبت5أيام/شركة واحدة. قياس محدود واحد مناسب، دون حمل إنتاج أو إنشاء بيئات متكررة.

## G2 — عقد المصدر والهوية

- نموذج أدلة تقرير صغير داخل الموديول المالك، وليس جدول مبيعات مستقل: company،source_system/tenant/company/summary_id الحقيقي،move_id الأصلي،business_date،period_scope،customer_count،source_gross كدليل مطابقة،وقت/بصمة المصدر؛ source_gross لا يحل محل مبلغ القيود. استيراد إداري صريح ومحدود فقط، بلا حفظ تلقائي عند القراءة ولا بيانات تشغيلية في مصدرGit. لا تشغيل لترحيل سبتمبر الذي ينشئPOS.
- هوية اقتصادية فريدة مركبة، وربط بالقيد من `src:<id>` بعد التحقق من الشركة. هويةmove فريدة أيضًا؛ تكرار الإدخال المتطابق لا يكرر الأثر؛ تعارض الهوية/المبلغ يرفض ذريًا. الربط بملخص معتمد لنفس الحدث مثبت صراحة إن وُجد؛ لا جمع تلقائي ولا حذف اعتمادًا على المبلغ والتاريخ.
- يقبل القارئ posted entry فقط، SAR، الشركة الفعلية نفسها، مرجع مصدر مضبوط، وإيراد/ضريبة متصالحين مع قيمة المصدر، بلا ملكيةPOS/invoice/payment مصطنعة. لا يجمع طرفي القيد. الحالة الغامضة أو اختلاف الأصل بعد الاستخراج تُرفض برسالة واضحة.
- نطاق all-day لنفس الشركة واليوم لا يتداخل مع ملخص آخر غير مثبت الهوية؛ يظهر تعارض بدلاً من جمع صامت. POS/فاتورة صغيرة لا تُحذف بسبب مبلغها. عكس القيد الكامل يُتبع بالعلاقة الأصلية وبإشارته وتاريخه، دون تكرار العملاء؛ التصحيح الجزئي أو الغامض يفشل بأمان إلى عقد مدعوم.
- مبلغ القيود وعملاؤها يضافان مرة واحدة في `_baseer_unified_period`؛ المراجع والbounds/capacity والحالي/السابق وكلhistoryheat تتبع المفتاح. الدفع يبقى تغطيته غير معروفة إلى أن يثبت تصنيف القنوات؛ لا تحصيلات مخترعة. الورديات لا تقسم يومًا كاملًا تخمينيًا.
- publicRPC تقبلBooleanحقيقي فقط، افتراضيfalse. يُعاد تمريره صراحة بعد تنظيف السياق في نقطتيالدخول ولا يُوسع `clean_context` العام. حدودالشركة وACL الأصلية باقية؛ لاsudo أوإضافة مجموعاتمحاسبة للمستخدم.
- العملاء معلومون فقط من دليل المصدر المرتبط والمطابق؛ المجهولnull وتغطيةجزئية، والحرارة لا تساوي posted باكتمال اليوم بلا دليلall-day. لاخلطSHAMIمعSHAMITAX.

## G3 — الرصة والمسار المباشر

Odoo19/Python/Owl/المكوناتالأصليةالموجودة فقط، لا مكتبات أوشبكة من التقرير. تمديد جامعالمبيعاتالقائم أقلأثرًا من نسخPOS أوإنشاءفاتورة أوإعادةكتابةالتقارير. ملفاتالنطاق: salesdashboard models/UI/security/evidence/test/translations وheat models/UI/tests/translations؛ dailyreport/account.move/core والزاتكا خارجالتعديل. CI القائم test-baseer-command-center يتضمن UnifiedSales وHeat؛ تُضاف اختباراتالمصدر الجديد له. QA يمرعبرPRوفحوصوسياسةمجمّدة للموديولينفقط والغلافالمحمي؛ لاproductionpolicy.

## G4 — الواجهة

checkboxأصلي واحد موحدالنص بجوارفلتر/تحديث كللوحة، AR/EN وRTL/LTR وأرقام0–9، يطبقعلىكلpayload الحالي والتفاصيل ولا يتركاستجابةقديمة بعدتبديله. افتراضيfalse يحافظعلىعرضالمستخدم؛ حالةالعرضواضحة. لاحركة أومكتبة أومكوّنعامجديد. اختبارسطحمكتبوعرض390px بالمفتاحوالشهر والشركة وروابطالتفاصيل.

## سجل البوابات

| البوابة | الحالة | المالك | المراجع/الدليل |
|---|---|---|---|
| G0 | معتمد من خبير ERP المستقل | قائدالبناء + خبيرERP | مراجعة NSI-1 بتاريخ 2026-11-06؛ نطاق QA وعرض فقط، الأصل المالي دون تغيير؛ NSI005 |
| G1 | معتمدة | قائدالبناء/السعة | معماري الخريطة المستقل راجع NSI-1 وأجاز السعة المحددة، دون شهادة حمل |
| G2 | معتمد من خبير ERP المستقل | قائدالبناء | عقد الهوية والمساهمة والأدلة والعكس مقبول قبل الكود؛ مراجعة المعماري المستقلة لبقية البوابات؛ NSI005 |
| G3 | معتمدة | قائدالبناء/أمينالمكتبات | معماري الخريطة المستقل أجاز Odoo/Owl القائمين بلا اعتماد جديد |
| G4 | معتمدة للتصميم | بناءالواجهة | معماري الخريطة المستقل أجاز checkbox أصلي؛ القبول البصري لاحقًا |
| G5–G8 | غير مبدوءة | — | التنفيذ والفحوص والتسليم المستقل بعداعتمادG0–G3 |

### NSI006 — اعتماد البوابات قبل الشفرة

راجع المعماري المستقل G1/G2/G3/G4 وأجازها للتصميم، واعتمد خبير ERP المستقل G0/G2 في NSI005. يبدأ الكود بعد هذا الاعتماد. شروط المعماري: false لا يقرأ الأدلة ولا يضيف متطلب ACL؛ سقف استيراد10000دليل/طلب؛ قراءة شركة محددة وإدخال إداري قابل للتتبع. لا اعتماد نشر من هذه المراجعات.

## السجل الحي — إضافة فقط

| ID | المرحلة | النية/النتيجة | الأثر |
|---|---|---|---|
| NSI001 | قبلG0 | إعادةاستخداملجنةالفحصوثبوتالعملاءفيالخمسةأيام؛ قراءةAGENTSومهاراتألفاوالسجلاتوالفروعوالحاويات. | قراءةفقط |
| NSI002 | G0–G3 | fetch official/main نجح إلىf636d72ef؛ المعماريثبتوجودunified_salesوالتقويمالحالي؛ يسقطاقتراحfacadeسبتمبر. | لاصلاحياتأومكتباتجديدة |
| NSI003 | تشغيل/قراءة | SSHبلاكتابة تعذر(publickey/hostkey)؛ لاخادمالإنتاجتغير. مسارQAالمحميقائمولايتطلبتجاوزمصادقة. | لاادعاءوصولQAعنSSH |
| NSI004 | توثيق | إنشاءفرعمستقلوشجرةمعزولةمنofficial/main وكتابةهذاالعقدقبلأيشفرة. | لمتبدأتعديلاتالتطبيق؛ انتظارمراجعةالبواباتالداخلية |
| NSI005 | اعتماد G0/G2 مستقل — ERP | اعتمد خبير ERP المستقل عقد NSI-1 للـQA قبل الكود: أدلة العملاء في DB، استيراد إداري صريح، لا كتابة عند العرض؛ القيود الأصلية وحدها سلطة المبلغ. دليل الهوية السابقة: `custom_addons/baseer_noorix_migration/models/migration_models.py:302–330`؛ استخراج العملاء/هوية المصدر/الفاتورة: `tools/noorix_migration/build_sales_summary_payload.mjs:55–75`؛ يُمنع استخدام مستورد سبتمبر لأنه ينشئ ويعتمد ملخصات في `tools/noorix_migration/apply_qa_sales_summary_payload.py:162–176`. | قبول تصميم لا إثبات تنفيذ: فحص روابط الملكية الأصلية الموجودة قبل المساهمة، والهوية الاقتصادية مرة واحدة؛ التعارض يعلن عدم اكتمال التغطية ولا يعرض مجموعًا جزئيًا بوصفه كاملًا. عكس كامل مرتبط بإشارته وتاريخه دون تكرار العملاء؛ الجزئي الغامض مرفوض. 44804 مجموع المجموعة و658 مجموع عدادات العملاء اليومية؛ لا اعتماد شامل لإيراد الشركة أو امتثال ضريبي، ولا اختبارات منفذة بهذه المراجعة. |

### NSI007 — implementation and isolated QA

The existing unified reader is extended through `noorix_evidence.py` and `noorix_reporting.py`; native daily report and executive dashboard are unchanged. Metadata import is explicit and administrative, atomic and idempotent; views never synchronize Noorix over the network. There is no scheduled remote sync in this candidate. Actual business evidence must be verified and imported separately into its intended database; the acceptance seed is synthetic and exists only in local QA.

Tests run in pinned Odoo19 `sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd`, PostgreSQL16, database `baseer_noorix_toggle_qa_20261106`, separate Docker network/volume. An initial59-test run found fixture ACL omissions and a false-context regression; both corrected. A68-test run exposed invalid raw-list `any!` domain syntax and a fixture sales ACL omission; native baseline tests passed. Correct `odoo.fields.Domain` objects and fixture-only groups resolved these. No user permissions were expanded.

Final backend candidate run `baseer-noorix-toggle-tests-r4-20261106`: **32 post-tests / 0 failures / 0 errors**, 2026-11-06 11:33:36UTC,27.78s. This rerun was required by the final source-action optimization and two new native POS/approved-summary collision cases. It includes immutable metadata, strictBoolean/default-off, cross-company/forged-context isolation, hidden reversal via real record rule, older unmapped reversal origin, repeated reads/no writes, financial drift, full reversal/date/customers, native1SAR invoice/POS/summary overlap, non-admin authorized readers, partial/unknown coverage, and existing EDI state/payload invariance with HTTP/EDI processing forbidden during the read. UI suite **14/14** Node passes, including shared selection, native change callbacks, stale responses, company change and recovery after access error.

Actual Chrome local QA displayed **44804.00 SAR / 658** after enabling the switch and the same selection in heat:8113/126,8167/123,8733/129,8293/131,11498/149. Day5 detail opened the single underlying11498SAR move. Disabling heat removed the five source days. An earlier tab stopped responding to all actions, including the Odoo navbar; a fresh tab restored interaction. This is recorded as a browser-control observation, not proof of an application defect. Key screenshots are local QA artifacts under `output/noorix-qa-20261106` outside the source candidate. Focused Arabic copy follow-up translates Full day and explains Noorix business-date attribution; no arithmetic changes.

Independent financial/security delivery reviewer found no demonstratedP1 in the reviewed delta and issued CONDITIONAL GO for isolated QA. Remote QA requires frozen commit, passing PR checks, a two-module QA policy and protected wrapper; LIVE remains outside this authorization. The wrapper already takes a matched database/filestore recovery pair and restores on failure. Native-source overlap in actual company days1–2 must be reconciled before a combined total can be accepted; small invoices are never silently discarded.

G5 implementation complete; G6 backend/UI automated checks passed. G7 browser narrow/English and remote QA deployment receipt remain pending; G8 final independent decision follows candidate freeze and these results.
