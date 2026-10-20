# BRT-20261020 — احتفاظ بيورك وإدارة التخزين

## عقد البناء والحدود

طلب المالك تنفيذ اقتراح الحذف التلقائي واليدوي مع تطوير شاشة أودو التي ناقشناها.
الأساس07f5f802 (منتجfa9d51c2، QA/APK0.1.30)، الفرعcodex/bwork-retention-console-20261020.
ARCHITECTURAL: استثناء احتفاظ خادم محروس؛ لا تحويل حذف الموظف لرسائل الآخرين إلى صلاحية عامة.
التفويض تنفيذ وفحص مرشح فقط، لا نشر أو تفعيل سياسة أو حذف بيانات المالك/QA/Live.

النطاق:
- اسم عرض ثابت «إدارة بيورك» بدلNewId، وهيدر/كروت موجزة ومتجاوبة بلا أدوات إنشاء غير لازمة.
- لوحة تخزين تعرض قيم الخادم حسب الشركة/الغرفة/النوع، واستعراض الأكبر عبر المعرض المحروس.
- سياسة لكل شركة: OFF افتراضيًا، مدة أيام، وقت يومي صحيح ومنطقة زمنية IANA، ونطاق غرف اختياري.
- يدوي: ما قبل تاريخ (بداية ذلك اليوم محليًا، حد حصري) أو أقدم منNأيام؛ شركة/غرف محددة.
- نمطان: المرفقات فقط أو محتوى الرسائل ومرفقاتها؛ بقاء الغرف والعضويات ومعرفات منع إعادة الإرسال.
- معاينة خادمية العدد/الحجم/المستثنى ثم تأكيد صريح؛ سجل عمليات وصلاحية مستقلة لا تُمنح تلقائيًا.
- حفظ صريح يمنع الاحتفاظ الخادمي؛ لا يساويهpinكاش الجوال. ملفات/روابطERP/DMS والعمليات الجارية محمية.

الخريطة المعاد استخدامهاBMS/BWA:
`Odoo owner/current companies -> retention policy or manual scope -> immutable preview -> confirm -> bounded executor -> content erasure + audit`
`canonical retention state -> history/gallery/media/push guards -> BWork sync -> cached content invalidation`
`storage metadata service -> native Odoo controls/KPI/filters -> existing own-member media gallery`

## G1 — السعة والاستمرارية (مسودة)

المعلوم: لقطة4غرف/5عضويات/13.70MiB؛ سؤالصورتين يوميًا لا يثبت أنه لكل موظف أو للنظام كله.
افتراض تصميم محافظ: حتى100000صف مصدر لكل معاينة إحصائية، صفحة30/60، ضحايا خطة محدودة لا مسح غير محدود.
لا صور أصلية إلى الواجهة لمجرد الإحصاء. العدد/البايتات/التقريب فيPython/SQL بدقةصحيحة/Decimal ومنزلتين،0–9.
الحذف دفعات محدودة، قفل واحد مرتب/منع التكرار، وقت/نتيجة قابلة للرصد، لاتعهدإفراغقرصأونسخاحتياطية فورًا.
الفحص الجديد مبرر: مسار حذف نهائي وصلاحيات/ERP/تزامن غير مغطى بقبولكاش5000؛ بيانات اصطناعية معزولة فقط، لاحملQA.
الاستعادة من مسار النسخ الاحتياطي المعتمد فقط؛ التراجع عن الكود لا يعيد محتوى محذوفًا.

## G2 — العقود والسلامة (مسودة)

