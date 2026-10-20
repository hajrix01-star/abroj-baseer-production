# BMS-20261020 — معرض المرفقات وإدارة النسخ المحلية

## G0 — عقد البناء والخريطة (قيد المراجعة قبل كود التطبيق)

طلب المالك تنفيذ الاقتراح المعتمد: معرض صور وملفات، تنظيف يدوي للكاش مع
معاينة العدد والحجم، وتنظيف اختياري بعد 30 يومًا من آخر استعمال، واستثناء
الملفات المحتفظ بها دون اتصال. الأساس main/00ccbaa66e28383edcabeca1b5b3d6e4b15f0bdb؛
QA الحالي e0af46e3 / طلب39370626300 مثبت. الفرع codex/bwork-media-storage-20261020.
هذا تنفيذ واختبار مرشح؛ لا دمج أو نشر QA/APK/Live في هذا الطلب دون طلب نشر.

الأدوار: القائد يملك العقد وChatEngine وواجهة RN؛ عامل التخزين يملك runtime
وفهرس SQLite واختباراتهما؛ عامل الخدمة يملك gallery API وواجهة أودو واختباراتهما؛
حارس مستقل يراجع البوابات والمرشح. لا تعارض ملكية أو استكشاف شامل جديد.

الخريطة المعاد استخدامها من BWA/BIL/BSC/BSP:

`Odoo messages + memberships + media -> guarded room gallery GET -> ChatEngine`
`-> sparse gallery associations (NOT history coverage) -> RN gallery / existing media viewer`

`Odoo own-member rooms + same gallery/content GET -> native Owl gallery`

`App storage settings -> guarded runtime serialMedia -> owned cache files + SQLite catalog`

المرفقات الأصلية والرسائل والعضوية من أودو فقط. الإدارة الحالية metadata-only
ليست إذنًا لعرض المحتوى. المعرض في أودو يعرض غرف عضوية المستخدم نفسه فقط، حتى
للمدير. أدوات كاش الجوال داخل التطبيق، لا أمر مركزي لحذف ملفات أجهزة الموظفين.

حدود ERP: لا قراءة ملفات فواتير عامة أو DMS، ولا تعديل مستندات أو قيود أو
مخزون أو الاحتفاظ بالأصل أو صلاحية حذف الرسائل. لا صلاحيات جديدة أو sudo caller.
يظل تنظيف staged غير المرتبط بعد24h كما هو، ولا يستدعي تنظيف الجهاز أي حذف خادم.

معايير القبول:

1. معرض الصور/الملفات/الصوت في غرفة مخولة، وفرز الأحدث/الأقدم/الأكبر وترقيم محدود.
2. تفاصيل الوسيط والفتح والانتقال إلى رسالته لا تتجاوز العضوية أو صلاحية الشركة/الوسائط.
3. لا read receipts بسبب استعراض المعرض، ولا إثبات تاريخ متصل من صفحة وسائط متفرقة.
4. تنظيف يدوي بمعاينة عدد وحجم النسخ القابلة للتنظيف، وتأكيد يوضح أثر عدم الاتصال.
5. لا stage أو part أو outbox أو رفع/تنزيل جارٍ أو lease عرض/تشغيل أو pin دائم ضمن الضحايا.
6. لا حذف لنسخة بلا ارتباط canonical مؤكد؛ يعاد فحص أهلية كل ملف تحت قفل المالك قبل الحذف.
7. سياسة 30 يومًا منذ آخر استعمال معطلة ابتداءً؛ لا إذن OS جديد ولا خدمة خلفية/Firebase.
8. حفظ offline intent معزول بالحساب/الخادم/الغرفة/العضوية؛ لا يتجاوز logout أو سحب الصلاحية/مهلة الحساب.
9. العربية/الإنجليزية والجوال320px وسطح المكتب وحالات الفراغ/الرفض/انقطاع الشبكة كاملة.
10. تبقى ثوابت سرعة عرض صور المرسل وطابور الإرسال وحماية المعاينات السابقة ناجحة.

