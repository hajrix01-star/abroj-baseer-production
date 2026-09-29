# G5 — دليل حارس المصدر وpreflight

تاريخ الفحص: 2026-09-14. النطاق هو قاعدة التدريب `baseer_integrated_release_rehearsal_20260914` فقط؛ لم تُكتب بيانات أعمال.

| الدليل | النتيجة |
| --- | --- |
| إضافة runtime | `baseer_noorix_rehearsal_replay`، حالة `installed`، نسخة `19.0.1.0.0` |
| بصمة شجرة الإضافة | 7 ملفات، SHA-256 `c3a8e2442f05d4f6a7ff8b9c75cc662c6c27c04e0f5b2279aa42ac7f1fcb8717` |
| المصدر/العقد | archive `024606…E79E2` وmanifest `84af…1fa6` اجتازا الحارس |
| الحارس | يقبل اسم قاعدة 18084 فقط ويرفض `baseer_dev` وQA وأي اسم آخر |
| mount | `/mnt/rehearsal-addons` و`/mnt/noorix-source` للقراءة فقط، وخارج candidate-v14 |
| خط أساس الأعمال النشط قبل/بعد preflight | 3 شركات، 77 جهة، 37 منتجًا، حركتا حسابات، دفعة واحدة، 0 stock moves، 0 pickings |
| جدول provenance | جدولا `baseer_noorix_rehearsal_run` و`baseer_noorix_rehearsal_source_map` موجودان وبهما 0 سجل |
| read-only plan | 5 شركات قانونية من 6 هويات مصدرية، 284 موردًا إنشاء و2 reuse VAT، 467 منتجًا إنشاء؛ `orm_writes=0` |
| فحص الواجهة | `GET /web/login` على 18084 = HTTP 200 |

النتيجة: G5 يثبت العزل والحارس والقراءة فقط. لا يثبت كاتب البيانات الرئيسية أو أي قيد/فاتورة؛ تلك تبدأ في G6 بعد اختبارات السلبية والضريبة والمطابقة والذرية المطلوبة.