تظل create/write/unlink العامة للرسائل/الوسائط محظورة. منفذ احتفاظ خاص يعيد فحص السلطة والنطاق والحماية تحتقفل.
معاينة قصيرة العمر مرتبطةcreator/currentcompany/scope/mode/cutoff/configrevision ومجموعة ضحايا ثابتة؛ لا توسيعها عندالتأكيد.
تأكيد مفرد لايتكرر؛ تغيرالصلاحية/الشركة/السياسة/انتهاءالمعاينة يرفض. أيحمايةأوربطجديد بعدالمعاينة يؤديskipمحسوبًا.
المالك أو تفويض احتفاظ مستقل مع عضويةداخليةفعالة وشركاتمخولة؛ لاauto-grant، ولااتخاذenv.su كإذن.
cron يعيد فحص الجهة التي اعتمدت السياسة، لا يسقط عزل الشركات عبرsudo؛ OFFلايفعلأيحذف.
تعريف الحالة النهائية يحافظUUID/digest/IDs للتكرار والردود؛ المحتوىالمحذوف لايعودفيhistory/gallery/reply/push/media.
العميل المتصل يبطل المحتوى المؤقت/المحفوظ عند مزامنة حالة الاحتفاظ؛ الجهاز غيرالمتصل لا يمكن إزالته عنبعدفوريًا، ويلتزمبمهلةالحسابالقائمة.
لا حذفir.attachment إلا بعدإثبات ملكيةBChatالخاصة وعدم مشاركة/ربطERP/DMS؛ لا ملفاتقرص عشوائية أوscanالنسخ الاحتياطية.
Auditإضافة فقط:actor/time/scope/mode/cutoff/counts/bytes/status، دوننصوصأوأسماءملفاتأوأسرار.
المشتريات/الفواتير/المخزون/المهام ومستنداتها وحساباتها وحقوقها لا تتغير؛ أيغموض ملكية يمنع الحذف ولا يخمّن سياسة مالية.

## G3/G4 — الرصة والتجربة (مسودة)

المسار الأصح والأقصر: نماذجOdoo19/ORM/PostgreSQL والأدواتالأصلية، لاحزمةأوخدمةأومخزنثانويجديد.
كتالوجالواجهة: native form/header/button/fields/many2many/select/date/list/search/dialog + Bootstrap/Odoo tokens.
إعادةاستخداممعرضOwlوالعرضوالفلاترالخادمية؛ لا كشفمحتوىللإدارةخارجعضويةالمستخدمالحالية.
مصادرالنصENمعar/ar_001؛ العربيةفصحىمبسطة، رسالةالحذفصريحةولامجرد«تنظيف»،0–9،RTL/LTRوجوال320وسطح1280.
Emil: لاموشنزخرفيأوتأخيرللحذف، عناصرلمسوتركيزواضح، حقولبأسماءثابتةودونفراغاتكبيرة.
التحسيناتالمطلوبةتعرضفيجدولBefore/Afterبمراجعةالواجهة، بلازيادةحجمخطعام.

## سجل البوابات

| البوابة | الحالة | دليل/مالك | مراجعة مستقلة |
|---|---|---|---|
| G0 | GO | عقدBRT/القائد | مراجعة مستقلة004؛ تنفيذ مرشح فقط، لا حذف تشغيلي أو نشر |
| G1 | GO بحدود التصميم | حدودالسعة/القائدومصممخدمة | مراجعة مستقلة004؛ الحدود التنفيذية العددية شرطG2 قبل الكود |
| G2 | GO للتنفيذ المحكوم | العقد النهائيbackend/client | مراجعة مستقلة006؛ activation latch خادمي OFF شرط إلزامي، لا تفعيل أو حذف تشغيلي |
| G3 | GO | reuseOdoo+RNnocreateDependencies | مراجعة مستقلة004؛ الأدوات الأصلية دون تبعيات أو مخزن جديد |
| G4 | GO تصميمي مبدئي | nativecatalog/EN-AR/ضيق | مراجعة007؛ قبول العرض الفعلي AR/EN320+wide لاحق |
| G5 | قيد التحقق | شريحة خادم ومزامنة وواجهة منفذة | دليل ORM المعزول مطلوب، ولا حذف تشغيلي |
| G6 | قيد التحقق | فحوص العقد والعميل والعرض | معالجة ملاحظات المراجع قبل تثبيت المرشح |
| G7–G8 | PENDING | مراجعة تسليم مستقلة ثم تسليم المصدر | لا تفويض نشر أو تفعيل ضمن هذه الجولة |