## G1 — السعة والاستمرارية (قيد المراجعة)

حجم الاستخدام الكامل غير مقدم. لقطة المالك لشركة واحدة تعرض4غرف/5عضويات
وحوالي13.70MiB؛ ليست شهادة سعة للشركات كلها. نعيد استخدام الحدود الفعلية:
كاش128MiB/5000ملف، ملف10MiB كحد أعلى، staging50MiB/200ملف، مصغر128KiB.
صفحة المعرض30 وبحد أقصى60/128KiB، ومؤشر keyset لا offset أو تنزيل تاريخ كامل.
الكاش لا يزيد بسبب pins؛ امتلاء المساحة المحمية يعيد media_quota ولا يحذف pin بصمت.
المصغرات عند الحاجة فقط؛ لا تنزيل جماعي للأصول أو حفظ كاش متصفح أودو دائم.
تنظيف تلقائي محدود الدفعة على بدء/استئناف التطبيق لا على كل صورة، ويحترم آخر استعمال.
اختبارات السعة الجديدة ضرورية فقط لضحية تنظيف متزامنة مع5عمليات/تبدل حساب، وفهرس
5000عنصر اصطناعي؛ الاستخدام المرصود25وسيطًا تقريبًا من اللقطة، لا ضغط QA أو Live.
الهدف الأول: استجابة UI فورية مع عمل غير حاجب؛ لا وعد بزمن هاتف أو شبكة غير مقاس.

## G2 — العقود والسلطة (قيد المراجعة)

GET إضافي `/bchat/api/v2/rooms/<room_id>/media` بقيم مفردة صارمة للنوع والترتيب
والحد والمؤشر. يعيد version وقدرة اختيارية، company/room/membership IDs، عناصر
message canonical التي تملك media، وnext_cursor. ترتيب الأحدث/الأقدم بـmessage.id،
والأكبر بزوج (size_bytes,message.id). المؤشر محدود ومقيد بنطاق الغرفة/العضوية
والفلتر والترتيب؛ تغييره لا يغيّر شرط الرؤية المفروض من الخادم. سقف128KiB.

قبل أي metadata أو bytes: internal active + chat_view + media + non-sudo caller،
شركة مخولة، عضوية حالية، حد joined_after، وتطابق message↔media↔room/company وحالة attached.
إعادة استخدام serializer وcontent/thumbnail routes وموصل الأصل الحالي، لا direct attachment URLs.
لا تغيير لشكل history أو لمس إيصالات القراءة أو ACL الخاصة أو source hold.
فهرس جزئي محدد للرسائل المرتبطة بوسائط عند الحاجة؛ لا جدول محتوى موازٍ.

ChatEngine يحفظ associations متناثرة محدودة منفصلة عن coverage مع كل فحوص الجلسة
والعضوية والحقبة. انقطاع الشبكة لا يحوّل قائمة جزئية إلى معرض كامل؛ لا توسيع24h lease.
الأرقام الخادمية تأتي من أودو. أرقام مساحة الجهاز تأتي من خدمة runtime والفهرس/الملفات
المملوكة بوصفها سلطة التخزين المحلي، لا من جمع داخل شاشة UI أو مساحة قرص مزعومة.
البايتات أعداد صحيحة، وعقد تنسيق مركزي بحد منزلتين وأرقام0–9 في اللغتين.

حالة الكاش والسياسة وpins داخل كتالوج المالك الحالي، وترقية SQLite إضافية متوافقة.
خطة التنظيف لقطة مرتبطة بالهوية والحقبة، وليست تفويض حذف مسارات UI عشوائية؛ إعادة
الفحص داخل serialMedia ملزمة، مع حصر exact owned media-* ورفض stage/part والروابط غير المؤكدة.
سحب الصلاحية/الخروج يعلو pin؛ لا إعادة استخدام سياسة/ملف حساب بديل أثناء await.
التراجع عن النسخة الجديدة لا يحذف أصولًا؛ كاش منظف يُعاد جلبه فقط عند صلاحية وتنزيل ناجحين.

