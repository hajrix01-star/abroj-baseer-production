# BCH-DEV-20261017 — برنامج تطوير بشات الموحد

## العقد والنية
- تفويض المالك: تنفيذ نتائج التدقيق F01–F40 وإضافة الشكل D01–D08، مع نتيجة نهائية واحدة واختبارات، لا APK جزئي بعد كل حزمة.
- المصدر الأساس: main `5e061ac97eaf2e6a5cba7019895ae383f1216d49`؛ المنتج v87 من `9a3abda312b739f62fba62c284b1c8d206f454d7`. الفرع `codex/bchat-unified-maturity-20261017` في نسخة عمل قائمة نظيفة. لا تعديل root المتسخ أو artifact v87.
- الدليل السابق: output/bchat-development-audit-20261017/REPORT.html، وfindings.json وimplementation-plan.json. نسخة خطة العمل المتتبعة: docs/bchat/development-program.json.
- خريطة BCH-NMU-2 باقية: Android/SQLite/ملفات خاصة؛ جلسة WebView موثقة؛ رفع Android أصلي بتفويض محدود؛ خدمة Odoo مرجع الحقوق والأرقام؛ PostgreSQL/filestore؛ FCM للتنبيه لا لإثبات القراءة. لا رسم جديد أو إعادة اكتشاف.
- الهدف: موثوقية تخزين وحالة، إرسال سلس، بحث وتنظيم، تصميم وأصوات واضحة، وتشغيل يمكن قياسه وصيانته لسنوات. لا ادعاء شهادة سنوات أو كل طرازات الهاتف.
- التعليمات: لا مصدر مباشرة إلى main؛ PR وفحوص ناجحة، نشر QA محمي عند وجود مرشح؛ لا LIVE أو بيانات تشغيلية أو حسابات جديدة ضمن البناء.
- العرض النهائي: مرشح واحد مجمع، بنفس هوية التوقيع، واختبارات قبول واضحة. الحزم داخلية لتنظيم الملكية والتحقق وليست تسليمات للمستخدم.

## بوابات البرنامج
| البوابة | الحالة | المالك | الدليل قبل الانتقال |
|---|---|---|---|
| G0 عقد ونطاق | معتمدة مستقلاً | قائد البناء | DEV005، خطة الأربعين ومعيار النتيجة الواحدة |
| G1 السعة | معتمدة حدودًا، لا قياسًا | مهندس السعة | DEV005/014، حدود محافظة وقياس معزول دون أرقام مالك مختلقة |
| G2 العقود | معتمدة للشرائح المسجلة فقط | المعمارية والخدمة | C01/02/03/04/07/08/10/27 وresolve وBCH-DEV-SOCIAL-1؛ لا صلاحية لاختراع API خارج عقودها |
| G3 التقنية | معتمدة مستقلاً | المعمارية والجودة | DEV005، Java/Views/Odoo/SQLite والتبعيات الحالية؛ لا مكتبة منتج جديدة |
| G4 تصميم | معتمدة للأساسات فقط | التصميم | Ui/Palette/Appearance؛ لا قبول Activity أو D04–D06 ضمن الأساسات |
| G5 رحلة | غير مبدوءة | الجودة | اختبارات سلوكية لا حراس نص فقط |
| G6 سعة مقاسة | غير مبدوءة | السعة | قياس معزول مبرر للحجم المعتمد؛ لا حمل QA مشترك |
| G7 دمج | غير مبدوءة | قائد البناء | الربط بين كل بند وكوده واختباره |
| G8 مرشح نهائي | غير مبدوءة | التسليم المستقل | APK مثبت الهوية مع نتائج وحدود وقائمة اختبار هاتف |

لا تُعتمد البوابات ذاتيًا. كل شريحة لاحقة تمس API/schema/دلالة/أمن تعيد G2 بتصميمها المحدد قبل كودها؛ لا تمنح موافقة البرنامج العامة إذنًا باختراع سياسة أعمال أو مسح بيانات.

## G1 — ملف السعة والقياس
- الفعلي المعلوم: مالك يستخدم هاتفًا واحدًا، قاعدة QA صغيرة (5 غرف و37 رسالة و13 وسيطًا وقت التدقيق). لا تعداد مستخدمين متزامنين مثبت.
- حدود المنتج الحالية محفوظة حتى تبرير تغييرها: 50 عضوًا/مجموعة،100غرفة/مستخدم؛ تاريخ30/صفحة وسقفJSON128KiB؛ نافذة500رسالة وكاش10000/حساب و64MiB؛ صور5MiB وملفات/صوت10MiB؛ انتظار20عنصرًا و50MiB.
- قبل اختبار حمل جديد: الفرق، الخطر غير المغطى، وحجم استخدام المالك. بيانات اصطناعية في مجلد/قاعدة معزولة فقط. لا إنتاج أو QA مشترك.
- السلاسة: القياس على الهاتف/المحاكي شرط لقبولها؛ في غيابه نماذج JVM/HTTP وlint ترجمة فقط وتبقى FPS/RAM/بطارية غير مقاسة.
- لا احتفاظ مدمر تلقائي. نضيف سياسات آمنة قابلة للتقرير والمراجعة؛ مدة حذف سجل أعمال أو RPO/RTO تحتاج قرارًا معتمدًا عند الأثر، ولا نستنتجها من «كل شيء».

