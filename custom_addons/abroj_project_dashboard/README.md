# لوحة مشاريع أبرج / Abroj project dashboard

لوحة عربية في تطبيق المشاريع تعرض المؤشرات والمالية ومراحل المهام والمتأخرات. تتيح صفحة المشروع تفاصيل الميزانية والسندات. حقول الإعداد موجودة في تبويب «لوحة أبرج» وتاريخ بداية المرحلة في المهمة.

The Project menu opens an RTL dashboard with filters, project details, budget categories and phase dates. Project and task access uses the current user's record rules and allowed companies. The module depends on `abroj_contracting` as well as `project`, `analytic` and `account`.

تاريخ بداية المرحلة هو المرجع، والمدة بالأيام الصحيحة لا تقل عن يوم واحد. الحساب شامل ليوم البداية: ثلاثة أيام تبدأ الأحد تنتهي الثلاثاء. عند تغيير البداية أو المدة يتغير تاريخ النهاية تلقائياً؛ وعند غياب البداية يبقى الموعد الموجود كما هو. عند الترقية تُستخلص المدة من التاريخين الموجودين (وبحد أدنى يوم واحد) دون تغيير الموعد.

The phase start date is the anchor and duration is a whole number of days, at least one. Counting is inclusive: three days starting Sunday end Tuesday. Changing the start or duration recalculates the end; without a start, the existing deadline is preserved. On upgrade, existing dates are used to backfill the duration (minimum one day) without changing the deadline.

## مصادر البيانات / Data assumptions

- Project budget and contract value are manual. If manual contract value is zero and `abroj_contracting` is installed, its project contract value is used.
- Actual cost is negative analytic lines on the project analytic account plus manual category actuals. Category totals include only analytic lines explicitly tagged with the budget line, plus that line's manual actual. Untagged analytic costs are included in project actual but not a category. Avoid entering the same cost manually and analytically.
- Only issued contracting vouchers visible to the user count as collected or paid. Liquidity is receipts minus payments; vouchers are not added to analytic costs, avoiding double counting. Without contracting or voucher read access, liquidity is zero; invoice payments are not inferred.
- Manual progress is enabled by a checkbox; otherwise the percentage of completed or cancelled tasks is used. A project is completed by status or closed date. Delayed means an overdue project or open task. Stalled means off-track/on-hold or no project/task write in 30 days. These are operational indicators, not accounting statements.
- Users without analytic-line read access see only manual category actuals; analytic costs are omitted from their totals. Financial totals can therefore differ by user.
- Amounts are summed in company currency; dashboards spanning companies with different currencies should be filtered to one company.

## Demo / بيانات توضيحية

On a disposable database only, after installing the module without demo data:

```bash
/opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin shell --db_host=/tmp --db_port=5433 --db_user=odoo --addons-path=/opt/odoo19/src/addons,/workspace/abroj-baseer-production/custom_addons -d dash1_demo < custom_addons/abroj_project_dashboard/scripts/load_demo_data.py
```

Use `--data-dir=/tmp/abroj_odoo_data` when the default Odoo data directory is not writable.

The script creates illustrative projects in `base.main_company` and adds it to the admin user's allowed companies, and grants that user analytic-accounting access. Install `abroj_contracting` in the disposable demo database before running the script to create subcontract records and issued receipt and payment vouchers; otherwise liquidity is zero. The script creates disposable `owner` / `owner` (project manager) and `engineer` / `engineer` (project user) accounts in the main company. The script commits explicitly; never run it against production.

## Tests / الاختبارات

Run Odoo with `-i abroj_project_dashboard --without-demo=all --test-enable --test-tags=/abroj_project_dashboard --stop-after-init --workers=0 --max-cron-threads=0` on a fresh test database. The workflow expects 46 methods across the model and HTTP test classes. `abroj_contracting` is installed as a dependency.

## Remaining / المتبقي

يتطلب التثبيت الفعلي موافقة مسبقة. إزالة `abroj_project_costing` مهمة مستقلة لاحقاً. يجب ربط العقود والسندات الحقيقية والتحقق من تصنيف التكاليف مع فريق العمل قبل الاعتماد على النتائج المالية.

Live installation requires approval. Removal of `abroj_project_costing` is a separate future task. Link and validate real contracts, vouchers and cost categorisation with the business before relying on financial results.

### تطبيق الهاتف / Mobile app

