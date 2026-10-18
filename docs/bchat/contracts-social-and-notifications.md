# BCH-DEV-SOCIAL-1 — عقد G2 للمحادثات والتنبيهات

الحالة: **GO للعقد من مراجعة G2 مستقلة قبل الكود**، بتاريخ 2026-10-17 (DEV025 لدى القائد). هذا إذن تنفيذ المصدر فقط، وليس قبول runtime أو ORM أو تزامن أو إصدار.
يتبع `docs/build-governance/BCHAT-DEVELOPMENT-PROGRAM.md`؛ النطاق C05/C06/C16/C17/C18/C19/C32 فقط. لا QA/LIVE أو تثبيت حزم أو سياسة حذف أعمال. شريحة C03/C04 المجمدة واختباراتها مستقلة؛ لا تُعاد تسميتها نجاح ORM أو تزامن قبل تشغيل الدليل الحقيقي.

## 1. الحدود والمسار الأقصر

- إعادة استخدام خدمة Odoo الخاصة، جلسة WebView وCSRF، حقبة العضوية، PostgreSQL، مسار الرسالة/الوسيط، والتلميحات وFCM القائمين. لا Discuss أو مخزن رسائل ثانٍ أو مصادقة موازية أو استخراج كوكيز أو بحث سحابي.
- كل قراءة تبدأ بحساب داخلي نشط وحق مناسب وشركة حالية مصرح بها، ثم قفل الغرفة وإعادة العضوية النشطة. الرسالة المرئية تحقق `room/company` و`message.id > joined_after_message_id`. ترسل الكتابة `membership_id` الحالي؛ اختلافه `membership_changed`، ولا تعيد إحياء حقبة قديمة.
- البحث أو الحفظ أو الإشارة لا يمنح محتوى أو أصل وسيط. المعاينة تحتاج `media_view`، والأصل يحتاج `media_download`، والرفع `media_upload + chat_send`، بجانب الشركة والعضوية دائمًا.
- لا تتغير دلالة sent/delivered/read. البحث، معاينة نتيجة، رد FCM، فتح مركز الملفات، أو اختبار التنبيه لا يكتب `read_at` أو `delivered_at`.
- لا أسعار/مجاميع جديدة في هذه الشرائح. رسائل الأعمال والمستندات تبقى immutable، ولا نسخ محتوى إلى سجلات التفضيلات أو العمليات.

### التوافق

- `api_version=2` و`permissions.version=1` باقيان. v87 يرفض capability غير معروف قيمته true؛ لذلك لا نضيف أعلامًا داخل `capabilities`.
- الإعلان **بعد التنفيذ واختباره فقط** بخصائص أعلى bootstrap: `social_contract_version: 1`، `notification_preferences_version: 1`، `notification_diagnostics_version: 1`. غيابها يعطّل الواجهة الجديدة؛ لا تحويل صامت إلى مسار أضعف.
- مسارات v87 وأشكال reply/digest/ACK القائمـة لا تتغير عند غياب الميزة الجديدة. تستخدم التحديثات الاجتماعية نوع التلميح القائم `room`، لا kind مجهول يكسر عميلًا قديمًا. المحفوظات والتفضيلات الخاصة لا تنشر إلا لصاحبها.
- كل POST أدناه form `{csrf_token,payload}` وجلسة auth=user فردية، no-CORS/no-store، مفاتيح دقيقة وأنواع strict. GET وبحث POST الموصوف أدناه بلا أثر كتابي أو ACK. حد الطلب 64KiB؛ حالات التشخيص/الإعدادات 8KiB.

## 2. ملكية البيانات والذرية

