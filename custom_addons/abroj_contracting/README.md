# أبروج للمقاولات — المرحلة الأولى

إضافة جديدة لـ Odoo 19 Community؛ غير منشورة وغير مثبتة على النظام الحي. تعتمد فقط على `project`, `project_account`, `analytic`, `account`, `purchase`؛ وتُفعّل حماية `hr_expense` عند تثبيته اختيارياً. لا تثبيت تلقائي ولا ربط ثابت بالشركة 56 أو بيانات المؤسسة.

من المشاريع ← المقاولات: المشاريع، سندات الصرف، سندات القبض، مقاولو الباطن، فواتير المقاولين، صندوق الوارد، التدفق النقدي. شاشة المشروع تعرض بيانات العقد والعميل والهدف والتواريخ والمدة والتكلفة التقديرية وتبويبات السجلات والسندات والمقاولين والمقبوضات والتدفق النقدي، مستوحاة من مصدر تطبيق «أبروج مشاريع» 1.3.4. يربط العميل بسجل جهة الاتصال وهاتفه؛ أرشفة المشروع تستخدم حقل Odoo «نشط». لا مزامنة مع التطبيق ولا استخراج آلي داخل الإضافة.

## الحسابات وسير العمل

- السند: مسودة ← إصدار واعتماد بضغطة واحدة من المستخدم نفسه ← إلغاء. لا تعديل أو حذف بعد الإصدار/الإلغاء، ولا إصدار مباشر بكتابة الحالة. الترقيم عند الإصدار، مع قفل الصف لمنع الإصدار المتزامن مرتين.
- المتبقي للمقاول = المتفق عليه − سندات الصرف الصادرة + سندات القبض الصادرة المرتبطة به. المفوتر = الفواتير المؤكدة فقط.
- تكاليف المشروع = المصروفات المؤكدة + فواتير مقاولي الباطن المؤكدة. السجلات المستخرجة مسودات للمراجعة، ولا تدخل المجموع تلقائياً. أدخل تكلفة واحدة لكل واقعة؛ لا تسجل فاتورة المقاول مرة ثانية كمصروف.
- ربح العقد = قيمة العقد − إجمالي التكاليف. الربح المتوقع = قيمة العقد − التكلفة التقديرية. المتبقي من العقد = قيمة العقد − جميع سندات القبض الصادرة. التدفق النقدي = المقبوض − المدفوع. تشمل المقبوضات استردادات المقاولين؛ لا تسوية ذمم أو ضريبة أو تعدد عملات في هذه المرحلة، والمبالغ بعملة شركة المشروع.
- المدة = تاريخ الانتهاء − تاريخ البدء بالأيام، دون احتساب يوم البدء مرتين.
- اتفاقية المشروع والسندات متاحة من قائمة الطباعة، باتجاه RTL والطرفان جنباً إلى جنب. جميع بيانات المؤسسة والعنوان والسجل والضريبة من `res.company` وجهة اتصالها وقت الطباعة. لا تُزرع بيانات شركة أو مستخدمين.

## المحاسبة والصلاحيات

إصدار السند لا ينشئ دفعة. زر «اعتماد محاسبي» على السند الصادر ينشئ `account.payment` ويعتمده بالمسار المحاسبي المعتاد؛ يتطلب `account.group_account_manager` أو `account.group_account_invoice` ومحاسباً غير مصدر السند. وكيل الاستخراج ممنوع حتى مع صلاحيات المحاسبة أو sudo. حقل `create_payment` القديم محفوظ للتوافق ولا ينشئ دفعة عند الإصدار. يتطلب الاعتماد دفتر نقد/بنك من الشركة نفسها، وعند ترك الدفتر فارغاً يختار دفتر نقد/بنك من شركة المشروع حسب طريقة الدفع لدعم السندات الصادرة سابقاً. يتطلب طريقة دفع وحساب مقابل معلق يولد قيداً، وحساب مشروع تحليلي. يخصص الحساب المقابل للدفعة بنسبة 100% للمشروع قبل اعتماد الدفعة، ضمن المعاملة نفسها ودون sudo. السند المرتبط بدفعة لا يقبل الإلغاء التلقائي؛ تُعالج الدفعة محاسبياً أولاً. ليس السند فاتورة ضريبية، ولا تنشئ الفواتير المخصصة قيود `account.move`.

