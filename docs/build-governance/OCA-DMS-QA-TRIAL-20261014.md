# تجربة OCA DMS — QA فقط — 2026-10-14

## العقد والحدود (G0–G3 مسودة)

- تفويض المالك: تجربة OCA DMS للعقود والرخص على QA، مع اختبار عزل الشركات والصلاحيات وعدم تكرار الملفات، وإبلاغه بالنتيجة. لا نشر LIVE أو نقل مستندات حقيقية أو نسخ فواتير أو تعديل قيود.
- المصدر المقترح: OCA/dms فرع19 commit `1a3098d1d6bbce6a38d06d9f361db319e7858fa3`، dms19.0.1.1.2، LGPL3 وفقmanifest؛ لا إضافات OCR/AI/توقيع.
- المسار المباشر: اختبار إمكانات الموديول الأصلية أولًا لا بناء بديل. الفشل في منع نسخة منطقية مكررة يُبلغ كقيد مثبت، ولا يُخفى بدعوى أن checksum يمنع السجل الثاني. لا تغيير سياسة الشركات عبر التطبيق إلا بعد عقد منفصل إذا كشف الاختبار ضرورة ذلك.
- الخريطة: مستخدم داخلي مصرح → dms.storage خاص بالشركة → مجلد عقود/رخص → dms.file → تخزين أودو/filestore. لا ربط بمسار رفع الفواتير أو جلب مرفقاته. التخزين العام company=False غير مستخدم في العينات. بوابة مشاركة token/portal والتحميل تحتاج اختبارًا، لا يكفي search فقط.
- G1: تجربة صغيرة بملفين صناعيين لكل شركتين موجودتين، وحساب قارئ/محرر محدود مؤقت؛ حدود الملف 1MiB للعينة، لا مستندات مالك/بيانات حساسة. الاستخدام الفعلي شخصي لعدة شركات، لا حجم إطلاق معلوم؛ لا اختبار حمل أو بيئة جديدة دون سبب. فحص السعة قبل النشر، backup/rollback عبر الغلاف فقط.
- G2: مصدر الحقيقة ملف أصلي واحد لكل عينة؛ SHA256 محلي وبصمة dms/attachment للتحقق. اختبار الملف نفسه باسم جديد وفي مجلد آخر، وتمييز سجل الملف عن bytesfilestore. اختبار شركاتA/B: search/read/write/unlink/create/move/download، وقارئ بلا تعديل، ومن ليس عضوًا. لا صلاحياتadmin كدليل عزل. شروط وصولtoken/portal مقيّدة أو تُعد مانعًا للاستعمال الخاص.
- G3: يعتمد أودو19 الموجود، واجهاتOCA الأصلية والترجمات؛ لا مكتبةواجهة جديدة. python-magic اختياري وفقREADME، يفحص الواقع قبل اعتمادpreview. تثبيت المصدر المجمد فيGit وPR ناجح وQApolicyضيق قبل أيinstall. whitelistQA الحالية لا تقبلdms؛ توسيعدقيق لموديولواحد فقط ومراجعةمستقلة، لا تجاوزالغلاف أو تعديلLIVE.
- G4: إعادةاستعمالواجهةDMS الأصلية، قبولAR/RTL/EN والتفاعل موثق منفصل عن ORM. تعذرالمتصفح لايصبح قبولًا بصريًا.
- G5/G8: فحص تركيب وعينةمصطنعة، مصفوفةصلاحيات وتكرار، backup/hash/upgrade/result.env، حكمتسليممستقل قبلإبلاغالنجاح. لايلزمقبولnativeDMS إذاكشفالاختبارعيبًا؛ تظلنتيجةالتجربةNO-GOللتوسع معالأسباب.

## البوابات

G0/G1/G2/G3: مسودة للمراجع المستقل؛ لا تنزيل تثبيت أو كود تطبيق أو تغييرQA قبلGO.

## دفتر العمليات