## G3 / G4 — التقنية والواجهة (قيد المراجعة)

المسار الأصح والأقصر: native components.tsx/Sheet/Button/Icon/dictionary + existing
image/file/voice viewers وSQLite/ExpoFS، وOwl/fetch الأصليان داخل أودو. لا حزمة جديدة
أو مكتبة ويب مفروضة على RN، ولا استبدال رصة أو إنشاء خدمة أو تخزين خارجي.
المراجع المطبقة: alpha-build/architecture/scale/design-catalog، وإرشادات Emil وux-araby.
الحركة ليست غاية؛ لا تأخير متكرر أو hover-only أو scroll أفقي. اللوائح محدودة/كسولة.

معرض RN من المحادثة، وإعدادات التخزين من الإعدادات؛ مكونات خاصة صغيرة دون نسخ الهيكل.
Owl action صغير تحت قائمة بيورك الحالية، rooms من API المستخدم لا admin.rooms().
اختيار/تبديل الغرفة أو الفلتر أو الخروج يلغي الاستجابة السابقة وObjectURLs/عرض الوسائط.
النص يميز «تنظيف من الجهاز» من «حذف من المحادثة»، ولا يخلط دعم الاحتفاظ مع إذن العرض.

الفحوص: عقود gallery وORM/HTTP معزولة (سلب الشركات/العضوية/السحب/إعادة الانضمام،
الترقيم والفرز والروابط والحدود)؛ tests actual cache runtime/SQLite/pins/races؛
ChatEngine association/coverage؛ UI dictionaries/actions/accessibility؛ TypeScript؛
البوابة التراكمية الحالية دون حذف ثوابتها؛ ومعاينة أصلية AR/EN320+desktop/خط130%.
لا إعادة بناء APK عادي أو فحص حمل خادم لتغيير غير متعلق؛ CI الجديد مرة لكل رأس متغير.

## سجل البوابات

| البوابة | الحالة | المراجع | الدليل |
|---|---|---|---|
| G0 | معتمدة | حارس مستقل | عقد BMS والخريطة القائمة؛ قرار المراجع 005 أدناه |
| G1 | معتمدة | حارس مستقل/سعة | الحدود المعلنة والدفعات؛ القرار 005 دون شهادة حمل |
| G2 | معتمدة | حارس مستقل/سلطة وERP | العقد مع الضمانات الملزمة 005؛ لا أصل خادم ضمن التنظيف |
| G3 | معتمدة | حارس مستقل/معماري | إعادة استخدام الرصة بلا تبعيات؛ القرار 005 |
| G4 | معتمدة | حارس مستقل/تجربة | الكتالوج واللغتان وحالات التأكيد والفشل؛ القرار 005 |
| G5–G8 | غير مبدوءة | — | لا كود قبل قرار G0–G3 |

## دفتر العمليات (إضافة فقط)

### تفويض إصدار لاحق — 2026-10-20

بعد اكتمال تنفيذ المرشح، طلب المالك صراحة «ادمج وانشر». يوسّع ذلك التفويض إلى
دمج PR435 بعد فحوص الرأس، وتحديث QA عبر سياسته المحمية، وبناء ونشر APK عادي
0.1.30/build31 في صفحة التحميل. لا يجيز ذلك Live أو منح أدوار أو حذف أصل خادم.
إعادة استخدام قبول aaf77426 المحلي المشروط ودليله؛ فرق المرشح التالي metadata
الإصدار والتوثيق فقط، دون إعادة فحوص ناجحة غير متأثرة أو توزيع حزمة uipreview.
تُراجع مستقلًا سلسلة source S → policy M → QA request Q → actual host receipt →
normal APK/tree/hash/signature/upgrade ثم draft/publish/public-download verification.
الموديولان فقط baseer_bchat وbaseer_bwork_admin؛ لا تثبيت تبعيات جديدة أو تغيير أدوار.
يبقى P2 الأداء/الإتاحة وحدود native EN negatives معلنًا، ولا قبول مالي/FCM شاملًا.
السجل الحي للإصدار: output/bwork-media-storage-20261020/release-0.1.30/release-progress.json.