مجموعة «وكيل الاستخراج» لا تسند إلى أحد في البيانات. تقرأ المشاريع وفق قواعد Odoo وتكتب المسودات والوارد؛ الكود يمنع الإصدار واعتماد الفواتير والمصروفات وترحيل القيود واعتماد المدفوعات وتأكيد المشتريات. فحص المجموعة لا يستثني رقم المستخدم؛ سياق `env.su` وحده تجاوز صريح للحمايات العامة؛ الاعتماد المحاسبي للسند يمنع الوكيل حتى في هذا السياق. تمتد الحماية إلى اعتماد وترحيل `hr.expense` و`hr.expense.sheet` عند وجود كل منهما دون اعتماد إلزامي على وحدة المصروفات. صلاحيات المشاريع العادية تبقى صلاحيات Odoo الأصلية (إنشاء المشاريع لمدير المشاريع)، والنماذج الجديدة للمستخدم الداخلي، مع قواعد شركات عامة.

## ملاحظات المشروع

تبويب «الملاحظات» والزر الذكي مع العدد يعرضان `abroj.contracting.project.note` داخل المشروع: الكاتب والتاريخ والنوع والنص والملف. الأنواع نص/صوت/صورة/فيديو/PDF. المشروع إلزامي للملاحظة، وشركتها من المشروع، وحذف المشروع يحذف ملاحظاته. الملف Binary بتخزين `attachment=True` مع اسمه ونوع MIME. كل إنشاء ينشر رسالة في محادثات المشروع مع النص المهرب بأمان ونسخة `ir.attachment` مرتبطة بالمشروع؛ الملاحظة الفارغة تنشر «ملاحظة جديدة».

الوارد المرتبط بمشروع ينشئ ملاحظة واحدة تلقائياً ويحفظ رابط `inbox_id` الفريد، بما يشمل رفع صفحة الالتقاط؛ إعادة حفظ المشروع أو تحليل الوارد لا يكرر الملاحظة. يُسمح بوارد دون مشروع من ORM/صندوق الوارد، مع عزله بشركة المستخدم حتى إسناده، وعند إسناد المشروع لاحقاً تنشأ الملاحظة تلقائياً باسم منشئ الوارد وتاريخ إنشائه. هذه نسخة عند الربط وليست مزامنة لتعديلات النص والملف اللاحقة. صفحة الالتقاط نفسها تتطلب مشروعاً في الواجهة والخادم. يستطيع وكيل الاستخراج قراءة وإنشاء الملاحظات مع قواعد عزل الشركات.

## الالتقاط والإشعار

`/abroj/contracting/capture` يتطلب جلسة مستخدم وCSRF، دون website، ويتيح اختيار المشاريع المقروءة في الشركات المسموحة وإضافة ملاحظة أو ملف صوت/صورة/فيديو/PDF حتى 25 MiB. لا sudo لإنشاء السجل أو المرفق.

يضبط المسؤول `abroj_contracting.agent_webhook_url` و`abroj_contracting.agent_webhook_key` في معاملات النظام. عند غياب الرابط لا يحدث شيء. بعد commit يرسل JSON يتضمن فقط: `id`, `model`, `project_id`, `project_name`, `filename`, `mimetype`, `state`, `create_uid`, `create_date`؛ المفتاح في ترويسة `X-Abroj-Key` فقط. لا محتوى ملفات ولا نص ملاحظة ولا أسرار في JSON أو السجلات. مهلة 3 ثوان، دون تتبع تحويلات، والفشل لا يفشل الإنشاء؛ إشعار best-effort دون طابور إعادة محاولة. ضع رابط HTTPS موثوقاً عند التهيئة. `_send_webhook` منفصل ليسهل mock الاختبارات.

## التحقق

