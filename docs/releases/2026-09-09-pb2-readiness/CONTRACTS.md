# العقود في النسخة الحالية

فحص قراءة للمحرك الفعلي علىQAبتاريخ9سبتمبر2026، دون تغيير عقد موظف أو إضافة موديول.

- العقد غير محدد المدة موجود: `hr.version.contract_date_start` يحدد البداية و`contract_date_end=False` يعني نهاية مفتوحة. غياب البداية لا يكفي لاعتبار العقد ساريًا. ملف الموظف ← كشوف المرتبات ← نظرة عامة على العقد يعرض «غير محدد المدة» في خانة النهاية بعد إدخال البداية.
- أضيف فيPB2 توضيح بجوار مجموعة العقد الأصلية، مع بقاء صلاحيات `hr.group_hr_manager`. مدير الرواتب وحده لا يُمنح صلاحية تعديل عقدHR ضمن هذا التغيير.
- قوالب الإعدادات موجودة في `hr.action_hr_contract_templates` على نموذج `hr.version` بلا موظف؛ زر «تحميل قالب» يستخدم `hr.version.wizard.action_load_template` لنسخ الوظيفة والقسم والأجر والجدول ونوع العقد وهيكل الراتب. البداية لا تُملأ افتراضيًا من هذا المسار.
- لم يُوجد في الإضافات المثبتة تقريرPDFلعقد العمل مرتبط بالموظف أوhr.version؛ تقارير الموظف المتاحة الشارة والسيرة الذاتية. لا `hr_contract_salary` أو`documents`مثبت، ومصدر`sign`غير موجود.
- وثائقOdoo19 تصف قوالبPDFوالتوقيع ضمنSalary Configurator وSign. هذه قدرة مختلفة عن قوالب إعداد الموظف الموجودة: https://www.odoo.com/documentation/19.0/applications/hr/payroll/contracts.html و https://www.odoo.com/documentation/19.0/applications/hr/recruitment/offer_job_positions.html .

الطريقة المتاحة الآن للطباعة: إرفاق نسخةPDFمعتمدة من عقد المؤسسة بملف الموظف، ثم فتحها وطباعتها، وحفظ النسخة الموقعة في المرفقات. توليدPDFمملوء تلقائيًا من بيانات الموظف يتطلب تقريرًا يستعمل صيغة عقد معتمدة؛ لم يطلب المستخدم صياغة نص قانوني أو تثبيت نظام توقيع، لذلك لا أضيفهما ضمنPB2.

الأدلة الأصلية: native `hr/models/hr_version.py:156,445` و`hr/models/hr_employee.py:181` و`hr/views/hr_employee_views.xml:325,338` و`hr/views/hr_contract_template_views.xml:69` و`hr/wizard/hr_contract_template_wizard.py:15`. قراءةir.actions.reportالأصلية نفذهاaudit_sales_reports؛ لا توجد ادعاءات بطباعة عقد لم يتم إنشاؤه.