| التخزين المقترح | الملكية والقيود |
|---|---|
| `baseer.bchat.membership.preference` | model خاص one-to-one للعضوية: membership_id وuser_id المتطابق مع صاحبها، unique(membership_id)، مع muted_until/mute_forever/pinned_at/archived/revision. افتراضه غير مكتوم/غير مثبت/غير مؤرشف. لا related/نسخة لحقوله على membership ولا استثناء room_admin |
| حد إداري على `baseer.bchat.membership` | `joined_after_group_event_id` فقط لحد رؤية تاريخ إدارة الحقبة الجديدة؛ لا تفضيلات شخصية على membership الذي يقرأه مدير الغرف |
| `baseer.bchat.direct.pair` | `company_id`, `low_user_id`, `high_user_id`, `room_id`؛ low < high وunique للشركة/الزوج، room واحد، لا تصنيف تلقائي لغرف legacy |
| `baseer.bchat.social.operation` | سجل append-only ضيق: actor، action، UUID، digest، company/room/membership إن وجدت، مرجع النتيجة/revision، وقت الخادم. unique(actor, action, UUID)، لا نص رسالة أو query أو توكن؛ نتيجة مرجعية <=4KiB |
| `baseer.bchat.group.event` | سجل إدارة append-only: room/company، actor وحقبته إن كان عضوًا، action/target IDs، وقت الخادم، نسخة metadata محدودة عند الحاجة؛ لا جسم رسالة أو مستند |
| `baseer.bchat.message.reaction` | message/room/company، actor ومembership، emoji من قائمة ثابتة، active/revision؛ unique(message,actor,membership). العرض الافتراضي counts + own reaction، لا دليل أشخاص جديد |
| `baseer.bchat.message.saved` | user/message/room/company/membership، active/revision، saved_at؛ unique(user,message,membership)، إشارة خاصة لا نسخة نص/ملف |
| `baseer.bchat.message.mention` | مرجع immutable: message وrecipient_user/membership وقت الإنشاء؛ unique(message,recipient_membership). لا ربط تلقائي باسم مشابه |
| حقول `baseer.bchat.push.device` | `preview_mode=none/sender/full` وrevision؛ default none. التفضيل لجهاز/حساب مسجل بعينه، وليس لكل الشركة |
| امتداد `baseer.bchat.push.event` | diagnostic نوع ثالث محدود بلا message/task، UUID فريد للجهاز، مع بقاء قيد source-shape للأنواع الثلاثة وعدم قبول مصدرين |

ليس لأي موديل خاص جديد ACL إنشاء/قراءة/كتابة عامة عبر ORM؛ حدود الخدمة الضيقة فقط، وACL/record rules مُختبرة للحساب العادي والمدير والبوابة. لا يكتسب مدير الغرف قراءة المحفوظات أو تفضيلات جهاز شخص آخر.

تفضيلات العضوية لا تستند إلى إخفاء fields أو `groups=no_one`: لا ORM ACL عام للـmodel الخاص ولا view إداري يكشفها. الخدمة تعيد تفضيل العضوية الذاتية الحالية فقط، وتجمع التفضيلات باستعلام scoped واحد على IDs العضويات التي ثبت أن user_id لها هو حساب الجلسة. ACL قراءة membership القائم للمدير لا يمتد إلى جدول التفضيلات. مصفوفة الأفعال: reaction يحتاج chat_view+chat_send، saved يحتاج chat_view فقط؛ كلاهما يحتاج الشركة والعضوية الحالية والرسالة المرئية.

الفهارس المقصودة مرتبطة بالقراءات: saved(user,active,id DESC)، reaction(message,active)، mention(recipient_membership,message_id DESC)، group_event(room,id DESC)، ومفاتيح pair/operation الفريدة؛ لا فهرس تخميني لكل حقل. السجلات التقنية/social audit لا تُحذف تلقائيًا في هذه الشريحة؛ خطة الاحتفاظ الآمن العامة منفصلة، ولا وعد نمو لسنوات من دون قياس. لا يمنع سجل جديد تعطيل موظف.

### منع التكرار والأقفال

- عمليات التفضيل/التفاعل/الحفظ وإضافة مجموعة أعضاء ترسل `client_uuid` و`expected_revision` حيث توجد حالة قابلة للتغيير. إعادة نفس UUID ونفس digest تعيد المرجع الملتزم مرة واحدة؛ اختلافه `idempotency_conflict`. تعاد أهلية الحساب/الشركة/الحقبة **قبل** replay؛ المرجع القديم ليس إذنًا دائمًا.
- تُقفل الغرفة قبل إسقاط/إضافة العضويات أو تغيير التفاعل، وتُقفل صفوف metadata بترتيب ثابت. العملية المركبة تجمع **اتحاد كل مستلمي الدفعة** وتحجز cursors تصاعديًا قبل أول hint، ثم لا تجلب مستلمين إضافيين بعده. لا نشر ضمن حلقة أقفال جزئية.
- إنشاء direct يستخدم مفتاح الزوج canonical وقيد SQL نهائي، وتحققًا جديدًا عند تعارض UNIQUE/40001. لا catch عام يفسر فشلًا غير مرتبط كنجاح. لا إعادة إرسال طلب أعمال أو تغيير UUID لاسترداد تفاعل.
- الترحيل additive فقط: قيم تفضيل محافظة، إنشاء فهارس وجداول، ولا رسالة/عضوية/إيصال قديم يُحذف أو يتغير. لا backfill وهمي لتاريخ إدارة لم يُسجل سابقًا. تراجع العميل القديم يبقى محافظًا؛ لا حذف للجداول لعمل rollback.