1. قبل الاستكشاف: نية إعادة استخدام الخريطة والحدود الحالية؛ agent mobile للكاش فقط،
   agent backend لمسار المعرض/أودو فقط؛ لا تنفيذ حتى مراجعة البوابات.
2. نتيجة القراءات المتجانسة: skill build ومراجع governance/scale/architecture/design/ERP،
   package/components/MediaTools/nativeArchive/HistoryArchive/رسالة/registry/release evidence؛
   لا قائمة gallery قائمة، وmediaPins الحالية leases عابرة لا احتفاظ دائم. لا اختبارات مكررة.
3. الفرع المستقل أنشئ من00cc؛ tracked clean قبل الوثائق، output السابقة محفوظة.
4. هذا العقد مسودة للمراجعة المستقلة؛ لا ادعاء تنفيذ أو اختبار أو نشر جديد.

### دليل تنفيذ موجه — 2026-10-20

- فحص TypeScript والبوابة التراكمية الفعلية: PASS،187سلوكًا محميًا،24.58ثانية.
  suites: gate5،odoo365(364PASS/1benchmarkاختياريSKIP كما هو؛0FAIL)،brand5،orders99،
  tasks52،leadership61،camera4،notifications19،media-ui4. لا تغيير أو تخفيف للثوابت178السابقة.
- عقود backend156:155نجح وفشل واحد كشف نقلJS إلىadmin؛ عولج بنقل قارئ المحتوى
  إلىstatic/src/bwork_gallery فيBChat، لا تعديل لحارسnativeadmin. أعيد فقط المتأثر:
  admin12PASS/gallerypure7PASS/Owlclient7PASS. isolatedORM/HTTP9 ما زالPENDING.
- ChatEnginegallery10PASS بما فيها sparse≠coverage/no receipts،offlineTTL،رفض403
  ومسحretained،hidden-own عبرhot/sparse/archive،ورجوعhideالأحدثبعدانتظارarchive.
  UIactualcomponents4PASS،actualSessionApp29PASS؛ لا يُعد ذلك إثبات بكسلات الجهاز.
- schema2 وretained additive،ميزانية8MiB تشملenvelopemetadataكما أقر006؛
  cleanup OFF أوليًا. nativeFS/SQLitesandbox/صورAR-EN/CI والمراجعةالنهائيةPENDING.
- لا merge/QA/APK/Live ضمنهذهالدورة. فرعالمراجعةcodex/bwork-media-storage-20261020؛
  يُرفع فقط لتشغيلأودوالمعزول وحفظالمصدر، لا تشغيلمسارالنشر.

## 005 — قرار حارس البوابات المستقل قبل التنفيذ

2026-10-20: قُرئ عقد BMS كاملًا وأُعيد استخدام خريطة BWA/BIL/BSC/BSP؛
قُرئت تعليمات build/governance/scale/ERP/design-catalog. لا إعادة استكشاف
للخلفية أو فحوص ناجحة أو حذف ملفات. القائد اعتمد صراحة الضمانات الآتية
كتصميم ملزم قبل التطبيق. GO لاعتماد G0–G4 فقط؛ G5–G8 لا تزال غير معتمدة.

### حدود السلامة الملزمة للتنفيذ

1. last-use المجهول أو 0 أو غير الصالح/المستقبلي محفوظ، وكذلك عند رجوع
   الساعة؛ لا يُنشأ عمر كاذب لملف قديم عبر تخمين تاريخ الاستعمال. شرط30 يومًا
   لا يكفي وحده للحذف. إذا تعذرت قراءة ملكية الكاش أو outbox/journal أو pins
   أو حالة نقل/عرض جارٍ، تفشل أهلية الحذف مغلقة. تُحفظ السياسة معطلة افتراضيًا.