1. قراءة skillsالبناء/المعمارية/التنسيق ومراجعها، registryومساراتQA، وتحققcurrentQA/freedisk بقراءةSSHStrictHostKeyChecking. QAعلىf894b892، المتاح2476408832bytes. المصدررئيسي6d0708a5، branchcodex/oca-dms-qa-trial-20261014؛ تغييراتالمستخدمغيرالمتعلقة محفوظة.
2. فحص رسميREADME/manifest/companyrules/checksum عبرGitHubAPI: nativeDMScompanyrulesتسمحsharedcompanyFalse ومخزنخاص، checksumليسبرهانمنعسجلمكرر. نتائجتفصيليةتراجعهاdms_source_audit، مسارالنشرdms_qa_route_audit. لاinstallأوتغييربياناتQAحتىالآن.
3. حارس مستقل dms_trial_gate أجاز G0–G3 للتجربة الصناعية وحدها، لا للتوسع أوLIVE. تدقيق المصدر المستقل كشف autoattachmentrootlookupبسودو بلاcompanyfilter وحذف الأصل عندunlinkattachmentlinked؛ لذلك model_ids=[] وinclude_message_attachments=False وsave_type=file شروطملزمة. checksumلايمنعcontentduplicate؛ نتيجةالسماحبنسخةمنطقيةتسجلNO-GOللتوسعالمشروطبمنعها. تنزيلالمصدرللفحصبعدGO، HEADطابقpin. تجربةCIصغيرةجديدةمبررة: تركيبموديولخارجيجديد/خطرالصلاحياتوالرفعغيرمغطىبفحوصقائمة/الاستخدامشخصيلعدةشركات وعينات4ملفات فقط؛ بلاحملQA.
4. PR320 candidate1ad02ea5: فحصsource38528890440رفضREADMEupstreamفقط: trailing-space فيتعليقRST وخطCredits=======يفهمهGitكconflictmarker. صححتتنسيقREADMEفقطوثبتالفرقفيPROVENANCE؛ كودOCAالتشغيليلميتغير. Odoo38528890538قيدالتشغيل، لاQAinstallحتىالنتيجةوالمراجعة.
5. نتيجةOdoo38528890538 على1ad02ea5: 7اختبارات/1فشل/0أخطاء. ستةنجحت: reading/companysearch، CRUDفيالشركة، قارئومستخدمبلاعضوية، portal/public/tokeninvalid، تنزيلownمسموحوforeignمرفوض، وduplicatecontentمسموحاسممختلفمعphysicalfilestorededup. فشلP1فيtest_cross_company_mutations_denied line87: نقلfileAإلىdirectoryB بمستخدمcompanyAفقطلميرفضAccessError. البحثوالقراءةوالإنشاءوالحذففيالشركةالأخرىمنعتقبلذلك؛ هذامانعوجهةالنقلوليسحكمأنكلمساراتالعزلمكسورة. dms_security_mixin.writeيتحققسجلماقبلالنقلولايفرضوجهةالشركةقبلالتعديل.
6. قرارقائدالبناء: NO-GOقبلQA؛ لمينفذأيinstallأوتعديلrootwrappers/QAconfigأوبياناتخادم؛ QAوLIVEبقيادونتغيير. لاإعادةCIبلاسببجديدولاإضعافassertion. إصلاححارسوجهةالنقلومنعcontentduplicatesعملجديديحتاجطلبالمالكبعدالنتيجة، وتحديثG2/G3ومراجعةمستقلة. READMEformatfixمحليلايصلحP1؛ لاادعاءاجتيازالفحوص. PR320يبقىDraftلمنعاعتبارهبمرشحنشرمقبول.

## ملخص التجربة وحد الدليل

## استثناء المالك للتقييم الخاص (G2/G8 قيد المراجعة)

بعد إبلاغه بمانع النقل، وافق المالك صراحة على QA بملفات وهمية وحسابه وحده، وتأجيل الإصلاح. الاستثناء صالح حتى نهاية التقييم الخاص فقط، وينتهي فور إضافة مستخدم آخر أو مستند حقيقي أو طلب LIVE. ليست موافقة إنتاج ولا ادعاء إصلاحP1؛ يبقى الاختبار الصارم موجودًا كفشل متوقع معلن بدل حذفه. حارس مستقل يراجع global owner-only rules لمخزن/مجلد/ملف/مجموعة DMS، groupownerلـbase.user_admin(2) فقط، لاtokens أوautoattachments. اختبارnativeفيCI يعطلrulesالتجربة ضمنfixturetransaction فقط، والاختبارالخاص الجديديثبت منعmanagerآخر وpublic. مصدرOCAتشغيليunchanged. لا financial/businesswrites أو حذف backups. القيودمرئيةللمالكوسجلIDs للعينة.

تحديث التنفيذ: حارس مستقل أجازCONDITIONAL GO للحصرالخاصفقط. استُخدمتخمسglobalrulesلـstorage/directory/file/accessgroup/sharewizard، ownerIDمنXMLrefbase.user_admin(ثبتQA=2) لاgroup-specificOR. لاgroupownerجديدولاأدوارحقيقيةتغيرت. أبقيناassertAccessErrorلنقلnativeفيtestcaseمنفصلexpectedFailureمعلنكاستثناء، وأضيفprivateORM/HTTP/directattachment/sharewizardcoverage؛ ليستنتيجةPASSعلىصلاحياتOCAالأصلية. إعادةCIمبررةبتغييرعقدالحصرواختباراته وfixtureلاعلىفشلقديمبلاسبب.