## دفتر العمليات الحي

- 001: قراءةمتجانسةقبلالتغيير: مهاراتbuild/governance/scale/architecture/design/ERP وOdooModels/Security/Testing/XML؛ registryBMS/BWA وmessage/media/room/v2_service/admin/gallery/workflow. النتيجة: immutablecontentومعرفسجلعارضافتراضي؛ لاappchangesقبلالبوابات.
- 002: تثبيتفرعمنofficial/main07f5f802معtrackedclean؛ حفظoutputالسابقدونمسح. لاQA/Liveأومكتبات.
- 003: مراجعةتصميممستقلةمحكومة: bridgeلخدمة/ERP، mobileللمزامنة/cache، gatekeeperللصلاحياتوالحذف. لاكتابةمنتجقبلاعتمادG0–G3.

## G2 final contract submitted for independent review

This supersedes ambiguous draft wording above; it is a design, not implemented evidence.

- Limits: source preflight100000 rows; exact eligible total or unavailable/null (never sampled). Oldest deterministic1000 frozen victims/run,100/batch,5min preview TTL, one active run/company, max10 policies/tick. UI distinguishes eligible_total, selected_for_run, remaining_eligible and batch_limited. A subsequent manual run needs a NEW preview; a confirmed run never grows.
- User methods: manual wizard.action_preview() opens immutable run; run.action_confirm() requires creator/current authorization+scope/config version/TTL and an explicit confirmation_checked field. It row-locks and is idempotent for already queued/running/completed jobs. action_cancel()/action_refresh() do not grant content access. No client-generated deletion paths or client counts.
- Policies: company_id, scope_mode(company|rooms), room_ids, enabled=False, mode(attachments|messages_and_attachments), retention_days(positive integer), schedule_hour00..23, schedule_minute00..59, IANA timezone, readonly approving owner/revision/next_run_at/last_run_at/status. Changes invalidate previews. One daily local-date execution identity, DST/missed slot semantics tested; revocation stops further work.
- Models in baseer_bwork_admin: retention.policy, retention.wizard, retention.run, retention.item, retention.audit; audit metadata append-only, readonly item manifest, action-only state transitions. Independent retention permission has no automatic assignments or implied content read. Owner/existing effective room-admin guard remains the conservative default; explicit role cannot expand company scope.
- Original rows/UUID/upload UUID/digest/linkage remain as minimal idempotency tombstones. Message text, media filename/content/thumbnail and reply/push previews are scrubbed through a private capability only. Public write/unlink/create guards remain. Attachments-only keeps text; messages_and_attachments removes message content. Unknown/shared/ERP/DMS/fiscal ownership blocks deletion, and existing staged cleanup remains TTL-bound. A new explicit server hold is NOT a local offline pin.
- Protocol: bootstrap.capabilities.retention_version=1, room.content_revision>=0; the same revision on history/detail/gallery and protected binary responses. Atomic destructive batch bumps room revision and publishes existing room change. Serializers/push/reconcile/reply/send-replay deny or omit removed content while retaining UUID idempotency.
- GET/POST content-state reconciliation is owned by BChat, authenticated and CSRF protected: POST /bchat/api/v2/rooms/<id>/content-state, body api_version2/membership_id/content_revision/media_ids(up to200 unique sorted IDs) plus bound cursor on followups. Server returns exact scope/revision and live canonical messages OR removed,128KiB max. Unknown/foreign IDs only yield removed, never existence disclosure. Cursor <=256bytes bound actor/company/room/member/revision/exact ID-list hash/last processed; changed revision409 content_changed with no mixed items.
- Client barrier: mask hot/history/browsing/gallery/reply/viewer/audio before reuse, persist incomplete marker before durable mutations; clear room history/coverage/retained/gallery metadata WITHOUT dropRoom/logout/outbox/stage mutation. Quarantine cached bytes/pin intents; reconcile <=5000 IDs in200-ID pages, filesystem work100/batch. Only server-removed final owned media-* bytes are deletion targets; unknown/failure stays unavailable. Restored live pins add sparse canonical associations, not history coverage/receipts. Late responses are revision/session/scope fenced; restart cannot unquarantine stale bytes. No lease renewal through reconciliation.
- Offline/legacy limit: disconnected or externally exported copies cannot be instantly erased. Existing0.1.30 does NOT implement the revision barrier; no old-client coherence claim. Policies remain OFF and activation is a later explicit owner operation after updating clients, never performed by this build.
- Storage overview reuses metadata guard and bounded SQL; fields retention_storage_by_room/by_kind, retention_storage_total/status are backend-owned and formatted, no UI aggregation. Own-member gallery remains the only content preview route, including largest sort and server-owned search.
- ERP guard: chat echoes of purchases/tasks cannot delete actual purchase/task/account/DMS records or files. No financial/stock state transition, fiscal dependency install, or role assignment. Uncertain references preserve data.