## 3. C16 — بحث التاريخ ومركز الوسائط

المساران الجديدان المقترحان:

- `POST /bchat/api/v2/rooms/{room_id}/search`؛ form+CSRF، payload `{api_version,membership_id,q,kind,before_id}`، kind من all/text/image/file/audio، وbefore_id موجب أو null. بحث النص أو اسم الملف المرئي كلاهما بهذا المسار، لا q في URL.
- `GET /bchat/api/v2/rooms/{room_id}/media?membership_id=…&kind=image|file|audio|all&before_id=…`؛ gallery بفلاتر IDs/kind فقط، لا q أو مصطلحات خاصة في query string.

اختيار POST هنا لحماية كلمات البحث من access-log URL، لا لأنه عملية كتابة. لا client_uuid أو سجل إرسال أو outbox أو تغيير رسالة أو receipt أو history للبحث. يعرّف العميل هذا المسار تحديدًا `read-only query` قابلًا لإعادة المحاولة الآمنة مثل GET، لا عبر قاعدة تعيد POST عامة. يسري retry على البحث نفسه فقط، ولا يغير UUID رسالة ولا يعيد رفع وسيط. لا تسجل request body أو q في telemetry/log، وno-store يبقى قائمًا؛ POST وحده ليس حماية إذا كان مُشغّلٌ يسجل أجسام الطلبات.

النتيجة `{api_version:2,membership_id,messages:[canonical message rows],next_before_id}`. قبل cursor موجب اختياري؛ الفرز id تنازليًا والنتائج تعرض زمنيًا كما التاريخ القائم، <=30 رسالة و128KiB **بعد JSON/UTF-8**. يصغر عدد النتائج قبل الرد إن لزم؛ cursor أصغر message ID في الصفحة المعادة، لا أقدم صف جرى إسقاطه لتصغير البايتات. لا COUNT كامل ولا تحميل سنوات إلى التطبيق ولا تخمين غياب نتيجة من صفحة واحدة.

- q نص literal <=128 UTF-8 bytes، وعدد كلماته <=8؛ لا SQL أو tsquery خام من العميل. بحث لفظي عربي/إنجليزي باستخدام PostgreSQL `simple` وquery مُعلَّم المعاملات، وليس بحثًا دلاليًا أو OCR أو اشتقاقًا لغويًا عربيًا معلنًا.
- GIN expression على `to_tsvector('simple',coalesce(message.text,''))`، وعلى اسم الوسيط عند الحاجة، مع فهرس room/id القائم. لا حاجة لـpg_trgm أو مزود/حزمة جديدة. تُراجع EXPLAIN ببيانات اصطناعية لاحقًا؛ لا ادعاء زمن أداء أو سعة من وجود الفهرس وحده.
- البحث العام لا يطابق أسماء ملفات عند غياب media_view؛ filters الوسائط ومركزها تتطلبه. الوسيط يجب attached ومربوطًا برسالة مرئية في الحقبة؛ staged/cancelled/expired لا يدخل المركز. الأصل وDMS يخضعان لحراس C03 القائمة، لا رابط عام أو base64 في النتيجة.
- الانتقال من النتيجة يعيد GET الرسالة الموجود ويثبت company/room/epoch. لا تستخدم نتيجة بحث قديمة لتجاوز حارس الرد أو فتح محادثة مسحوبة.

## 4. C17 — كتم/تثبيت/أرشفة شخصية