اختبارات `AbrojContractingCase` بعد التثبيت تغطي الحسابات، الإصدار والإلغاء، قيود الوكيل والشركات، وإشعار ما بعد commit باستخدام mocks دون أي طلب شبكة، وإنشاء رسالة الملاحظة ومرفقها والفراغ والوارد المرتبط وعدم التكرار وإسناد المشروع لاحقاً بواسطة الوكيل. Workflow `test-abroj-contracting.yml` يتبع صور وإجراء CI المثبتة في `test-bwork-tasks.yml` ويشترط تشغيل الاختبارات الخمسة عشر دون فشل أو تخطي.

شُغلت اختبارات الإضافة على قاعدة `abroj_contracting_544_test`، وعلى قاعدة اختبار مستقلة دون `hr_expense` ثم بعد تثبيته، للتحقق من الحماية والاعتماد الاختياري. لم يُمس النظام الحي.


### تسوية عقود الباطن

تكلفة المشروع التشغيلية = قيم عقود الباطن + المصروفات المستقلة المعتمدة.
مواد أبروج المعتمدة تدخل ضمن قيمة العقد كشراء ودفعة عن المقاول؛ لا تسجل مرة ثانية كمصروف مستقل.
المستحق = قيمة العقد - مواد أبروج - سندات الصرف + المسترد.
مثال: عقد 100,000 ومواد 80,000 → تكلفة العقد 100,000 ومستحق 20,000 قبل الدفعات.
فواتير المواد باسم المقاول مرفقات إثبات فقط، بلا تكلفة أو ضريبة.
اختر معالجة الفاتورة حسب اسم المشتري في أصل الفاتورة؛ لمواد أبروج أدخل رقم الشركة الضريبي المطابق.
هذه سجلات تشغيلية ولا تنشئ فواتير مورد أو قيود ضريبة في دفتر الأستاذ؛ التسجيل الضريبي معلومة فقط.
الضمان نسبة اختيارية للمراجعة، ضمن إجمالي المستحق ولا يخصم تلقائياً.
زر تسوية نهاية المشروع يطبع ملخصاً دون إنشاء دفعات أو إقفال العقد.

## Printable bilingual contracts and vouchers

Project and subcontractor forms provide Arabic print buttons. Contracts place English
on the left and Arabic (`dir="rtl"`) on the right in a separate table for each clause.
Project contract value is shown with the separately configured VAT rate, VAT amount
and VAT-inclusive total. Enter payment milestones, retention and contract dates before
printing. Subcontracts also expose start/end dates and penalties.

The **بنود العقود** menu contains sequenced Arabic/English clause templates by contract
kind. Internal users can read them; Project Managers can edit, archive and create them.
Default clauses use `noupdate="1"`, so module upgrades preserve edits. Reports reflect
current terms and balances when printed; PDFs are not immutable signed snapshots.

Receipt vouchers without a subcontract must name the project's customer. Payments
must reference a subcontract or a vendor contract reference before issuance. Vendor
contract value is entered on each vendor voucher. Subcontract receipts remain supported
as refunds. The form and PDF calculate:

- Client receipt: contract value − previous issued receipts − current receipt.
- Subcontract: agreed value − confirmed Abroj materials − previous net payments
  − current payment (a refund increases the balance).
- Vendor payment: vendor contract value − previous payments − current payment.

History is scoped by company, project, party, subcontract and vendor reference.
Issued vouchers use issuance time, with ID as a tie breaker, rather than business date;
backdating does not reorder issuance history. Existing issued records are initialized
from creation time during upgrade. Cancelled vouchers are excluded. Retention remains
within the balance and is displayed separately on contracts, matching existing accounting.

Company forms expose Arabic and English contract names. The custom report layout uses
the document company for names, CR, VAT, address, contacts and logo. Set both names for
bilingual branding; an unset name falls back to the company's name. DejaVu Sans and its
license are bundled and embedded as a data URI. Report bodies, headers and footers are
self-contained, so wkhtmltopdf does not need an HTTP asset server. A patched-Qt
wkhtmltopdf installation is required for repeating headers and footers.

Sample generator (strictly restricted to `abroj_contracting_544_test`):
`custom_addons/abroj_contracting/scripts/generate_samples.py`.
Feed it to `odoo-bin shell` with the same test DB/addons/data-dir arguments. It creates
an isolated sample company, loads the website's Abroj logo, writes the four PDFs into
`/workspace/abroj-contract-samples`, then rolls back all sample database records.