### G2 concurrency refinement — independent review finding

Row locking alone does not prove absence of an incoming reference committed after an Odoo REPEATABLE READ snapshot. The executor must lock the message, media and owned attachment parents in fixed order, check references visible to its own transaction (including its uncommitted changes), and obtain a fresh READ COMMITTED READ ONLY boolean-only incoming-reference veto before scrub. No payload, source record, content authority or business write leaves this private probe. Unknown/inconsistent metadata fails closed. Native concurrency evidence remains mandatory; the design is not proof. A blanket unknown-FK-schema veto must not masquerade as functional deletion, because ordinary mail/M2M schemas could exclude every attachment. Tombstone IDs may be referenced after erasure, but this never restores their content; already linked original ERP data must remain intact.

Primary source checked for isolation/default and cursor lifecycle: [Odoo 19 SQL connector](https://raw.githubusercontent.com/odoo/odoo/19.0/odoo/sql_db.py). The concurrency failure/fix remains a project inference requiring the isolated proof, not a claim made by this reference.

## دليل التنفيذ الجاري — ليس قبول إصدار

- العميل الأصلي: أضيفت عشرة حراس سلوك دون تغيير 187 حارسًا سابقًا. بوابة BWork الأولية مرّت: 197 سلوكًا مع فحص TypeScript، 24.89 ثانية. يوجد benchmark أرشيف واحد مستثنى عمدًا من هذه البوابة كما في الإعداد السابق؛ ليس من حراس القبول. هذه النتيجة قبل إصلاحات المراجعة اللاحقة، وليست دليل المرشح النهائي.
- بعد إصلاحات المراجعة: أصبح الحراس الجدد 15 والمجموع 202. بوابة 200 السابقة مرّت في 23.97 ثانية قبل آخر دلتتين؛ أُعيدت فقط الشريحة المتأثرة بعد استقرارها: TypeScript PASS، و380 اختبار محادثات (379 PASS، benchmark واحد مستثنى بالإعداد السابق)، مع إثبات تنفيذ حراسها الـ125 جميعًا. بقية مجموعات الطلبات والمهام والمالية والهوية والإشعارات لم تتغير وأُعيد استخدام نتائجها الناجحة. المراجع المستقل أجاز مصدر الجوال بعد قراءة الإصلاحات؛ ليس ذلك قبولًا للخادم أو نشرًا.
- واجهة المعرض: الاختبارات السبعة السابقة وثمانية اختبارات جديدة PASS؛ المراجعة الخادمية والردود المتأخرة والنطاق وCSRF والحماية وإلغاء الحماية مشمولة.
- واجهات أودو: خمسة اختبارات XML/الحقول/تأكيد الحذف/حاجز التفعيل/مراجع الترجمة PASS. تغطي ملفات ar وar_001 ومئتي عبارة، وليست تشغيلًا لنموذج أودو المثبّت.
- معاينة فعلية لمكونات المعرض باستخدام Owl وBootstrap الرسميين المخزنين سابقًا: 10/10 حالات PASS بالعربية والإنجليزية، 320 و1280 وتكبير الخط إلى 130%، مع الحالة الفارغة والمرفوضة. فحص مستقل للقطات دون overflow أفقي؛ التمرير الرأسي طبيعي. الدليل output/bwork-retention-console-20261020/owl/acceptance.json، SHA256 DF39FC2CA4151AE9BDED584AE6E11FA5DEDEB1184BE19D5FF39EAE43976B643C. الشبكة اصطناعية على localhost فقط؛ ليس تشغيل نموذج الإدارة الكامل أو حذف بيانات حقيقية.
- المراجع المستقل كشف قبل التسليم مسارين P1 في عودة محتوى القرص بعد force-stop، وفي سحب صلاحية الوسائط مع طابور نصوص قائم. المالك يعالج باختبارات RED→GREEN؛ لا إخفاء للملاحظات أو تخفيف الصلاحيات. عرض حجم الملف بعد الحماية ملاحظة P2 أخرى أُرسلت لمالك الخادم.
- إعادة استخدام الخريطة أعلاه بفرق BRT فقط. قائد التسليم يجمع حارس البيانات/الأمان/العقود والسعة عبر المراجع المستقل، ومختبر العميل والعرض مستقل عن مؤلف واجهة المعرض. لا دليل تحمّل لسعة أكبر من الحدود المفروضة، ولا تجربة استعادة نسخة احتياطية أو حذف تشغيلي ضمن المهمة.
- مرشح المصدر الأول c20608af في Draft PR437: سلامة المصدر والعقود التراكمية واختبارات المهام ومسار المشتريات نجحت. فشلت اختبارات الإدارة والمعرض والاحتفاظ قبل بدء الحالات بسبب اسم CSV الجديد retention_access؛ محمّل أودو يستنتج اسم النموذج من اسم الملف. نُقل الملف إلى security/retention/ir.model.access.csv بنفس الصفوف والقيم، دون تغيير ملف ACL الأصلي أو منح صلاحيات. لا يُعد هذا الفشل نجاح ORM أو قبولًا للمرشح.
- مانع بصمة المعاينة أُصلح أيضًا: فحص معرفات المرفقات وحدها لا يرصد تغيير محتواها بنفس المعرف. تُبصم الآن بيانات checksum/file_size/write_date وملكية/حماية المرفق، ويُقارن بعد أقفال المصدر. اختبار أساليب الإنتاج الفعلية أعاد RED مقابل c20608af ثم GREEN على الإصلاح؛ الحالة الأصلية الجديدة تنتظر تنفيذ أودو المعزول. زاد العدد المحدد من 11 إلى 12 حالة أصلية بإضافة واحدة، دون إسقاط اختبارات سابقة.

### UI refinement intent

| Before | After | Why |
|---|---|---|
| NewId technical title | Stable translated BWork Administration title | No internal identifiers in navigation |
| Large stacked labels/values | Compact native KPI cards and short tabs | Mobile density without enlarging typography |
| Storage numbers only | Bounded room/type breakdown and own-member largest-file gallery | Understand consumption without new content permissions |
| No retention commands | OFF policies, scoped preview/confirm/run/audit forms | Explicit consequence before irreversible server erasure |

- 004: G2 wire/service agreement received from bridge/mobile; independent approval pending. No product code has started. Official Odoo19 scheduled-action batching reference: https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html . Reuse existing native cron, no queue framework or new package.

- 005: Independent G2 reviewer approved controlled implementation with a mandatory readiness latch. It is server-owned, OFF by default and independent of policy.enabled. All new destructive confirmation/cron paths fail closed before any scrub unless a later authorized readiness action records client-upgrade acknowledgement and offline/legacy limits. Migration/deployment/policy.enabled cannot open it. This build never calls readiness activation on QA/Live; synthetic isolated tests may do so only inside test transactions. No fleet/version registry or auto-detection claim is introduced.
- 006: Product implementation starts only after the independently recorded G0/G1/G2/G3 decisions. Backend owner: bridge (models/security/manifests/backend tests/protocol controllers). Client owner: mobile (RN/archive/runtime/protocol/tests only). Root: native views/styles/translations, Owl gallery client and UI tests, contract/log integration. Review owner never approves evidence they implement.
- 004: قرار حارس مستقل بعد قراءة العقد كاملًا: G0 وG3 GO؛ تفويض التنفيذ لا يتضمن تشغيل حذف QA/Live أو نشرًا. G1 GO لحد المصدر100000 والفحص الاصطناعي المعزول فقط، لا إثبات أداء جديد أو سعةمالك مفترضة. يلزم في G2 تحديد سقف ضحايا المعاينة والدفعة ومهلةالمعاينة وحدوقت/توقفcron رقميًا قبل الكود؛ المقترح المحافظ1000ضحية/100دفعة/5دقائق معاينة وليس ادعاء قدرة. G2 لا يزالPENDING فلا يبدأ المنتج.
- 005: اشتراطات G2 المستقلة: scrub خاص محروس لا يفتح write/unlink العامة ولا يعدلFK/UUID/idempotency؛ الردود والمشتقات والـthumbs وpush المؤجل لا تحتفظ بنص محذوف أو تعيد إظهاره. الاحتفاظ بمعرّف/tombstone ليس الاحتفاظ بالمحتوى. يجب توثيق protected/sharedattachment/reference فحصًا نهائيًا تحتقفل، وsingleuse/revoke/preserve/policyrevision ومحاسبةdeleted/skipped/failed والاستئناف. آلية invalidation للمحفوظ/retained وold1.30/offline24h حدود صريحة؛ pin محلي ليس استثناءاحتفاظخادم. يلزم دليل nativeORM/HTTP/cron/races وclientcache/restart اصطناعي مناسب قبل التسليم، دون حذف بياناتالمالك أو توسيعصلاحيات.
- 006: G2 GO مستقل للتنفيذ بعد قراءة العقد النهائي واتفاق الخادم/الجوال: source100000/exacttotals،1000victims/100batch/5min/oneactivecompany/max10policies، immutabletombstones/privatecapability، revisionbarrier وboundedexact-IDreconcile مقبولة كتصميم وليست أدلة تنفيذ. شرط ملزم قبل أي مسار حاذف: readiness/activation latch خادمي مستقل عنpolicy.enabled، OFF افتراضيًا؛ confirm والتنفيذ وcron يعيدون فحصه قبلscrub ويفشلون مغلقًا بدونه. لا يفعّلهmigration أو النشر أو مجرد تحريرenabled، ولا يُشغّل بهذه المهمة؛ تفعيله لاحقًا يحتاج إجراءً معتمدًا منفصلًا يؤكد تحديث العملاء والإقرار بحدودold1.30/offline/exportedcopies. لا يلزم بناءregistryأجهزة جديد لهذه الجولة أو ادعاءأنcapabilityمنطلبواحد يثبت تحديثالجميع. تفعيلlatch فقط داخلtransactionاختبارية اصطناعية معزولة مسموح لإثبات المنفذ. لا QA/Live deletion أو activation أو releaseGO.
- 007: مراجعة مستقلة للإضافات: expired_uploads يدوي فقط ضمنالمنفذالجديدالمحروس/readinesslatch، IDsمجمدة وحدود1000/100 وTTL24h/no message/no activegrant وإعادةفحصexactattachmentowner/inverse/company/hold/ERP/DMS/sharedrefs؛ existingclose('expired') لايحذفrows/UUID ولايغيّرcron24hالقائم أوrevision لغيرالمنشور. البحثfilename-only≤128UTF8 وliteralescaping%/_/backslash ورفضNUL،cursorمقيدqhash/filter/revision ونفسauth/page/bytecaps. تعريفgroupفقطدونimplied/autogrants. قُرئتnativeviews/feature-localSCSS: G4 GOتصميمي مبدئي للcompactcards/hourminute/dangerwarning+checkbox+confirm دونزيادةخطعام؛ لا ادعاءعرضفعلي قبلAR/EN320+wide وlatchOFF. لاactivation/deletion/نشرتشغيلي.