2. خطة المعاينة محدودة5000مرشح/دفعات100 وصلاحيتها5دقائق؛ مقيدة بالهوية
   والخادم والحقبة وارتباط canonical الحالي. لا مسارات من UI ولا إضافة
   ضحايا بعد التأكيد. يعاد فحص root/association/hash/usedAt والملف الفعلي
   وكل pin/lease/transfer/outbox تحت قفل المالك قبل حذف كل مرشح؛ أي تغير
   يلغي أو يتجاوز المرشح بدل تطبيق لقطة قديمة. لا حذف staging/part مطلقًا.
3. pin دائم يحمي من التنظيف اليدوي/التلقائي وLRU/إخلاء quota، لكنه لا يزيد
   حدود128MiB/5000ملف ولا يحول intent إلى bytes متاحة offline. لا تعرض حالة
   «متاح دون اتصال» قبل تحقق الملف والحجم والـSHA. فشل حفظ pin لا يعرض نجاحه؛
   لا يتجاوز pin سلطة القراءة أو logout/revocation/مهلة الحساب، ولا يستدعي
   حذف نسخة محمية لتلبية تنزيل جديد. نفاد غير المحمي يعيد media_quota.
4. حذف الملف وفهرس SQLite ليسا معاملة ذرية واحدة: النتيجة تفصل deleted/
   skipped/failed والبايتات المحررة المثبتة عن التقدير، وتصرح partial عند
   فشل جزئي/إلغاء/تبدل هوية. لا rollback مزعوم للبايتات ولا إعادة جلب خفية
   لاسترجاعها. يحدد التنفيذ reconciliation/resume آمنًا بعد الانقطاع أو
   فشل تحديث الفهرس، دون إعادة استعمال خطة منتهية أو حساب آخر.
5. المعرض يستعمل canonical message items من الخادم ويطبق أيضًا إخفاء
   الرسائل الخاص بالمستخدم؛ لا يعيد إظهار hidden-own أو محتوى غير مخول
   بسبب كون القائمة متناثرة. الانتقال لرسالة يمر بمسارها المخول المعتاد؛
   مشاهدة المعرض وحدها لا تحدث read receipts أو coverage.
6. next_cursor نص أقصاه256، مقيد room/member/filter/order وبترتيب ثابت عند
   ties. عند سقف128KiB يتبع آخر عنصر أُعيد فعليًا، لا آخر عنصر مسحته الخدمة؛
   لا إسقاط tail أو false-end/صفحة فارغة توقف التصفح مع وجود عناصر. الحد60
   لا يبرر تحميل تاريخ كامل أو metadata خارج scope.

### عقد G4 والتوثيق للمستخدم

مركز RN القائم هو mobile/chatwoot/src/odoo/ui/components.tsx مع dictionary.ts؛
فتح الوسائط يعيد استعمال MediaTools.tsx وviewers القائمة. لا نسخة محلية من
Sheet/Button/Icon/تأكيد/تنسيق عام، ولا مكتبة جديدة. أودو يستعمل Owl/action
القائمين. تنسيقات العدد/الحجم يصدرها مالك الخدمة لا تجمعها الشاشة؛ عربية
وإنجليزية وأرقام0–9. التأكيد يذكر تنظيف نسخة الجهاز لا الأصل، ويعرض العدد
والحجم المقدر وحماية offline وفقد الإتاحة بعد تنظيف غير المحمي؛ نتيجة جزئية
تُعرض بصدق. يبقى اختلاف pin intent/availability/authority واضحًا ومتاحًا.

### شروط منع الانتقال عند G5/G6