## G2 — سلطة البيانات والتوافق
- حقوق الشركات والعضوية وحقبتها عند كل وصول مصدرها Odoo، وليس كاش الهاتف أو payload Push.
- إنشاء رسالة/طلب بنفس UUID يُتصالح ولا يتكرر. لا استدلال على ربط صورة بتشابه اسم أو توقيت.
- الحساب المالي وDecimal والتقريب في الخلفية؛ تطبيق هذا البرنامج لا يغيّر سعرًا أو قيدًا أو دورة فاتورة. تصنيف المستند وربطه وأصله يبقيان كما هما.
- العربية والإنجليزية وRTL/LTR، والأرقام0–9، وبيانات إصدار من البناء. لا توسيع أمان للشاشة أو صور الأشخاص.
- مستقبل D04: sent حفظ بالخادم؛ delivered جلب موثق للتطبيق لا مجرد FCM؛ read ظهور فقاعة في شاشة نشطة. التوسعة تحتاج عقد مزامنة وACK مصادق وصفحات وحدود، لا استخراج كوكيز أو اعتماد حضور التنبيه.
- أي fields/API جديدة تضيف اختبارات عزل وأهلية وتوافق عملاء v87، ولا حذف أو إعادة كتابة للرسائل السابقة.

## الشريحة الأولى C01 — احتواء أعطال المرفقات F01/F02
- الملكية: BChatConnectedMediaStore واختباراته؛ لا تعديل Activity أو الرفع أو metadata الخادمية في هذه الشريحة.
- التصنيف: CONTROLLED، تقوية تخزين محلي ضمن العقد القائم، لا schema خادم أو صلاحية أو مكتبة.
- السبب المثبت: enumeration يقرأ كلJSONقبل تصفية الغرفة؛ فشل عنصر يفشل القائمة كلها. الكتابةAtomicFileوالقراءةFileInputStream؛ .bakقد يُتجاهل أو يحذف، و.partلا يدخل الكوتا/التنظيف الكامل.
- الإصلاح: استعادةAtomicFileقبل اعتبار سجل تالف؛ فهرسة أسماء JSON/.bak canonical UUID ضمن حساب موثق؛ احتواء الفشل لكل عنصر وتقديم قائمة مشاكل محددة بلا محتوى خاص، مع إبقاء البايتات والـUUID. بقية الغرف تعمل.
- لا تجاهل صامت: API تشخيص محلي محدود يسرد UUID ونوع المشكلة والسياق الموثوق إن أمكن؛ لا حذف الأصل أو توليد رسالة/UUID بديل بسبب فساد محلي.
- الكوتا تحسب مساحة الملفات الخاصة الفعلية بما فيها .part والأصل اليتيم، وتتجنب احتساب نسخ metadata المؤقتة كطلبات جديدة. حد عدد الطلبات والكوتا يبقيان قائمين.
- التنظيف يزيل .part غير النشط القديم فقط بعد حد معلن (24 ساعة)، ولا يمس عملية نسخ نشطة؛ الأصول .bin اليتيمة تبقى للمراجعة ولا تحذف بصمت. purge حقوق قائم يبقى fail-closed ولا يمنح الملف الفاسد حق العرض.
- قفل موحد/ترتيب ثابت يحميAtomicFileمنقراءة أثناء كتابة، دون حمل القفل أثناءSAFcopyأوHTTP، ولا عكسSTAGE_LOCK/thisيسببdeadlock.
- حالات قبول: تلفJSONفيAثمpending/sendفيB؛ baseمفقودمعbakسليم؛ رفضJSONأكبر24KiB؛ قتلنسخ ثمquota/cleanup؛ملف.binناقص؛تزامنstage/scan؛فصلالحساب/العضوية/الشركة؛لا تكرار ولاحذفملفسليم.
- التراجع: كود فقط دون تغيير تنسيق JSON أو أسماءUUIDأوالبايتات؛ لا نقل تلقائي مدمر إلى quarantine يتعذر على الإصدار السابق قراءته.

## G3 — المسار المباشر
- لا Kotlin/Compose/Redis/خدمات مصغرة أو ORM جديد للتجميل. إعادة استخدام المنصة الحالية وRecyclerView وSQLite وAtomicFile.
- لا تثبيت مكتبات أو تنزيل قوالب. Gradle8.11.1 وSDK35 المثبتان للبناء الحالي؛ ترقيةAPI36فيC31شريحة منفصلة بتوافقها قبل مرشح التوزيع.
- أوامر الإثبات: اختبار سلوكي JVM/Android المناسب، Gradle compile وlint، الحارس التراكمي Source integrity وBChat cumulative contracts عبر CI، ثم Odoo اختبارات المسارات المتغيرة بقاعدة معزولة.
- لا تعاد الفحوص غير المتأثرة. الثيم والألوان لا تستدعي حملًا للخادم؛ الصلاحيات/الترحيل تستدعي فحصها الحقيقي.

## G4/C12 — أساسات التصميم المعتمدة
اعتماد مستقل من حارس البوابات: GO للأساسات فقط. لا يشمل هذا دلالات التسليم أو الأصوات/الستارة أو قبول الهاتف.

| Before | After | Why |
|---|---|---|
| ثوابت ألوان فاتحة | موارد دلالية day/night من Context | لا حالة عامة متغيرة أو كسر نافذة أخرى |
| نص محادثة ثابت | 14/16/18sp وارتفاع متناسب | يحترم خط النظام دون تضاعف التكبير |
| substring للأحرف البديلة | grapheme آمن وبديل للاسم الفارغ | لا قطع للتشكيل أو ZWJ أو علم أو لون البشرة |
| صح نصي يلوّن الوقت | رمز متجهي منفصل ووصف وصول | الوقت محايد والدلالة ليست اللون وحده |
| قياس من الشاشة كاملة | قياس من الحاوية المتاحة | نوافذ متعددة وجوال/لوحي دون قص |

