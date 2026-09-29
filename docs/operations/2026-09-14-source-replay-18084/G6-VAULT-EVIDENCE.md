# G6 — دليل موجة المحافظ

تاريخ الفحص: 2026-09-14. النطاق `baseer_integrated_release_rehearsal_20260914`
على 18084 فقط. البيانات الرئيسية السابقة موجودة؛ لم يُكتب أي مستند مالي في
هذه الموجة.

| الدليل | النتيجة |
| --- | --- |
| لقطة المصدر | `vault-source-snapshot.json`، SHA-256 `11538ed7a7f72f9e1e2dfbfb635cfcc91f5296e357284de0d7a7beea2a510a58`؛ 14 صفًا خامًا من أرشيف نوركس مع source-row SHA لكل صف |
| تسلسل المصدر | أرشيف `024606…E79E2`، manifest `84af…1fa6`، وعقد قرار السيولة 26 `fffd6b…ffa127` |
| إيصال addon runtime | 7 ملفات، SHA-256 `05e281374460bb023a4df5124d5f7db66de06cec9343ec5de25d6c206fd19109`؛ `replay_writer.py` `d274388b…` |
| مفتاح المطابقة | source company map ثم `(account.journal.company_id, code, type)` فقط؛ لا مطابقة بالاسم ولا استعمال `PSBNK` أو`PSCSH` |
| إعادة الاستخدام | 9 يوميات سيولة موجودة أعطت تطابقًا نشطًا وحيدًا بالضبط |
| الإنشاء | 5 محافظ تاريخية: `KEET` و`HNGR` للمعلم، `SIFI` و`PERS` و`ABJL` لـARZ؛ ينشئ Odoo لكل واحدة journal وحساب سيولة تابعًا لها |
| probe الذري | داخل savepoint: +5 journals و+5 accounts و14 mapping وrun واحد، ثم rollback أعاد 75 journal و935 account و0 vault mapping |
| منع الأثر المالي | بقيت `account.move=2` و`account.payment=1` وstock moves/pickings=0 قبل/أثناء/بعد الاختبار |
| idempotency | الاستدعاء الثاني أعاد النتيجة نفسها دون إنشاء جديد |

لا يكتب الكاتب سوى `account.journal` وإثبات provenance. لا ينشئ payment
method أو statement أو move أو invoice أو stock record. يلزم قرار مراجعة
مستقلة قبل `commit` فعلي للمحافظ.

## التنفيذ الفعلي والتسوية

منح المراجع المستقل GO، ثم نُفذ `vault_company` في transaction واحدة على
18084. النتيجة الملتزمة: 14 خريطة vault provenance وrun واحد `committed`؛
9 إعادة ربط و5 يوميات/حسابات سيولة تاريخية جديدة. ارتفع عدد اليوميات من
75 إلى 80 والحسابات من 935 إلى 940 فقط؛ بقيت الحركات=2 والدفعات=1
وstock moves/pickings=0.

إعادة التشغيل اللاحقة كانت idempotent ولم تغيّر أي عدد. لا تزال `PSBNK`
و`PSCSH` خارج هذه الموجة كليًا.