قبل قبول الشريحة/السعة، يلزم اختبار إنتاجي المسار للـgallery والسلطات
والـhidden-own والترقيم/byte-bound؛ وChatEngine sparse≠coverage/no receipts.
للتنظيف يلزم دليل sandbox أصلي معزول من FS وSQLite الحقيقيين، لا صور synthetic
قديمة وحدها، يثبت: unknown/0/clock rollback محفوظ؛ pin وoutbox غير المقروءين
يفشلان مغلقين؛ preview→تغير pin/use/association/actor لا يحذف؛ original/stage/
part/leased/inflight محفوظة؛ quota تشمل المحمي؛ فشل unlink أو catalog/restart
يعطي partial/reconciliation صحيحة؛ لا مساس ببيانات التطبيق العادي أو ERP.
دليل5000عنصر/دفعات100 وتزامن5عمليات يكون محدودًا ومعزولًا مع قياس معلن لا
شهادة ضغط مطلقة. فحوص AR/EN320/desktop/font130 وcancel/stale responses وتحرير
ObjectURLs مطلوبة للشريحة؛ لا إعادة بناء APK عادي أو نشر QA/Live ضمن هذا الطلب.

أي تغيير لهذه الحدود يعيد البوابة المتأثرة للمراجعة؛ هذا اعتماد تصميم لا
إثبات تنفيذ، ولا إذن حذف حقيقي في جهاز المالك أو عمليات تشغيل خارجية.

## 006 — إضافة G2: ارتباط محفوظ لملف offline دون توسيع التاريخ

سبب إعادة المراجعة: gallery associations في الذاكرة لا تكفي لفتح pin بعد
إعادة تشغيل التطبيق. الإضافة المقترحة من القائد هي سجل retained_media في
SQLite الحالي، لا history commit ولا مصدر سلطة مستقل. GO تصميم G2 لهذه
الإضافة فقط بالشروط الملزمة الآتية؛ بقية البوابات/حظر النشر لا يتغيران.

- واجهة HistoryArchive.retainMediaAssociation اختيارية للتوافق؛ الواجهة العامة
  في ChatEngine تقبل room/media ID وkeep فقط، وتستخرج Message canonical داخليًا
  بعد التحقق من النطاق والصلاحيات؛ لا يقبل runtime/الشاشة Message أو مسارًا
  لإنشاء ارتباط. غياب دعم persistence يفشل keep صراحة، لا no-op ناجحًا.
- جدول منفصل بحد إجمالي5000row/8MiB للـaccount يشمل JSON/metadata، لا يكتب
  archive_scopes أو coverage أو latest/window. لا LRU يحذف ارتباط pinned، ولا
  يزيل ارتباط تاريخ عادي عند unpin؛ عند السعة يرفض keep بدل نجاح زائف.
- findMedia fallback يعيد نسخة دفاعية بعد نفس current account/company/room/
  membership/media+chat_view وepoch/TTL guards، قبل وبعد كل await والمعاملة؛
  لا يجدد lease أو يعيد اشتقاق سلطة من وجود metadata. الفلتر hidden-own يطبق
  قبل أي إعادة association من hot/sparse/archive/retained لا الفرع الجديد وحده.
- reconciliation/purge تسقط retained rows عند logout أو منع media أو تغيير
  الشركات/العضوية، وتحترم رفض fresh authority؛ لا reuse تحت عضوية جديدة.
  صف قديم لا يعيد ملفًا أو association من حساب آخر بعد استئناف await.
- ترتيب keep: يثبت canonical association قبل إعلان pin دائم، والاستدعاء خارج
  serialMedia/قفلFS. لا lock inversion بين engine/archive وFS/catalog. فشل حفظ
  الارتباط أو pin لا يعرض retained/available نجاحًا؛ orphan metadata الناتجة
  عن فشل لاحق تبقى محدودة ويمكن reconcile بلا حذف أصل أو outbox. unpin يرفع
  حماية bytes وينظف retained metadata الخاصة به، مع نتيجة صادقة عند الفشل.