- ChatAppearance تفضيلات جهاز فقط: system/light/dark وحجم المحادثة؛ يضبط uiMode للسياق وTheme معًا. لا أسماء أو محتوى في تفضيلات المظهر.
- Ui ومكونات صغيرة هي مصدر tokens/text/buttons/receipt/initials؛ Android Views والـTheme الحاليان، بلا مكتبة أو حركة زخرفية.
- الشعار الحقيقي والهوية وجهتا الفقاعات محفوظة؛ 48dp للمسّ، نصوص عربية/إنجليزية وأرقام0–9. تعريب UX وفق ux-araby بلا إطالة.
- Insets من padding أساسي ثابت، لا تراكم؛ الدمج يُختبر مع غرفة وسلة ومسودة وUUID معلق عند تبديل المظهر. لا اعتماد جهاز قبل تنفيذه.

## سجل العمليات، إضافة فقط
| المعرف | النية والعمل | النتيجة والدليل | الأثر والتراجع |
|---|---|---|---|
| DEV-001 | قراءة خطة التدقيق ومراجع ألفا وحالة المصدر والأثر | جرى التحقق من تنفيذ الصورة المغلق ومن مراجعة التسليم الحالية، مع الحفاظ على root المتسخ | قراءة فقط |
| DEV-002 | جلبmainثم إنشاء فرع مستقل في نسخة عمل قائمة نظيفة | fetch حدّثofficial/mainإلى5e061ac9؛ أولswitchرُفض بسببsandboxثم نجح بإذنtoolمصعد | لم يتغيرmainأوv87؛ الفرعقابلللمراجعة |
| DEV-003 | تثبيت عقد النتيجة الواحدة وربط الأربعين بالبرنامج | هذا السجل وdevelopment-program.json؛G0–G3قيدمراجعةمستقلة | لا كودمنتجبعد |
| DEV-004 | تصحيح عقد التتبع بعد مراجعة حارس البوابات | C33 يشترط المرشح الموحد وجميع C00–C32؛ أزيلت دورية C31؛ C32 ضمن التنفيذ والمهارة لم تعد تخطيطًا فقط | تصحيح توثيق فقط، لا APK جزئي |
| DEV-005 | اعتماد مستقل G0/G1/G2-C01/G3 | حارس البوابات أعطى GO لبدء C01 بعد تصحيح التتبع؛ لا اعتماد لبقية عقود API/schema أو APK | أُسند تنفيذ المخزن واختباراته لعامل مستقل، بلا Activity أو backend |
| DEV-006 | نية ضبط عقد C03/C04 | عقد الخلفية أدناه قيد مراجعة مستقلة قبل الكود؛ حدود القراءة/التنزيل وتوافق v87 معلنة | لا تغييرات تشغيلية |
| DEV-007 | اعتماد مستقل G2-C03/C04 ثم بدء تنفيذ | حارس البوابات أعطى GO بعد عقد الحقوق المحافظ والإيصالات وFCM؛ عامل الخلفية يملك ملفات Odoo واختباراتها، والقائد يملك Android dedupe | لا QA/LIVE أو إصدار جزئي |
| DEV-008 | نية Android منع تكرار التنبيه | سجل خاص محدود512 حدثًا/7أيام، account+kind+event، بلا نص أو توكن؛ التسجيل بعد notify مع onlyAlertOnce وtag فريد؛ اختبارات JVM للمنطق الفعلي | التراجع كود فقط، وتفضيلات قناة المستخدم لا تتغير |
| DEV-009 | اختبار callback التنبيه الفعلي والسجل | test-notification-presentation.py نجح10حالات؛ المصدرv87فشل حالة التكرار نفسها كما هو متوقع. المحاولة الأولى تعذرت لصلاحيةTemp؛ استُخدم artifacts/test-runtime الخاص بدلها | لا جهاز أو صوت مقاس؛ لا تبديل قناة المستخدم |
| DEV-010 | تسليم عامل C01 واختباراته | 40فحصJVM+isolation ناجحة، baseline5e061ac9أعادIOExceptionالعابرللغرف؛ compileReleaseJavaWithJavacنجح. adaptersAtomicFileقديم/حديث معلنة، وليستAndroidفعليًا | الكود محلي؛ لاAPK. الربط بواجهة التشخيص والحارس والمراجعة ما زال باقيًا |
| DEV-011 | نية G4 وتصميم السلاسة التالي | أُرسل عقد foundationsالثيم/الخط/الأيقونات لحارس مستقل؛ عاملAndroidيعد عقدC02/C07/C08قبل الكود. Ui/resourcesللقائد وActivityللعامل بعد الاعتماد | لا تداخل ملكية أو نشر جزئي |
| DEV-012 | نية فحص ORM معزول | الفرق: حقوق/ترحيل/cron؛ خطرSQL/ORMلايغطيهJVMأوfixtures؛ حجم المالك المثبت هاتف واحد، لا حمل جديد. نعيد استخدامComposeالمعزول إن كانمتاحًا | Dockerreadرفضsandbox، أُعيدفحصالمتاحبالتصعيد؛ لاQA/LIVE أو قاعدة تشغيلية |
| DEV-013 | G4 مستقل ثم تنفيذ foundations | UiPaletteمواردcontext/day-night وChatAppearance وAvatarInitials ورمزحالةمنفصل. اختبارالتباينكشف4.446للميتاداتاعلىالصادر؛صُححالمتغيرالدلاليوأعيدالاختبارالمتأثرفقط:13grapheme+18contrastPASS؛GradlecompilePASS | لا تفعيلثيمشاشةكاملةأوقبولجهازبعد؛ترجمةالأولىتعذرتsandboxnativeDLLثم نجحتبالتصعيد |
| DEV-014 | G2 مستقل C02/C07/C08 | GOبشروطcapacityTX/editorrevision/room/body/reply/retrydurable/purgefence؛عاملAndroidينفذActivity/Outbox/repository؛قائدUi/resources | لا قبولمختلطوسائطحتىC09 |
| DEV-015 | مراجعة C03/C04 مستقلة أوقفت الدمج | وجدالحارساحتمالانقلابأقفالتلميحاتحقوقبينمعاملتين؛العاملأضافحجزاتحادالمستلمينقبلأولنشرومسبارPostgreSQLحقيقيقيدالتشغيل | لا دمجبلاreview+ORM؛110purecontractsلايثبتسباقDB |
| DEV-016 | نية واختبار محاكي منفصل | الفرقlifecycle/SQLite/UIfont؛لايغطيهاJVM؛هاتفالمالكواحد. AVDجديدداخلartifacts،API35headlessport5580،WHPXoperationalوboot_completed=1. بدءsandboxلميبقَحيًا؛بدءمباشرمصعدنجح | لاAPKعلىجوالالمالك؛لاإعداداتأوبياناتمحاكيقديمة |
| DEV-017 | بديل ORM معزول | Dockerالمحليلايردولانعيدتشغيله؛فحصالخادمقراءةفقطأثبت4.3GiBavailable. أُعدrunnerمحدد512MiBpostgres+1536MiBodoo/CPUمحدودوشبكةnoneبلاportsأومصادرQA/LIVE | اختبارمصدرمستقللاترقيةQA،والنتيجةلمتُنفذبعد |
| DEV-018 | قيد أمني لنسخ مصدر الاختبار | أوقفتAutoReviewمحاولةSCPقبلالتنفيذ لغيابإذنوجهةصريح؛لاsourceنُقل. مجلد/tmpالمؤقتفارغ. سُئلالمالكعن100.124.140.114بالاسم،ونكملالمحليدونالتفاف | ORMومسبارPostgresبانتظارالإذنأوبيئةمحليةمتاحة |
| DEV-019 | قياس Android فعلي للمكونات | standaloneappearance35:36حالةAR/EN،day/night،font1/1.3/2،body14/16/18؛656assertionsPASSوصورمحفوظة. فحصالصوركشفخلفيةenabledرمادية؛فشلتassertionثمصححmutateقبلتركيبRipple،وحالاتenabled/pressed/disabled/re-enableنجحت | ليسشاشةActivityمتكاملةولاقياسFPSأوصوت؛علامةالوقتneutral |
| DEV-020 | SQLiteفعلي للمهاجرات والطابور | العاملشغّلstandaloneoutboxtestعلىemulator5580:130assertionsPASS؛السجلartifacts/test-results/C02-C08-SQLite-android35.log. تكاملActivityوالسلةباقيان | لامتدخلبةجوالالمالكأوبقاعدةتشغيلية |
| DEV-021 | مراجعة أقفال ثانية وقرار C27/resolve | زالمانعالمصدرعندحجزunionفيكلالناشراتالمحددة،لكنسباقاتDBغيرمنفذة. GOلأداةC27وbatchresolveبالحدودالمسجلة | لااعتمادتزامنأوتسليممنsource-reviewوحده |
| DEV-022 | بناء قابل للتتبع وحارس تراكمي | preflightيرفضwrongcommitوdirtysourceقبلالتوقيع؛PowerShellsyntaxPASS؛المسارانالموثقانموجودانفعليًابفحصمصعد(قراءةsandboxأظهرتfalse). سجلتinvariantsوCIJVMالواقعي؛مصدرالموديول4.15محليًا | لاAPKمنتجأومفتاحجديد،ولاادعاءنسخةمفتاحاحتياطية |
| DEV-023 | C10 اعتماد foundations وتصحيح حد المسودة | مراجعة مستقلة GO للمسار الضيق وإعادة استخدام decoder؛ تصحيح G2-C10: الحد القائم 1400px لا2048، و8MiB/tile. AudioFocusLease بمالك واحد وport خارجي صغير لاختبار grant/loss دون ادعاء مكالمة فعلية | نقل AudioPlayback لنفس lease؛ تكامل Activity لم يبدأ لهذه الشريحة، ولا cache-retention مكتمل |
| DEV-024 | نية اختبار C10 على Android معزول | الفرق EXIF/المقاسات وإلغاء callback وملكية الصوت؛ لا يغطيها JVM السابق. نفس AVD5580/هاتف مالك واحد. standalone package بمصادر decoder الفعلية وcompile-adapters ترفض المسار offline؛ نتائج AudioManager الخارجية فقط محقونة صراحة | لا بيانات مستخدم، لا شبكة أو قاعدة تشغيلية، لا ادعاء مصادقة أو سماعات OEM من هذا الاختبار |
| DEV-025 | G2 مستقل اجتماعي وتنبيهات | GO لعقد BCH-DEV-SOCIAL-1 بعد فصل model التفضيلات الخاص وبحث POST بلا q فيURL وحقوق reaction/saved. يلزم حارس direct فيmembership.create وGETdefault بلاwrite وCAS عندغيابصف | عامل الخلفية بدأ C05/C06 من العقد؛ التنفيذ/ORM ليسا مثبتين بالموافقة |
| DEV-026 | C10 مراجعة كشفت سباقًا ثم تصحيح | NO-GO أولي: prepared قديم يطلبfocus ويقطع تسجيلًا أحدث؛ reserve صار عند نقرة المستخدم وprepared لا يحجز نفسه. أُضيف AudioPlayback الحقيقي مع DelayedPlayer لترتيب callback؛ PASS140 ثم GO تصحيح الصوت مستقل | تصحيح DEV024: adapter الصوت يقبل fixture خاصًا فقط، لا إنتاج/auth. الأجزاء الأصلية الأخرى لا تدّعي codec/OEM |
| DEV-027 | C10 viewer tiles فعلي | وُصل decoder بعارض صغير بمصفوفة EXIF ثم zoom/rotate، tile واحدة1400/8MiB، لا إعادة كتابة أصل. Android activity اختبار مستقل:8EXIF وcurrent-rights draw fence مرتين؛ PASS182 كل الاختبارات معًا | source review للtiles وActivity integration باقيان؛ لا قبول F09/cache-retention أو FPS |
| DEV-028 | C01/C03/C12 checkpoint العامل | source settings diagnostics والثيم والخط وحقوق الوسائط وInsets وrestore-barrier؛185Androidchecks بمافيها PermissionSet و403failclosed عبر adapters معلنة. الترجمة النهائية تنتظر آخر widthlistener | لا Activity lifecycle/screens قبول؛ غير مؤكد لم يُحذف عندtimeout؛ لا نسخة منتج منشورة |
| DEV-029 | مراجعة C01/C03/C12 وC10 | Activity checkpoint compile النهائي PASS وGOمصدر محدود. reviewer أوقفtiles بسببسقوطحارسالأصل عندdetach؛ فُصل originalAllowedعنطلباتtiles،واختبارdetach→revoke→reattachنجح182ثمGOللتصحيح | workerيبدأwireC10وعقدC07المالي،لاحذفintentأومصدرجزئيمنشور |
| DEV-030 | C05/C06 تكامل قيد المراجعة | الخادم أضاف preferences/selftest معHTTP-payload ORM اختبارات غيرمشغلة؛ Androidreceivedقبلإذنالعرض وdisplayedبعدnotify وledger32/7days وقناعnone/sender/full. callback/ledger23PASS معAPI/PushStatefixtures معلنة | القائد يراجع CAS/تبديلالحساب؛ لا settingshealth مكتملة ولا وصولFCMفعلي مثبت |
| DEV-031 | تحديث الحراس للشكل غير المتزامن | الفحص الجامع كشف حراس alias/single-pending قديمة وقراءةcp1252؛ صُححتUTF-8 وفُرضتحدودالطابور وثلاثيةالوسائط وserial reconciliation بدلحذفالشروط. source-package/permissions/media21/entry14/localization20 PASS؛ orders7 وverified-read11 وlogin3 وjourney11 PASS فيsnapshotفحصها | يتعين فحص آخر فرقC07/PushState لاحقًا؛ لاندعيCI أو قبول جهاز بهذهالحراس |
| DEV-032 | G2 Android notification routing | المراجع أعطىNO-GO للمصدرالأول وGO للتصحيح المحدود: stateRAMواحدة،finalmatches+privacy+notify/cancelAllبقفلترتيبقصير،لاdiskتحته؛RegistrationticketقبلHTTP وserialsnapshots وnoneintentيقيدفورًا ويُبطلGETقديم | received=callback مطابق،displayed=notifyreturned فقط؛لاmessageACKأوHTTPخلفي جديد |
| DEV-033 | تنفيذ G2 routing وإثبات ضيق | BChatPushState الفعلي اختُبر89check عبرadaptersمعلنة،منهاcommitfalseمعmemorychanged/diskold،reloadnone،logout-vs-notify،oldresponse/snapshotdifferentepoch. أضيفepochلشرطsnapshotكيلايعتمدجيلجديدمنcommitقديم. callback/ledger23PASS | ليسAndroidSharedPrefs/FCMdelivery؛ فشلdiskلايُعلنlogoutدائمًا أوfullمحفوظًا؛coldpreviewnoneحتىردخادمحديث |
| DEV-034 | C10 wire وC07 عقد | عاملActivityربطEXIF/detailsourceوcoordinatorواحدوحجزقبلفetch/prepare؛compilePASS و196Androidchecks بمافيها11inline-productionprobe بمحاكاةplayer/transportمعلنة. حارسG2الماليGO لعقدasync-intent-persistenceبلاcalculator/API/schemaتغيير | C07الماليبدأبعدالموافقة؛screens/lifecycle/OEMaudio/FPSلمتُقبل؛لاإصدارمنتج |
| DEV-035 | تجميد checkpoint ومراجعة مستقلة | C07 بلغ253 assertions بمكيفات UI/HTTP معلنة؛ مراجعة مستقلة أوقفت حفظ order-policy الذي يلغي generation نفسه. الخلفية أوقفت quota يومية بلقطة RR قديمة عبر جهازين؛ صُححت bounded-union لقراءة حديثة وكتابات المعاملة وحصلت GO مصدر فقط. ملاحظة batch-capacity سُحبت لأن guard لكل صف موجود؛ regression أضيف دون تغيير السياسة | لا ORM/سباقات منفذة بعد؛ C09/C32 متوقفان حتى checkpoint معزول؛ لا إصدار جزئي |
| DEV-036 | توجيه الاختبار المعزول | نقل المصدر إلى خادم100.124.140.114 لم يُنفذ بعد رفض الإذن وبقي سؤال المالك بلا إجابة. البديل المراجع GO: CI المعتاد على المصدر المجمد مع PostgreSQL/Odoo مثبتين بالـdigest، بيانات اصطناعية، لا secrets أو mounts تشغيلية أو ports منشورة. الفرق الصلاحيات/التزامن؛ لا يغطيه JVM؛ الاستخدام المعروف هاتف مالك واحد لا حمل إنتاجي | يختار كل اختبارات core مع HR بدل tag maturity وحده، ثم يستدعي5 permission+5 social phases صراحة؛ يفشل عند skip أو نقص الدليل. Procurement والرحلات الفعلية للجهاز لا تُقبل بهذا الفحص |
| DEV-037 | تثبيت توجيه التنبيهات | تصحيح DEV033: آخر BChatPushState behavior160 PASS وcallback23 PASS بمكيفات معلنة؛ مراجعة المصدر GO محدودة بعد serial registration وMAIN recheck وpending-none ثابت عبر تبدل token وإعادة التشغيل. حارس المصدر القديم حُدث إلى RAM invariant وتغطية behavioral CI بدل literal SharedPreferences قديم | لا ادعاء Android preferences/OEM/FCM فعلي؛ إعدادات العميل لم تكتمل بعد |
| DEV-038 | تصحيح R-AND-C07 وقفل نقطة المصدر | سحب order-rights/fence أصبح قبل الحفظserial غير الملغى ذاتيًا؛ readiness يفصل policy/orderpolicy ويُحرس latest-write. BEFORE فشلassertion3 وAFTER32PASS بـrepository/MAIN فعليين وprefs/UI/loss-fakes معلنة؛ Java compile15s وGO مستقل محدود. release_guard--all PASS بعد تحديث حراسيorders/403 لمرحلةDurable مع إبقاء persist-before-dispatch؛ backend pure118 PASS | لا financialHTTP/Activity كاملة/processkill. CI runner bash-n PASS؛ YAML المحلي لم يُفحص لغيابPyYAML، ولا ندعيORM قبل سجلCI |
| DEV-039 | قبول مشروط لتشغيل CI | المراجع أعطىGO للتشغيل عبرPR المعتاد بشرط pg_isready عبرTCP127.0.0.1:5432 لاsocketمرحلةinit؛ طُبق. وصُحح تصنيف اختباراتgrantالموروثة إلىORM بدلBaseCase مع assertionموجه. قبولSourceللrunner/gate فقط | لا نقل للخادم ذي الإذن المعلق ولا تشغيل قواعده؛ PRداخليلاAPKجزئيولادمجأونشر |
| DEV-040 | PR413 وتشخيص أول CI | المصدر1327d002 رُفع فيdraftPR413 وأُرفق بالخيط. CI39059459651 توقف قبلORM لأن digestPGمنقولناقصحرفًا؛ استُبدل بالـpinالموجودبـworkflowsالمشروع وأضيفحارس64hex/التطابق وpreparationlog. SourceCI توقف لبندtest-bchat-user-permissionsغيرالمسجل؛أضيفبـsuiteAndroidلا إسقاطالحارس. changed_guard يغطيكلالفرقبعدالتصحيح | لاORMنفذولاphaseمرّفيالمحاولةالأولى؛app/QA/LIVEغيرمتأثرة |
| DEV-041 | ترجمة Firebase الحقيقية | استُخدمgoogle-services.jsonالقائمفيv87المحلي داخل المسارignored دونعرضأورفع؛ compileReleaseJavaWithJavac -PbchatEnablePush=true --offline PASS20s بمافيهFCMclassالحقيقي | ترجمةفقط،لاAPKوتوقيعأوتنبيهخارجيولاادعاءوصولجهاز |

