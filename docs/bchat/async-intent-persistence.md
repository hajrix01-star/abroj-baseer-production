# C07: حفظ النوايا الحساسة خارج خيط الواجهة

الحالة: عقد التنفيذ المالي معتمد من حارس البوابات G2، ونُفذت شريحته في المصدر مع فحوص سلوكية محلية؛ ليس قبول شاشات أو إطلاقًا. يعيد استخدام G2-C02/C07/C08 و`BChatStorageRepository`، بلا schema أو API أو مكتبة جديدة. الملكية: `OdooIdentityActivity` ومستودع sync/اختباراته فقط.

## المواقع التنفيذية

كل المواقع في `android/bchat/app/src/main/java/com/baseer/freshchat/OdooIdentityActivity.java`؛ أسماء الدوال مرجع ثابت لأن أرقام الأسطر تتحرك مع الدمج.

| المجال | مواقع commit على UI التي ستُنقل | حد الأثر المحفوظ |
|---|---|---|
| group | `chooseGroupCompany`، `submitGroupCreate` (admission/ACK/rejection/discard) | نفس JSON وclient_uuid؛ لا إنشاء مجموعة قبل نجاح الحفظ |
| live | `requestFeed` و`snapshotChanges` عند نهاية snapshot | لا تقدم feedCursor أو watermark ولا جدولة صفحة تالية قبل نجاح commit |
| task | `submitTask`، `sendPendingTaskCreate`، `confirmDiscardPendingTask` | نفس UUID والعنوان/الوصف/الموعد/المكلف؛ لا ضياع النموذج عند فشل الحفظ |
| orderPermission | `applyOrderRights` | نفس سياسة view/create/receive؛ المنع في الذاكرة فوري، وفشل الحفظ يعطّل offline |
| receiptShare | `shareConfirmedReceipt` وmarker الناتج من تأكيد الاستلام | marker account+order+company فقط؛ لا مشاركة جديدة تلقائية |
| receiptConfirm | `confirmReceiptReview`، `sendPendingReceipt`، `discardPendingReceipt` | نفس UUID وقيم الإدخال الخام؛ استبدال rejected فقط بمطابقة السجل المتوقع |
| orderCreate | `submitOrder`، `sendPendingOrder`، `confirmDiscardPendingOrder` | نفس UUID وpayload وخيارات route/warehouse/representative/room |

## عقد الحفظ والإرسال

1. خيط الواجهة يتحقق من السياق الحالي، يلتقط account/session/view/editor identity ونسخة raw نهائية، وينشئ UUID مرة واحدة فقط. لا حساب مالي أو تقريب أو إعادة تشكيل payload في العامل.
2. عملية admission تمر في serial storage lane نفسه. تقارن القيمة المتوقعة بالسجل الحالي داخل العامل؛ السجل المختلف لا يُستبدل أو يُحذف. عمليات permission purge تستخدم المسار المتسلسل نفسه وstorage generation fence القائم.
3. `SharedPreferences.Editor.commit()` الحقيقي يُنفذ على العامل وتُفحص نتيجته. لا `apply()` بديلًا عن write-ahead durability، ولا wait/join أو fsync على UI.
4. فشل commit قد يغيّر **نسخة SharedPreferences في الذاكرة** رغم فشل القرص. لذلك وجود raw في الذاكرة ليس تصريح إرسال: **كل dispatch/retry** يعيد إثبات commit لنفس raw/UUID قبل HTTP، بما فيها محاولة تُطلق من شاشة مراجعة pending. لا إرسال عند false/exception.
5. admission busy مستقل عن v2Busy؛ يمنع نقرات إنشاء متكررة حتى انتهاء الحفظ. إذا انشغل HTTP بعد نجاح الحفظ، يبقى pending محفوظًا للمراجعة/المحاولة بنفس UUID؛ لا إنشاء UUID بديل ولا auto-send بعد تغير السياق.
6. تُعاد صلاحيات الشركة/العضوية اللازمة في callback قبل HTTP. purge/revocation generation أو account/session mismatch يمنع dispatch ويمنع callback من إعادة عنصر مسحوب للواجهة.
7. عند نجاح admission لا يغلق أو يمسح النموذج/السلة إلا callback يطابق الحساب والرحلة والنموذج/revision/fingerprint الملتقط. الفشل يبقي قيم المستخدم ويعيد تمكين الإجراء مع رسالة حفظ مفهومة.

## ACK والتراجع والتزامن

- تحقق ACK الحالي يبقى كما هو، لكن يقارن هويات المنشئ بالحساب **الملتقط للطلب** لا بحساب ربما تغيّر أثناء HTTP.
- retire/discard/rejection-cleanup تقارن exact old raw/UUID مرة أخرى داخل العامل قبل remove+commit. رد قديم لا يمسح سجلًا أحدث. إذا فشل remove تبقى الحالة غير مؤكدة ولا يُعلن اكتمال تنظيف محلي.
- حفظ receipt-share marker ثم إزالة receipt-confirm ليس معاملة بين ملفي تفضيلات؛ لا ادعاء atomicity. الترتيب المعتمد يبقى marker commit ناجح أولًا ثم إزالة exact confirmation. إذا انقطع التنفيذ بينهما يبقى UUID الأصلي قابلًا لـidempotent replay، ولا تضيع علامة المشاركة. لا مشاركة HTTP تلقائية من هذا التسلسل.
- UI acknowledgements مقيدة account+session+view؛ العمل الدائم المقبول سابقًا قد يكمل تسويته لنفس الحساب بعد تبديل شاشة، لكن callbacks القديمة لا تغلق محررًا أحدث ولا تعيد إظهار محتوى بعد purge.
- timeouts و0/5xx لا تحذف نية. حالات الرفض المحددة الحالية وحدها تحتفظ بقرارها القائم، وبنفس حدود الغرفة/الشركة. لا تغيير سياسة رفض مالية ضمن نقل الخيط.
- live hints قد تُنفذ قبل حفظ cursor كما في المسار القائم؛ فشل commit يعيد القراءة وقد يكرر hint idempotent. لا يقدم cursor في الذاكرة أو يشغل snapshot منافسًا بينما حفظ watermark معلق. تُحرس callback بجيل live/session، والقيمة لا تتراجع بسبب callback قديم.
- التراجع كود فقط قبل النشر؛ ملفات التفضيلات وkeys وraw formats لا تتغير. لا حذف بيانات أو تحويل مالي أو ترحيل تخزين في هذه الشريحة.

## الإثبات المطلوب قبل قبول الشريحة

- اختبارات admission ناجح/فاشل/exception، بما فيها fake صريح يقلد commit=false مع تغير الذاكرة: لا HTTP قبل durable=true، retry يعيد commit، UUID/payload مطابقان.
- exact compare-and-remove: ACK قديم أمام raw أحدث، account/session/view switch، purge أثناء worker؛ لا حذف أو dispatch أو إعادة عرض خاطئة.
- receipt marker-first failure/restart وUUID replay، task form failure preservation، order cart revision/fingerprint، group double-tap، live cursor monotonic/generation.
- اختبارات التنفيذ الحقيقي المحلي المناسبة وcompile؛ source guards تُحدّث لتثبت persist-before-HTTP غير المتزامن بدل شكل synchronous قديم. لا تجاوز حارس تراكمي.
- StrictMode/trace للرحلات المتأثرة في قبول Activity المعزول لاحقًا؛ الاختبارات ذات UI/transport fakes لا تثبت سلاسة الشاشة أو process death. لا ادعاء اكتمال C07 قبل نقل ما بقي من IO الوسائط في C09 وفحص الرحلات المؤلفة.