شرط G5 الإضافي: actual production archive SQLite restart يجد association
والملف المحقق دون coverage/HTTP جديد؛ hidden-own/expired lease/rejoined member/
wrong actor/company/revoked media لا يفتح، وفشل persistence/capacity لا يدعي
keep. لا يكفي mock MemoryHistoryArchive لادعاء تحمل إعادة تشغيل القرص.

المراجعة المبكرة لملفات backend gallery_service/gallery_contracts/gallery_api
واختباراتها الستة لم تكشف P0/P1 مصدرية: الحراس قبل SQL، inverse link والحالة
والشركة وjoined_after، query/cursor مقيدان، والمؤشر بعد byte trim يتبع آخر
emitted. هذا ليس قبول G5: ORM/HTTP والفرز/ties والسحب وإعادة الانضمام ونفي
إيصالات القراءة/coverage تظل فحوصًا إلزامية قبل قبول الشريحة.

## 007 — مراجعة مصدرية مستقلة مرحلية، لا قبول شريحة

قُرئت RN gallery/storage وSessionApp/Timeline وChatEngine/Memory/retained
والـbackend/Owl الحالي قراءة محددة، دون إعادة الفحوص. أصلح منفذ Owl مانع
استدعاء callbacks محتجزة بعد dispose: guards قبل fetch لا بعده فقط، ومسح
metadata/ObjectURL؛ رُوجع المصدر واختبار Node الجديد، وأُغلق المانع مصدرّيًا.

موانع الرحلة RN عند هذه المراجعة أُرسلت للقائد للإغلاق قبل G5:
- مدخل gallery لا يكون حصريًا عبر إدارة أعضاء المجموعة، لأن المحادثة الفردية
  المخولة لها المرفقات نفسها؛ لا يشترط group/admin لمدخل مستخدم مخول.
- رجوع Android يغلق gallery/storage أولًا، ولا يغير المحادثة تحت overlay.
- اكتمال jump المحتجز من معرض قديم لا يغلق معرضًا جديدًا أو يضع focus في
  محادثة أخرى للحساب نفسه؛ يلزم instance/room/navigation guard قبل وبعد await،
  واختبار close/reopen/switch. account mediaScope وحده لا يميز هذه الحالات.

تنبيه تحقق موجه: snapshot hiddenIds قبل انتظار archive قد يصبح قديمًا عند
تقدم setMessageHidden في queue؛ طلب المراجع اختبار الترتيب المحتجز قبل اعتباره
فشلًا مثبتًا. لا يعاد عرضه كاختبار منفذ. تظل G5/G6 غير معتمدتين؛ سلامة المصدر
جزئية وليست قبولًا للـFS/SQLite أو واجهة أصلية أو صلاحيات خادم منفذة بعد.

## 008 — إغلاق المراجعة المصدرية المحددة واستمرار شروط الإثبات

رُوجعت إصلاحات 007: مدخل Timeline مباشر للمحادثات الفردية والمجموعات، Back
يغلق النوافذ أولًا، إبطال gallery instance قبل await وتقييد الاكتمال بالاختيار
والمنطقة والعضوية، وfocus scoped؛ وحالة keep تستعمل serial وfresh refetch فلا
تطغى قراءة قديمة عليها. رُوجعت الاختبارات الفعلية المضافة للـSessionApp
والـmedia components دون إعادة تنفيذها؛ الموانع المذكورة أُغلقت مصدرّيًا.
فحص hidden association أصبح من hiddenIds الحالية بعد انتظار archive، وصُحح
namespace اختبار archive إلى prefix لا accountScope/epoch. اختبار ترتيب hide
المحتجز ما زال القائد يضيفه وقت هذا المدخل.

مسار CI الجديد gallery يفعّل فقط فحص repository --changed/--all ويحتفظ
بحارس default QA السابق؛ يثبت صور Odoo/Postgres، contents:read، timeout،
no-skip/no-failure و9 حالات ORM/HTTP مطلوبة. لا إضعاف للمتطلبات القديمة أو
صلاحيات جديدة؛ لا تُنسب مؤلفات الاختبار إلى تشغيل CI ناجح قبل وروده.