## G2-C03/C04 — عقد الخلفية قبل التنفيذ
- المشرف الفعال = عضوية نشطة+علمadmin+حساب داخلي نشط+شركة الغرفة+chat_view+group_manage. الإنشاء يحتاجcreate/manage؛ لا منح تلقائي. ترقية/خفض/خروج تحت قفل الغرفة. لا نمنع تعطيل موظف لأجل BChat، بل يعلن احتياج استرداد ويمنح room_admin تعيين عضو مؤهل فقط، دون انضمام أو قراءة محتوى.
- الإيصالات المؤهلة تعيد فحص active/internal/company/chat_view/membership epoch. أسباب الاستبعاد داخلية محددة؛ لا تعديل read_at/delivered_at بسبب سحب حق. صفر مؤهلين يبقيsent ولاall([]). read_at من قراءات حقيقية لاوقت مغادرة. إشعار تغيّر الحقوق تلميح بلا محتوى ومحدود الغرف/المستلمين؛ لا مسح تاريخ.
- الوسائط: bchat_media القديم يبقى الرفع، حقان جديدان للمشاهدة والتنزيل بنقل قيم القديم عند الترقية لأول مرة فقط. لا إعادة تهيئة عند إعادة تحديث الموديول. legacy permissions.media مؤشر محافظ (الثلاثة متاحة)، وإضافةmedia_view/media_upload/media_downloadفيversion1لا تكسرمحللv87الذييتجاهلالإضافات.
- الأصل/contentيتطلبdownload، والـthumbnailيتطلبview؛رفعومنحوتثبيتوسيطجديدتتطلبupload+chat_send. العضويةوالشركةوالحقبةمطلوبةدائمًا. عميلv87يبقىمحافظًا؛عميلالبرنامجالجديديفصلbuttons/reads.
- لا ادعاءDRM: عدم منح تنزيل الأصل ليس ضمانًا لمنع تصوير ما يظهر. في المجموعة الجديدة view دونdownloadيعرضالمعاينةالخاصةفقط،ولا يمررالأصلللتطبيقأولعارضخارجي؛تعطيلالتنزيللايسمحبتجاوزفيالمعاينةالكاملة. دعم عرض مستند كامل دون أصل إن لزم يحتاجمسارعرضمحدودموثقأولًا،ولانختلقهفيهذهالشريحة.
- تكاملDMS: كل امتدادقراءةوسيطيمرمننفسhelperrights؛يجردالعاملالمساراتالموجودةويرفضقبولالفصلإنبقيمساربلاالحارس. لاامتدادخارجيغيرمقروءيُقبلبالتخمين.
- FCM: FcmError.detailsنوعUNREGISTEREDيوقفالرمز،404وحدهلايكفي؛429/503ونقلبـRetry-Afterثواني/تاريخوبتراجع+jitterمحدود. لاجسمخطأأوتوكنفيlogs.
- Cronمحدد100مرشحوأميزانيةزمنيةبينالأحداث،وقفلSKIPLOCKEDوالتزاملكلحدثفيcursorمستقل. لاexactly-onceللاتصالالخارجي. Androidيزيلالتكرارالمرئيبـaccount_key+kind+event_idبسجلمحدودوبتنسيقمعروف.
- ملكية الخلفية: user_permissions/group_service/membership/message_receipt/v2_service/media_service/pushوالحقولالإداريةوترحيلواختباراتهذهالشريحة. القائديملكرقمالموديولوguard_registryوالـActivityوخدمةFCM. العامللاينشرولايمسQA/LIVE.
- الاختبارات: صلاحياتإنشاء/آخرمشرف/استرداددونقراءةوسحبحقوقوشركة،إيصالاتصفر/عودة/ثباتتواريخ،مصفوفةحقوقوسائطوعزلوتوافقv87وترحيلثابت،FCMواقعيالشكلومؤقتودفعةبطيئةوعاملين. قاعدةمعزولةومزودمحاكىفقط.