تستخدم الواجهة هوامش المناطق الآمنة وأحجاماً مناسبة للّمس، مع حقول إدخال بحجم خط لا يقل عن 16 بكسل. تتوفر واجهة الهاتف بالعربية والإنجليزية.

The PWA includes safe-area padding, larger touch controls and input text of at least 16px. Arabic and English can be selected in the header or drawer; the choice is stored locally and synced to the current Odoo user. Numbers use Intl with ar-SA or en-US, and dates use the same locale with UTC to preserve calendar dates.

افتح `/abroj/app` بحساب Odoo ثم اختر «إضافة إلى الشاشة الرئيسية» من المتصفح. يتطلب تشغيل عامل الخدمة والكاميرا والميكروفون HTTPS في الإنتاج (أو localhost للتطوير). تتوفر نماذج المراحل والمشروع ومعرض المرفقات والتسجيل الصوتي والتقاط الصور. الحد الأقصى للملف 25 ميغابايت، وتُرفع الملفات الأصلية دون ضغط من التطبيق.

Open `/abroj/app` with an Odoo account and choose Add to Home Screen. Service workers, camera and microphone require HTTPS in production (localhost is allowed for development). Task and project forms and attachment galleries are available. The media screen offers a rear-facing high-resolution camera, camera switching and torch where supported, native camera fallback and multiple file selection. Files are uploaded unchanged, preserving image metadata, up to 25 MB each. Upload progress and retry are shown per file; uploads queued in IndexedDB are retried when the app is open and connectivity returns. The voice sheet supports press and hold to record, slide to cancel, a live waveform, timer and playback before sending. The full-screen camera offers a preview and retake before sending. Permission help is shown in the app. Camera and microphone access depends on browser support and permission. Keep the app open while uploads finish; queued media remains on the device until uploaded.

مدير المشروع يستطيع تعديل الميزانية؛ مستخدم المشروع لا يستطيع تعديل الميزانية أو بنودها أو قيمة العقد. تطبق الصلاحيات وقواعد السجلات في Odoo. Project managers can edit budgets; project users cannot edit budgets, budget lines or contract values. Odoo access rights and record rules apply. If a user cannot write a particular project, its project edit action is hidden; task actions depend on task permissions. Users without analytic-line read access see only manual actual costs.

تُخفى أزرار التعديل حسب صلاحية السجل؛ وتقتصر التكاليف الفعلية للمستخدم الذي لا يملك صلاحية قراءة القيود التحليلية على القيم اليدوية.

### واجهة المشروع وسند الأمر / Project navigation and promissory notes

الدرج الأيمن يعرض المشاريع والبحث وأقسام اللوحة. داخل المشروع توجد تبويبات وزر إضافة؛ وتشمل النماذج الحالية عقد الباطن والسندات والملاحظات والفاتورة والمصروف. اتفاقية العميل هي حقول المشروع في إضافة المقاولات وليست سجلاً مستقلاً. نموذج `abroj.promissory.note` أُضيف حديثاً هنا، مع ترقيم وحالات وطباعة وصلاحية قراءة وإنشاء للمستخدم وصلاحيات كاملة لمدير المشاريع. تستخدم الواجهة شعار أبرج ولوحة ألوان موحدة ومكدس خطوط النظام في Odoo.

The drawer opens on the right in Arabic and on the left in English and provides project search and dashboard navigation. Project tabs and the floating button expose the current subcontract, voucher, note, invoice and cost forms. The client agreement is represented by project fields in contracting rather than a separate record. `abroj.promissory.note` is newly added here, with a sequence, states, PDF and read/create access for users and full access for project managers. The PWA uses the Abroj logo and a shared navy and orange token palette with the Odoo system font stack.

تستخدم واجهة التطبيق صلاحيات المستخدم دون `sudo` لبيانات الأعمال. تنشئ الملاحظات عبر ORM بصلاحيات المستخدم؛ وتستخدم إضافة المقاولات نفسها `sudo` داخلياً بعد التحقق من قراءة المشروع لنشر الملاحظة ونسخ المرفق إلى سجل المحادثة.

The PWA calls the ORM as the current user. The existing contracting note model internally uses `sudo` after checking project read access to post the note and copy its attachment to chatter.