- `GET /rooms/{id}/preferences?membership_id=…`، وPOST للمسار نفسه: `{api_version, membership_id,client_uuid,expected_revision,muted_until,mute_forever,pinned,archived}`، مع chat_view والعضوية الذاتية فقط. الأنواع Boolean حقيقية؛ `muted_until` UTC من المستقبل إلى سنة كحد أقصى، ولا يجتمع مع forever. الخادم يحدد pinned_at وrevision.
- المقترح المعروض للاعتماد: الكتم يوقف push للمحادثة ومهامها المرتبطة فقط؛ المهام المستقلة لا تتأثر. لا استثناء mentions يتجاوز الكتم بلا سياسة أخرى. تُقرأ التفضيلات **عند enqueue وعند dispatch/retry**؛ إلغاء push لا يلغي الرسالة أو hint أو unread.
- الأرشفة لا حذف ولا كتم ولا قراءة؛ تبقى إلى unarchive صريح ولا تظهر الغرفة في القائمة الرئيسية الجديدة، مع تبويب مؤرشفات وعداده. الرسائل الجديدة لا تعيد إظهارها تلقائيًا. التثبيت ترتيب شخصي pinned_at ثم آخر رسالة ثم id، ضمن سقف100غرفة القائم.
- `/rooms` وsnapshots القديمة تبقي جميع الغرف المصرح بها حتى لا يفسر v87/حارس cache إخفاء المؤرشف كسحب حق. يقرأ العميل الجديد `GET /bchat/api/v2/social/rooms?archived=true|false&cursor=…` بتفضيلات مجمعة <=30/صفحة و128KiB. يعاد استخدام قائمة الغرف المصرح بها المحدودة أصلًا100، وتُجمع التفضيلات باستعلام واحد، ثم ترتيب/صفحات في الخادم دون سلسلة queries لكل غرفة. cursor tuple مقنن <=512بايت مربوط بالفلتر والمستخدم وحقول الترتيب `(pinned,pinned_at,last_message_id,room_id)`؛ ليس room_id وحده. تغير نشاط غرفة بين الصفحات قد يغيّر موضعها، لذلك refresh يعيد البداية ولا يُدَّعى snapshot متعدد الطلبات.
- انتهاء العضوية لا ينقل التفضيل تلقائيًا إلى حقبة جديدة. ترجع الحقبة الجديدة افتراضاتها المحافظة ولا تعرض cache القديم. التفضيل لا يغيّر مستخدمًا آخر.

## 5. C18 — direct pair دون تدمير القديم

`POST /bchat/api/v2/direct-rooms` مع `{api_version,company_id,peer_user_id,client_uuid}`. يشترط للطالب chat_view+chat_send+group_create القائمـة؛ لا نشتق حق إنشاء أوسع صامتًا. نظهر هذا القيد في UI. الزميل مختلف عن الطالب، داخلي ونشط وله الشركة وchat_view؛ لا يلزم منحه حق إنشاء مجموعات أو قراءة جديدة.

- canonical pair=(company,min(userA,userB),max(...)). النجاح يعيد `{room_id,membership_id,created}` بعد تحقق العضوية الحالية. طلبا A→B وB→A المتزامنان يعيدان الغرفة نفسها.
- الغرفة الجديدة ذات عضوين بالضبط وليست managed group؛ لا rename/group-add يحوّلها إلى مجموعة أو طرف ثالث. حد الغرف100 للمستخدمين يطبق تحت الأقفال القائمة. أسماء العرض من دليل مصرح، لا أسماء يرسلها العميل.
- legacy ذات عضوين تبقى كما هي؛ لا merge أو حذف أو إعادة ربط رسائل/وسائط. unique ينطبق على direct الجديدة فقط. وجود legacy لا يمنع direct ولا يصنّفها تلقائيًا.
- إذا كان pair قائمًا ولكن عضوية أحد الطرفين سُحبت، ترجع `direct_unavailable` عامة؛ لا تعيد join تلقائيًا ولا تنشئ بديلًا يلتف على سحب الإدارة. استعادة صريحة من room_admin تنشئ حقبة جديدة عبر المسار الإداري المعتمد فقط. تعطيل حساب/سحب شركة يمنع replay/فتح المحتوى.

## 6. C19 — دليل محدود، اختيار متعدد، وتاريخ إدارة