## G2-C02/C07/C08 — مسودة الاستعادة والطابور
- الملكية Android Activity وBChatV2Outbox ومستودع sync صغير واختباراته؛ لا API خادم أو مصادقة/كوكيز جديدة. الترتيب: نموذج ومهاجرة ثم serial repository ثم auth restore ثم queue/local rows.
- SQLitev5 additive من1–4 تحفظUUID/body/reply/ids. draft={body,replyToId}. context={section,companyId,roomId,membershipId,anchorMessageId,offset,taskFilter}. cartIntent={companyId,warehouseId,route,representativeId,optionId,quantityString}. لا أسعار أو مجاميع أو توكنات أو حقوق أو نسخ محتوى فيBundle/SharedPrefs.
- لا إعادة عرض writable إلا بعدv1identity ثمv2bootstrap ثمcompanies/permissions ثمقائمةغرفحالية وتطابقcompany+membership ثمhistoryموثق. replyGETالقائم يعيدأهليته؛إذاحُجبلايتحولصامتًاإلىنصمستقل. offline24h/read-onlyيبقىعلىعقدهالقديم.
- السلة≤100option؛كمياتASCIIخام؛hydrateمنالخادمبعدالحقوقوالشركةوالمخزن/المندوبثمquoteجديدمعrevision/fingerprint. لا إرسال تلقائي أو مجموع محفوظ، ولا UUIDجديدلطلبمعلق.
- serial executor للتخزين، snapshotsimmutable، no wait/join/fsyncعلىUI. callbackfenceaccount+session/view؛storagegenerationمستقللـpurge/revocationحتىلايضيعحفظنفسالحسابمعreauth،ولايرجععنصرمسحوببعدpurge. SharedPrefscommitالحساسبنتيجتهعلىالعاملقبلتمكينoffline؛لااعتبارapplyدليلdurability.
- enqueue+draftconsumeذرّيان،UUIDمرةواحدة،sequenceمنSQLite_idلاتوقيتالحائط. textareaيتفرغبعدcommitفقطإنلميتغيرنصه. رأسواحدللغرفة؛loss/reauthيعيدنفسUUIDوالpayload؛membershipمختلفلاreplay.
- حالاتqueued/sending/uncertain/review/receipt؛v4pendingيهاجرuncertainبنفسبصمته. ACKيثبتmessageIdلنفسUUID/room/membership؛receiptلاPOSTويقرأcanonicalقبلretire. 400/413policy->review،401reauth،403غلقالرحلة،transientوفقOutboxPolicy8محاولاتثمreview. headreviewيوقفdispatchلاالكتابة.
- السعةالمقترحةالمحافظة:20نص/غرفة،100/حساب،2MiBUTF8queued،16KiB/نصو64KiB/draft. الامتلاءيحفظcomposerولاحذفunsentتلقائيًا؛media20/50MiBلايتغير.
- displayedMessagesيبقىserver-onlyللـcursors/ACK؛localrowsUUIDوstableidمنفصللامعرفخادمزائفولاصحdelivered/read. canonicalيستبدلالمحليدونتكرارأوقفزة. C08نصأولًا؛mixedmediaوترتيبالطابورالمشتركشرطC09ولاادعاءقبولهابإنجازالنص.
- القبول:SQLiteفعليعلىAndroidأومكيفJVMمعلنللتنفيذالحقيقي،migrations1–4،killقبل/بعدenqueue/ACK،10نصوص+ردضائع+restartبترتيبوUUIDواحد،revocation/account/reply،resume/rotate/processdeathونفسanchorوسلةبلاquoteقديم. StrictMode/tracesشرطسلاسة؛آخر300msقبلcommitقدتضيععندkillقسريولاادعاءغيرذلك.