BootstrapQA محدود `ops/qa/enable-dms-trial-runtime.sh`: يضيفOCAaddonspathبالضبطلقائمةQAفقطويثبتapprove/deploywrappersالمراجعةمنrevisionمجمد؛ نسخconfig+wrappersمعrestoretrap قبلالتعديل، لاrestart/installفيbootstrap. لاLIVE أوpolicysubstitution. الفحصالفعليقبلالتثبيت: owner2active، dmsغيرمثبت؛ financialfullrowcounts/MD5 كلهاbaseline: summary669/3cc77fb1c40cfe645ff5722a75ee6f33; POS718/5047663e50f54c0c48e7e8e7481c092e; payments1896/a650b5b054949864dca0665892438149; Sales0/null; moves8589/bf48d80866e766c6b4156b6ec6de6348; lines21289/09841457d6a0309df89fd97decf62a4c. المتاح2475192320bytes؛ حارسالنشرلايتجاوز.

CI38530857374 رفضصيغةDomain(1,'=',0) قبلالاختبارات؛ صححتإلى [('id','=',0)] وليسإصلاحP1. CI38531457782 علىfd9502fa:13حالة/2فشل/0أخطاء؛ Odooلايحترم unittest.expectedFailureلهذهالحالة، وقراءةمرفقcontent_fileبـir.attachmentظهرتفجوةفيحاجزالتجربة. مراجعمستقلأجازقاعدةglobalسادسةلمرفقاتres_model=dms.file/dms.directory فقط، معاختباروصولمرفقغيرDMSبدونتغيير. strictnativeassert بقيتفيclass/tagمستقل dms_known_defect، واستُبعدtagصراحةمنبوابةتجربةالمالكبـwaiverالموافقعليه؛ التشغيلالفاشل38528890538و38531457782يبقياندليلP1غيرمصَحّح، لاادعاءأنجميعفحوصOCAنجحت. اختبارحصرDMSattachmentوHTTPrawومرفقغيرDMSسببإعادةCIالجديدة.

قبولbootstrapالمستقلمشروطبـcallerprovenance:gitarchiveمنcommitمدموجمحدد، SHA256محلييطابقالخادم وgitget-tar-commit-idيطابقالcommit قبلالاستخراجفيroot0700 ثمينفذscriptالمستخرج. probeصناعيexactQAذُكروأجيزمستقلًا: PDFassetOCA4ملفات roots/subfoldersلكلشركتينموجودتينيسمحبهماowner2؛ accountmanagerغيرنشطوالنسخةالمكررةومجموعةوصولهكلهاsavepointrollback؛ commitلـsamplesبعدكلassert فقط. ORMغيرالمصادقلايعددليلHTTP؛ HTTPقبولCIونتيجةpublicQAمنفصلان. تحديثrule6يتحققالمرفقالمباشرقبلQA.

مرشحf7ed8160: source38532224423PASS وOdoo38532224474PASS13حالة/0فشل/0أخطاءلحاجزالتجربةوتوصيفالسلوك؛ known_defectمستثنىصراحةبعدwaiver، ليسP1fixed. حارسالتسليمالمستقلCONDITIONAL GO QAowneronlyبشروطالمصدر/backup/hash/probe/ثباتمالية. PR320دُمجبالمصدر87bbe0d5b8410b847a8e0286d8ef143449adffb8. سياسةQAتثبت baseer_dms_trial وdms فقط، لاLIVE. لا إعادةCIلذاتالمصدر؛ policyفقطيحتاجsourceguard.

حكم التسليم المستقل النهائي dms_trial_gate: NO-GO قبلQA، P1 نقل غير مصرح به وليس تسريب قراءة مثبتًا. مجموعة التحرير المشتركة في العينة مقصودة لإثبات أنcompanyruleهيالحاجز. لاخفضassertionولاإعادةاختباردونتغييرمعلل. بوابةألفاG5/G8أوقفتالنشر، وتحتاجالإصلاحاتنطاقًاواعتمادًاجديدًا.

التجربة الفعلية نُفذت في قاعدة Odoo19 معزولة ضمنCI قبلQA، وليسعلىQA؛ أوقفت بوابة السلامة الانتقال إلىQA. ملفان صناعيان في شركتين مع أدوار قراءة/تعديل/غيرعضو وHTTP. لا ملفات حقيقية ولا روابط مشاركة عامة ولاتكاملinvoiceattachment. منعالاسمالمكررليسمنعالمحتوىالمكرر؛ نفسbytesباسمجديديسجلمستندينلكنfilestoreاستعملمسارًاواحدًا. الاستعمالللعقودالحقيقيةأوالنشرQAالآنNO-GOحتىإصلاحالخللوإعادةالفحصالخاصبه. قبولAR/RTL/جوالغيرمثبت؛ ليستسببالمانعالأمني.
