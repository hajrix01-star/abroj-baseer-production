# لوحة مشاريع أبرج / Abroj project dashboard

لوحة عربية في تطبيق المشاريع تعرض المؤشرات والمالية ومراحل المهام والمتأخرات. تتيح صفحة المشروع تفاصيل الميزانية والسندات. حقول الإعداد موجودة في تبويب «لوحة أبرج» وتاريخ بداية المرحلة في المهمة.

The Project menu opens an RTL dashboard with filters, project details, budget categories and phase dates. Project and task access uses the current user's record rules and allowed companies. Install `project`, `analytic` and `account`; contracting is optional.

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

Run Odoo with `-i abroj_project_dashboard --without-demo=all --test-enable --test-tags=/abroj_project_dashboard --stop-after-init --workers=0 --max-cron-threads=0` on a fresh test database. The workflow runs 31 methods across the model and HTTP test classes. To exercise voucher integration too, install `abroj_contracting` and run the dashboard tests on that database.

## Remaining / المتبقي

Live installation requires approval. Removal of `abroj_project_costing` is a separate future task. Link and validate real contracts, vouchers and cost categorisation with the business before relying on financial results.

### تطبيق الهاتف / Mobile app

افتح `/abroj/app` بحساب Odoo ثم اختر «إضافة إلى الشاشة الرئيسية» من المتصفح. يتطلب تشغيل عامل الخدمة والكاميرا والميكروفون HTTPS في الإنتاج (أو localhost للتطوير). تتوفر نماذج المراحل والمشروع ومعرض المرفقات والتسجيل الصوتي والتقاط الصور. الحد الأقصى للملف 25 ميغابايت، وتُرفع الملفات الأصلية دون ضغط من التطبيق.

Open `/abroj/app` with an Odoo account and choose Add to Home Screen. Service workers, camera and microphone require HTTPS in production (localhost is allowed for development). Task and project forms, attachment galleries, voice recording and camera capture are available. Original files are uploaded without app-side compression, up to 25 MB. Camera and microphone access depends on browser support and user permission.

مدير المشروع يستطيع تعديل الميزانية؛ مستخدم المشروع لا يستطيع تعديل الميزانية أو بنودها أو قيمة العقد. تطبق الصلاحيات وقواعد السجلات في Odoo. Project managers can edit budgets; project users cannot edit budgets, budget lines or contract values. Odoo access rights and record rules apply. If a user cannot write a particular project, its project edit action is hidden; task actions depend on task permissions. Users without analytic-line read access see only manual actual costs.

تُخفى أزرار التعديل حسب صلاحية السجل؛ وتقتصر التكاليف الفعلية للمستخدم الذي لا يملك صلاحية قراءة القيود التحليلية على القيم اليدوية.