## G2-C27 — مسودة مصدر بناء وتوقيع قابل للتكرار
- نفسمفتاحالمعاينةالموجودفيrunbookخارجGit،لاkeyجديدولاطباعةسر. toolيحمّلمسارالمجلدالموثقعندغيابenv،ويفشلإنغابأحدالملفين؛لاsearchHome/history.
- build-unified-previewيتحققcleanHEADوفرعالمصدرومعرفcommitالمتوقعقبلrelease؛مقارنةversionCodeبالـbaseline87أوالأعلىالمعلن،لاحد58القديم. debug/testbuildsالمعزولةلايُدّعىأنهامرشحالتسليم.
- SOURCE_DATE_EPOCHمنcommitينتجrelease-dateوBuildConfigsourcecommit،وملفmanifestجانبيبعدالتوقيعفيartifactsيحويSHA256/package/version/targetSDK/signer/commit/Firebasepresent. لاكلمةمرورأوtoken/configcontent.
- لا حفظنسخةمفتاحمشفرجديدةأورفعسرفيGitHubبدونمكاننسخاحتياطيمعتمدمنالمالك؛نثبتالإجراءوالدليلولاندعيDRناجحًا.

## G2-C02 — استرجاع السلة المستهدف، قيد المراجعة
- المالكbaseer_bchat_procurementفقط،لاschemaأوتعديلحاسبةالموديولالمالي. POST /bchat/api/v2/orders/catalog/resolveبنفسsession/form/CSRF؛api_version2,company_id,warehouse_id,purchase_route,representative_partner_id,option_ids1–100unique،after_option_idاختياري.
- _order_create_scopeثمتحققwarehouse/representativeمنالمصادرالقائمة. قراءةIDsالمطلوبةفقط؛لاdefault_optionsأومسحcatalog. أهليةشركة/active/catalog/UoMبنفس_assert_catalog_optionsالقائم؛المرفوضأيًاسببهضمنmissing_idsعامبلاوصفأجنبي.
- itemsبنفسOrderOption،missing_ids،next_after_option_id؛24عنصر/64KiBكالحالي،100طلب≤5صفحاتIDsمستهدفة. السعرالمعروضمنlast_priceالخادمثمquoteجديدإلزاميقبلsend،لاسلطةمحليةولامجموعمحفوظ.
- contextinvalidيحفظالمسودةللمراجعة؛لاmutationأوإنشاءأوتغييرطلبUUID. v87والـquote/createباقون. اختباراتowner/reader/portal/crosscompany/warehouse/representative/archived/UoM/101/duplicate/invalidIDs/UTF8/changedprice/no-scan.