الفجوة المفتوحة المحددة: retained SQLite يعد SUM(bytes) لرسالة JSON فقط،
بينما 006 يشترط8MiB شاملاً metadata المنفصلة. يلزم احتساب logical account/
scope/IDs كذلك أو إعادة توضيح G2 واعتماد الحد المضاف صراحة؛ لا ادعاء حجم
SQLite الفيزيائي. تظل G5/G6 غير معتمدتين حتى إغلاق ذلك ودليل FS/SQLite
الأصلي والقياس المحدود والمعاينة وCI ذي الرأس المثبت. لا نشر أو قبول إطلاق.

## 009 — تعديل توجيه G2/G3 لحفظ عقد الإدارة الأصلي

كشف فحص backend الحالي فشلًا حقيقيًا في invariant سابق: الإدارة native-only
تمنع أي ملف JS داخل baseer_bwork_admin. لا يعتمد المراجع إضعاف هذا الحارس
أو استثناء معرض جديد منه. اعتمد اقتراح القائد بنقل gallery_client.js و
media_gallery.js واختبار المصدر الخاص بهما إلى وحدة المحتوى baseer_bchat؛
إضافة feature-local تحت static/src/bwork_gallery للمنتج، مع اختبار Node خارج
حزمة production. تبقى action/menu وXML/SCSS فيadmin إن لزم، وmanifestadmin
يشير لأصول اعتماده القائم baseer_bchat دون إضافة addon أو dependency.

GO لإعادة اعتماد G2/G3 بهذا النقل التنظيمي فقط: invariants الإدارة القديمة
تبقى حرفيًا، وقراءة المحتوى لا تستعمل admin service أو source ORM/ACL.
يُحدّث الربط الصريح للأصول وrelative import وCI وregistry ومسار اختبار Node،
ولا يدخل ملف اختبار أو mock إلى bundle. إعادة فحص العقد الذي فشل والـNode
المتأثر مطلوبة بسبب النقل؛ لا يعاد full mobile gate أو بناء غير متعلق.
المراجعة التالية تربط المسارات الجديدة بالدليل، ولا يقفل G5/G6 بهذا القرار.

## 010 — إغلاق فجوة الميزانية ومراجعة مسار الأقفال

رُوجع إصلاح retainedBytes: حجم UTF-8 للـenvelope الكامل account/scope/media_id/
message_id/message يدخل budget المخزن؛ لا ادعاء صفحات SQLite فعلية. أُغلقت
فجوة 008 مصدرّيًا مع بقاء إثبات القرص. ورُبط نقل009 بالـmanifest وCI: ملفات
المعرض في baseer_bchat/static/src/bwork_gallery، اختبار Node في static/tests،
ولا تعديل لحارس منعJS فيadmin أو إدراج test ضمن production assets.

فحص سؤال lock inversion المحدد لم يثبت دورة في hooks الحالية: cleanup/keep
قد ينتظر engine من serialMedia، لكن removeStoredAttachments يستعمل hook
removeOwned مباشرة (FS/catalog فقط)، وNative logout/refresh/login ينتظرsuper
قبل pruneMedia(serialMedia). لا edge من engine.serial إلى serialMedia في
هذا المسار؛ لا تغيير زائد أو اختبار deadlock جديد بلا سبب. لف removeAttachment
مستقبلًا داخل serialMedia يستلزم إعادة المراجعة قبل اعتماده.

البوابة التراكمية187 وثقها القائد ناجحة؛ لا يعيدها المراجع. دليل sandbox
FS/SQLite والقياس ومعاينة AR/EN وORM/HTTP9 لم تكتمل بعد وقت هذا السجل؛ لذلك
لا إقفال G5/G6 ولا قبول نشر، مع عدم وجود مانع مصدرّي جديد مثبت في الفرق المراجع.