تنزيل PDF يتحقق من صلاحية قراءة المستند والمشروع. الاختبارات تحاكي توليد PDF؛ يتطلب التحقق من التوليد الفعلي بيئة CI أو خادماً مثبتاً عليه wkhtmltopdf، وهو غير متاح على جهاز Debian 13 المحلي.

PDF downloads check document and project read access. Tests mock the renderer; actual rendering must be verified in CI or a live environment with wkhtmltopdf, which is unavailable on this Debian 13 host.

لا تزال بعض حقول المقاولات المتقدمة (مثل البنود الثنائية اللغة والمرفقات المرتبطة بالمستند نفسه) وإجراء الاعتماد المحاسبي غير متاحة في واجهة الهاتف. أزرار PDF متاحة للاتفاقية وعقد الباطن والسندات فقط؛ الفواتير والمصروفات والملاحظات ليس لها زر PDF في هذه الواجهة.

Some advanced contracting fields (including bilingual clauses and document-specific attachments) and accounting approval are not yet exposed in the PWA. PDF buttons cover the client agreement, subcontract and vouchers; invoices, costs and notes do not have PDF buttons in this interface.

### مهامي اليوم والتصميم / My Day and design

تعرض «مهامي اليوم» سجلات `project.task` ضمن المشاريع المتاحة للمستخدم، مجمعة حسب المشروع. تعتمد على `x_abroj_date_start` و`date_deadline` و`x_abroj_duration_days` و`user_ids`؛ وتعرض المرحلة إذا كان موعدها النهائي في اليوم أو بعد بدايته، وكانت بدايتها في اليوم أو قبله، أو كان موعدها النهائي خلال اليوم حتى لو لم توجد بداية. يُحدد اليوم باستخدام `fields.Date.context_today` في سياق المستخدم، وتُقارن المواعيد بحدود ذلك التاريخ كما يخزنها Odoo. لا يقتصر العرض على المهام المسندة للمستخدم ولا يستبعد الحالات المنتهية. يفتح الرابط المرحلة مع تمييزها، ويعيد الرجوع موضع القائمة.

My Day groups accessible `project.task` records by project, using `x_abroj_date_start`, `date_deadline`, `x_abroj_duration_days` and `user_ids`. It includes phases whose deadline is on or after the start of today and whose start is on or before today, plus phases due during today even without a start date. Today comes from `fields.Date.context_today` in the user's context; deadline comparisons use the corresponding date boundaries as stored by Odoo. The list is not limited to tasks assigned to the user and does not exclude completed states. Links open and highlight the phase; back restores the list position.

تتكيف الواجهة مع عرض الهاتف والجهاز اللوحي، وتسمح بتمرير تبويبات المشروع أفقياً، وتراعي اتجاه العربية والإنجليزية ومناطق الأجهزة الآمنة. يُحفظ اختيار اللغة محلياً ويُزامن مع المستخدم؛ أسماء المشاريع والبيانات المدخلة لا تُترجم تلقائياً.

The layout adapts to phones and tablets, with horizontally scrollable project tabs, RTL/LTR direction and safe-area insets. The language choice is stored locally and synced to the user; project names and entered data are not automatically translated.

توجد أصول الهوية في `static/pwa/`: الشعار الكحلي والأبيض وأيقونات التطبيق ونسخة maskable وأيقونة Apple. تعرف `css/tokens.css` ألوان الهوية والمسافات والزوايا والظلال، وتجمع ملفات CSS الأخرى أنماط الأساس والمكونات والشاشات. تستخدم الواجهة خط النظام مع التركيز المرئي وتقليل الحركة عند طلبه.

Brand assets in `static/pwa/` include navy and white logos, app icons, a maskable icon and an Apple touch icon. `css/tokens.css` defines the palette, spacing, radii and shadows; the other CSS files cover base styles, components and screens. The interface uses system fonts, visible focus styles and reduced motion when requested.

The camera action opens a full-screen live view directly. Capture several photos, remove individual shots, add a shared caption and send them through the offline upload queue; captions are stored on each attachment. Zoom, focus and torch controls depend on device capabilities. If access is denied, the permission sheet offers the device file picker.

For the mobile browser check, install Playwright and run `scripts/check_camera_playwright.py` against an isolated demo database with `M5_BASE_URL`, `M5_USER`, `M5_PASSWORD` and `M5_SCREENSHOT_DIR` set as needed. Chromium uses fake camera and microphone devices; the script exercises multi-shot upload, captions, permission fallback and voice states.