## G2-C10 — مسودة تقوية العرض والصوت
- المسارالأقصر:إعادةاستخدامImagePreviewsالموجودالذييعالجEXIFوالحجوموالإلغاءوالـImageDecoder28+،بدلBitmapFactoryالمكررالمتجاهلEXIFفيshowFullImage. مدخلكاشمتصلضيقلايقبلإلاcanonicalfileداخلcache/bchat-v2-media-readباسمهالقائم،ويعملخارجmain؛لاauthgrantجديدولانفسرانعكاسالصورةصلاحية.
- الحدالقائمmaxEdge2048وMAX_BITMAP_BYTESوvalidSourceيبقى؛8EXIForientationsوأبعادعريضة/عموديةوصورةتلفةوcancel/OOMتُختبر. callbackعرضالصورةيبقىaccount+membership+viewgeneration؛لاعرضبعدrevocationأوسياقمتغير.
- AudioFocusLeaseمكونplatformصغيرمشتركلثلاثرحلاتinline/voicepreview/recording،لاplayerآخرولاخدمةخلفية. AudioFocusRequest transient/EXCLUSIVEللتسجيل،loss/duck/noisyيوقفأويعلّقولاautoresumeعندgain؛النغمةلاتتجاوزDNDأوإذنالنظام.
- listenergenerationوملكيةmainthread،releaseعلىpause/stop/destroy/failure،registerReceiverNOT_EXPORTED33+،لاREAD_PHONE_STATEأوميكروفونخلفي. عندفشلالfocusلايبدأplay/record؛existingAudioPlaybackيرجعإلىنفسleaseلإزالةالتكراربعدثبوتالاختبار.
- لا حفظpathsأوصوتفيpreferences. الاختبارAndroidمعمكيفسياسةJVMصريحوفشلالطلب/خروجسماعةوتبديلمالكولاإعادةاستئنافتلقائية؛لاادعاءأنالمحاكييثبتكلمكالمةفعليةأوسماعةBluetooth.