- `GET /bchat/api/v2/social/member-candidates?company_id=…&q=…&after_user_id=…`، <=40 اسمًا و64KiB، ترتيب id ثابت وcursor على آخر ID معروض؛ q<=80حرفًا/256بايت. filtering داخلي/نشط/شركة/chat_view قبل إعادة اسم. حق الطالب حسب إجراء direct/group الموجود، لا دليل HR عام أو صور إضافية. يبقى member-candidates القديم كما هو.
- إنشاء مجموعة متعددة يستخدم API الإنشاء القائم، <=49 زميلًا +المنشئ =50. إضافة دفعة جديدة: `POST /rooms/{id}/group/members` مع `{api_version,membership_id,client_uuid,user_ids}`، <=49 IDs فريدة، تحقق كامل للدفعة وسعة الغرفة وأهلية كل شخص ثم commit واحد. لا تجاهل عنصر مرفوض أو إضافات جزئية؛ لا تغيير last-admin/recovery المعتمدين.
- `GET /rooms/{id}/group/events?membership_id=…&before_id=…` <=30/64KiB؛ للمشرف الفعال الحالي أو room_admin المصرح لهذه الشركة فقط. تحت قفل الغرفة يُحفظ أقصى event ID قائم وقت انضمام الحقبة في `joined_after_group_event_id`؛ المشرف العضو يرى IDs بعد الحد فقط، لا مقارنة زمن عميل أو message ID بevent ID. room_admin غير العضو يدخل بمسار إداري صريح بلا membership مزيف ويرى metadata الإدارة فقط، لا الرسائل أو المرفقات.
- يسجل الخادم create/add/remove/leave/promote/demote/rename/description/avatar/recover، actor/target/time وoperation UUID عند توفره. أحداث المجموعة القديمة غير الموجودة لا تُخترع؛ يذكر `audit_started_at` حد اكتمال السجل.

## 7. C32 — إضافات فوق الرسالة immutable

### التفاعلات والمحفوظات

- `POST /rooms/{id}/messages/{message_id}/reaction` مع `{api_version,membership_id,client_uuid,expected_revision,emoji}`، يحتاج chat_view+chat_send. emoji null يزيل التفاعل الشخصي؛ خلافه واحد من `👍`, `❤️`, `😂`, `😮`, `😢`, `🙏` canonical exact، لا UTF-16 slicing أو emoji عشوائي غير محدود. تفاعل واحد للشخص/الرسالة/حقبته؛ revision يخص تفاعله الشخصي لا مجموع تفاعلات الآخرين. تغييره metadata مع audit، لا edit للرسالة.
- `POST /rooms/{id}/messages/{message_id}/saved` مع `{api_version,membership_id,client_uuid,expected_revision,saved}`، يحتاج chat_view فقط للعضو الحالي؛ مصدر الحقيقة مرجع خاص بالخادم، لا snapshot محتوى. إزالة الحفظ تعطل المرجع وتحفظ حدث العملية فقط.
- `GET /rooms/{id}/social-metadata?membership_id=…&message_ids=1,2,…` لرسائل مرئية <=30 IDs فريدة و64KiB؛ النتيجة rows بالـmessage_id وreaction_counts وown_reaction وreaction_revision وsaved وsaved_revision وmention_user_ids المصرح بها. أول projection غائب revision=0؛ أول GET تفضيل عضوية/جهاز يعيد revision=1، ثم CAS يزيده. لا positive-ID validator يرفض revision=0 للحالة الغائبة.
- GET `/bchat/api/v2/social/saved?before_id=…` <=30/128KiB؛ تُصفّى العضوية/الحقبة المرئية قبل limit/cursor. تُجمع counts والتفاعل الشخصي دفعة واحدة؛ لا N+1 اسم أشخاص أو أصل وسيط. الـsaved لا يعطي استثناء epoch: عند سحب الحق يحجب العنصر والمقتطف/الاسم ويُمسح cache المحتوى عبر حارس السحب القائم، لا تُحذف رسالة الأعمال.

### الإشارات

- الإنشاء فقط عبر `POST /rooms/{id}/social/messages`، payload الرسالة الحالي + `mention_user_ids` <=49 IDs فريدة من أعضاء الغرفة الحاليين المؤهلين، دون @all أو parsing اسم حر. نص `@اسم` وحده لا ينشئ إشارة.
- المسار الجديد يمر **بنفس تنفيذ حفظ الرسالة والوسيط والإيصالات** مع normalize داخلي موثق، لا يستدعي إرسالًا ثانيًا بعد الإنشاء. يُضاف mention_user_ids إلى digest canonical فقط في مسار social وعند وجود قيم؛ المسار القديم وغياب mentions يحافظان على البصمة القديمة byte-for-byte.
- تُنشأ صفوف mention في المعاملة نفسها بعد تحقق targets تحت قفل الغرفة. نفس UUID مع تغيير mentions يفشل idempotency_conflict؛ لا يمكن تحويل replay لرسالة v87 إلى mention لاحقة. fresh-replay ووسيط/مستند/رد تُختبر عبر المسارين قبل القبول.
- لا push إضافي للإشارة فوق حدث الرسالة الموجود ولا bypass للكتم. فتح mention يعيد تحقق الرسالة والحقبة؛ mention ليست صلاحية أو إيصال قراءة.

### التعديل والحذف والحضور

لا edit/delete endpoint أو UI enabled في هذه الشريحة: الرسائل والمستندات سجل أعمال محمي، ولا سياسة مالك تحدد نافذة التعديل، النسخ السابقة، محو/إخفاء المحتوى، الأدوار، الحفظ القانوني أو الأثر على الردود والمستندات. «تنفيذ كل التحسينات» لا يختلق هذه السياسة. يعلن العقد `message_edit_policy: "immutable"` داخل metadata الاجتماعية الجديدة، لا capability true. إعادة توجيه المحتوى والحضور والمكالمات والبوتات ليست مسارات منفذة ضمن C32.

## 8. C05 — خصوصية المعاينة من الخادم

`GET/POST /bchat/api/v2/notifications/preferences`؛ POST `{api_version,installation_id,account_key,client_uuid,expected_revision,preview_mode}`. الجهاز نشط ويخص حساب الجلسة الحالي؛ account_key قرينة ربط لا بديل للمصادقة. تحديث آخر جهاز لا يغير أجهزة المستخدم الأخرى. إعادة register القديمة لا تعيد التفضيل؛ تبديل حساب لا يرث opt-in السابق.

| الوضع | ما يجوز إرساله إلى FCM |
|---|---|
| none (الافتراضي للجديد والقائم عند الترحيل) | account_key + kind + event_id فقط؛ لا اسم مرسل أو نص أو اسم ملف أو عنوان مهمة |
| sender (اختيار صريح) | نفس السابق + sender_name المصفى/المحدود فقط للمحادثات |
| full (اختيار صريح) | السابق + message_preview<=160حرفًا مصفى، أو attachment نوع عام بلا اسم ملف؛ لا محتوى مستند/مبلغ/عنوان مهمة إضافي |

- يقرأ dispatch/retry أحدث وضع بعد تحقق recipient الحالي والكتم. خفض الوضع يمنع تسريب مقتطف في محاولة لاحقة؛ لا تخزين payload فيه النص في event/log.
- Android يطابق account الحالي، ويطبق none محليًا أيضًا، وVISIBILITY_PRIVATE/publicVersion عامة. OS/channel/lock-screen خيارات المستخدم لا تُجبر أو تُستبدل بقناة جديدة. اختيار full ليس E2EE ولا ضمان خصوصية شاشة القفل؛ محتوى opted-in يمر بالمزود.
- قبول none يختبر جسم HTTP الفعلي الخارج إلى FCM، وليس إخفاء النص في UI فقط. v87 يظل يتلقى event عامًا صالحًا؛ لا ادعاء أن اختياره المحلي القديم غيّر عقد الخادم.

## 9. C06 — تشخيص ذاتي بلا رسائل أعمال وهمية

- `POST /bchat/api/v2/notifications/test` مع `{api_version,installation_id,account_key,client_uuid}`، لحساب داخلي نشط له chat_view أو task_view، والجهاز النشط الحالي فقط. لا recipient_id اختياري أو إرسال إلى موظف آخر أو إنشاء مستخدم/غرفة/مهمة.
- نفس UUID يعيد نفس event قبل حساب المعدل. إنشاء جديد <=1/60ثانية للجهاز و10/24ساعة للحساب عبر أجهزته؛ حجز advisory خاص بالمستخدم أولًا ثم صف الجهاز قبل فحص الحدود والإنشاء، مع فهارس diagnostic(device_id,create_date,id) و(recipient_id,create_date,id). لا إعادة استخدام cursor التلميحات لrate limiting. تجاوز الحد 429 مع retry_after_seconds؛ لا event إضافي.
- قفل advisory وحده لا يجدد snapshot من نوع REPEATABLE READ: بعده تُقرأ نافذة quota باتحاد IDs محدود من المعاملة الحالية وcursor قراءة جديد، حتى تدخل الاختبارات الملتزمة أثناء الانتظار وتبقى اختبارات المعاملة نفسها غير الملتزمة محسوبة. كل cursor يقرأ10 recent و1 latest فقط؛ لا `COUNT` غير محدود ولا تعديل صف أعمال لتسلسل الحد.
- diagnostic event يحمل kind=diagnostic وevent_id وdiagnostic_uuid وaccount_key فقط، ويستخدم queue/dispatch/cron/error classifier القائم. يُعاد تحقق مالك الجهاز والشركة والحق الحالي؛ الحدث diagnostic ليس message/task ويحتاج تعديل source-shape صريح مختبر. لا معاينة اسم أو نص حتى في full.
- GET `/notifications/test/{event_id}?installation_id=…` يعرض للحساب/الجهاز نفسه فقط مراحل منفصلة: registration active، configuration state، pending/retry/failed، provider_accepted_at إن كان sent. لا محتوى config أو token أو أخطاء مزود خام. آخر اختبار واحد وIDs/enum/وقت فقط، response<=8KiB.
- Android/root يضيف قبول kind=diagnostic وتسجيل **received_at محليًا بعد مطابقة account/id وقبل فحص إذن إظهار الإشعار**، وdisplayed_at بعد notify الناجح؛ بقيود ledger الحالية. UI يجمع نتيجة الخادم مع إيصال FCM المحلي للاختبار نفسه. إذن notification/channel وقيود البطارية تُعرض منفصلة؛ لا عبارة «التنبيهات تعمل» بناء على permission وحده.
- `provider accepted` لا يثبت وصول جهاز. وصول callback لا يثبت عرض الستارة/سماع صوت. displayed لا يثبت قراءة رسالة. لا HTTP خلفي بتوكن جلسة منسوخ، ولا كتابة message receipt ACK من FCM. الإيصال المحلي مرتبط بالحساب والاختبار وله حد7أيام؛ logout/purge يمنع إظهاره في حساب آخر.

## 10. التحقق وبوابات التنفيذ

| الشريحة | أقل إثبات سلوكي مطلوب قبل الدمج |
|---|---|
| C16 | بحث عربي/إنجليزي من تاريخ أبعد من نافذة500، POST+CSRF read-only retry ولا q في URL/log/outbox، pages/UTF-8، media_view مقابل download، لا staged/DMS bypass، عضوية جديدة لا ترى القديم، EXPLAIN معزول وحدود القياس |
| C17 | مستخدمان وتفضيلات منفصلة، مدير يقرأ membership لكنه يُرفض ORM/service لتفضيل غيره، لا related leak، scoped batch واحد، GET defaults لا ينشئ صفًا، سباق أول POST/CAS للحالة الغائبة باتصالين مستقلين، restart/rejoin، expiry/forever/revision/retry، mute يتغير قبل dispatch، archive لا يمس unread/receipts، v87 rooms/snapshot محفوظ |
| C18 | اتصالان PostgreSQL مستقلان A→B/B→A يعيدان pair واحدًا، revoked/foreign/portal/self/room quota، legacy لا يتغير، replay بعد سحب حق يرفض؛ حارس الطرفين يشمل membership.create الإداري أيضًا وليس is_group=False وحده |
| C19 | directory pages ثابتة/foreign و49+creator/50+رفض، batch واحدة بها هدف ممنوع rollback كامل، فعالية admin/last-admin، audit epoch وroom_admin بلا قراءة محتوى، union cursor locks |
| C32 | UUID/digest/revision مع اتصالين حقيقيين، save شخصي وسحب حق، reaction whitelist/counts، mention idempotence مع old/new send وmedia/reply/DMS، تواريخ إيصال لا تتغير، لا endpoint تعديل تاريخ |
| C05 | payload HTTP none خال من النص والاسم، sender بلا مقتطف، full opt-in فقط، تغيير الوضع أثناء retry، تبديل حساب/token، bootstrap v87 الفعلي يقبل top-level version |
| C06 | rate/replay وتبديل الحساب/current installation، permission denied callback يسجل received لا displayed، notify failure/restart/dedupe، sent لا يتحول إلى device/read، لا أثر في جداول الرسائل/المهام |

لا حمل أو اختبار ORM على بيئة تنتظر موافقة المالك. الاختبارات تستخدم مصدرًا مجمدًا وقاعدة اصطناعية معزولة فقط؛ رفض Docker/الشبكة ليس إذن التفاف. fixtures النقل أو الترجمة لا تُسمى فحص قاعدة بيانات أو هاتف.

ترتيب الشرائح المقترح بعد G2 مستقل: C05/C06 مع root FCM → C17 → C18/C19 → C16 → saved/reactions ثم mentions. كل API يعلن نسخته بعد إكماله فقط. القائد يملك السجل المشترك وAndroid/FCM؛ عامل الخلفية يملك موديلات وخدمة/controllers/migrations/tests بعد GO محدد، ولا APK جزئي أو نشر.

### نقطة تجميد المصدر الداخلية — 2026-10-17

- مصدر C05/C06/C17/C18/C19/C16 واختبارات ORM/HTTP/probes المستقلة مكتوب، لكنه **ليس قبول تشغيل**. C32 لم يبدأ بأمر القائد؛ لا `social_contract_version:1` منشور في bootstrap قبل إكمال بقية العقد وقبوله. لا QA/LIVE أو APK جزئي.
- C16 يستخدم `simple` lexical search عربي/إنجليزي، وليس fuzzy أو تصحيحًا إملائيًا أو stemming عربيًا. أسماء الملفات تُجزّأ أيضًا عند النقطة/الشرطة/الشرطة السفلية في الفهرس والاستعلام نفسه؛ لا أصل ملف أو DMS bypass. كل فرع بحث يجلب آخر31 ID فقط ثم union محدود بحد أقصى62 مرشحًا قبل نتيجة30/128KiB؛ وجود الفهرس ليس ادعاء سعة أو زمن استجابة دون تشغيل EXPLAIN/قياس معزول.
- حالات C16 المكتوبة: تاريخ أقدم من501 رسالة، البحث العربي/الإنجليزي، عدم تكرار اتحاد النص/اسم الملف، عزل الشركة/حقبة العضوية، سحب chat/media rights، view بلا download، staged غير مرئي، تصغير صفحات UTF-8 بلا فقد، عدم كتابة إيصالات، معاملات SQL مقيدة، حدود/types صارمة، وجود الفهارس وEXPLAIN تخطيط فقط، وHTTP POST+CSRF/no-store بلا q في URL. لم تُشغّل ORM/HTTP أو سباقات PostgreSQL بعد.
- ترجمة Python للملفات المتأثرة و`git diff --check` ناجحتان. pure contracts الحالية109/110: الفشل الوحيد في حارس Android الحرفي `test_client_preserves_a_verified_route_on_same_account_recheck` الذي يفترض نص تنفيذ BChatPushState السابق؛ أُبلغ مالكه، ولا يُسمى الاختبار ناجحًا أو يُضعف من عامل الخلفية. بقية اختبارات المصدر لا تعوض إثبات تشغيل قاعدة البيانات.
- تصحيح R-BE-01 اللاحق ضمن المصدر: مسبار social أصبح **5 phases**. المرحلة الإضافية `diagnostic_distinct_devices_daily_quota` تضع9 اختبارات اصطناعية قديمة أكثر من دقيقة، وتؤسس snapshot للاتصالين عند9 قبل القفل، ثم تطلب UUID مختلفًا من جهازين مختلفين: المتوقع نجاح واحد و429 واحد، `diagnostic_events=10` و`diagnostic_idempotent_events=1` و`daily_quota_winners=1`. كل phase يثبت PIDين مستقلين في بدايته؛ لم يُشغّل المسبار بعد. اختبار ORM إضافي يحسب own uncommitted عبر جهازين. ادعاء تجاوز membership.create لحد100 سُحب لأن حارس كل صف موجود؛ أضيف اختبار99+إضافتين/rollback ثم100/رفض101 دون إعادة هيكلة المصدر.
- قبل العمل في attempt0 لكل اتصال في مسباري social وpermission ينفّذ `SHOW transaction_isolation` ويرفض غير `repeatable read`، ويثبت PID الابتدائي قبل barrier. تعاد `isolation` و`initial_backend_pid` و`attempts` في نتيجة كل دور/اتصال؛ العدد العام أو نجاح retry ليس بديلًا عن إثبات عزل واتصالين مستقلين في المرحلة ذاتها.
