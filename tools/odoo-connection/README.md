# اتصال بصير المحلي

افتح `Open-Connection.cmd`. أدخل مفتاح API في نافذة Windows ذات الحقل المخفي، ثم «اختبار وحفظ». عنوان بصير مثبت في المصدر. اسم قاعدة البيانات اختياري إن كان الخادم يختارها من العنوان؛ إن فشل الاختبار بسبب اختيار القاعدة، أدخل الاسم الصحيح. لا ترسل المفتاح في المحادثة أو سطر الأوامر.

الأفضل حساب تكامل مستقل عن **Baseer MCP Live Reports**؛ صلاحيات مفتاح أودو تتبع حسابه. هذا البرنامج لا ينشئ حسابًا أو مفتاحًا ولا يوسّع صلاحيات الحساب. يجب أن يملك الحساب صلاحيات قراءة الموظفين والعقود والرواتب والشركات المطلوبة كي تعمل قراءاتها. نجاح اختبار الهوية وحده لا يثبت صلاحية كل نموذج.

يحفظ البرنامج بيانات الاتصال في **Windows Credential Manager** للمستخدم الحالي تحت الاسم `BaseerCodex/Odoo/baseer.abroj.sa`؛ لا يكتب ملف مفاتيح في المشروع. مخزن Windows لا يحمي المفتاح من برنامج آخر يعمل بحساب Windows نفسه. لا يُستبدل الاتصال السابق إلا بعد نجاح اختبار الهوية؛ لا تحفظ الأداة نسخة قديمة. عند فقد حساب Windows أعد إدخال المفتاح. إلغاء المفتاح يتم من أودو. إذا رفض Windows الوصول للمخزن تتوقف الأداة دون تخفيف صلاحيات الجهاز أو تخزين نصي بديل.

للاستعلام من PowerShell:

```powershell
& .\Read-Baseer.ps1 -Status
& .\Read-Baseer.ps1
& .\Read-Baseer.ps1 -Model hr.employee -Method fields_get -Fields id,name,company_id,baseer_salary_total,contract_date_start
& .\Read-Baseer.ps1 -Model hr.employee -Method search_read -Fields id,name,company_id,version_id,baseer_payroll_enabled,baseer_salary_total,contract_date_start -CompanyIds 1 -DomainJson '[["active","=",true]]'
```

الموارد المسموحة حاليًا: هوية الشركات، والحقول المحددة لتشخيص الرواتب في `hr.employee`, `hr.version`, `hr.payslip`, `hr.payslip.run`. استخدم `fields_get` بحقول محددة للتحقق من توافق نسخة أودو؛ غياب حقل أو صلاحية يرفضه أودو ولا يجري fallback بصلاحيات أعلى. النتائج تأتي من أودو بلا حساب أو إعادة تقريب محلية. كل صفحة بحد 100 سجل، مهلة 15 ثانية، حجم رد أقصى 2 MiB، بلا تحويل عنوان أو استدعاء methods أخرى أو caller context.

موصل MCP المحلي `Start-BaseerMcp.ps1` يطلقه Codex من إعدادات MCP وفق `mcp-config.example.toml`؛ لا يعمل خادم شبكة. يوفر حالة الاتصال والهوية والقراءة المحدودة فقط. يشغل المالك نافذة الإعداد من جلسة Windows العادية، لأن بيئة الأوامر المعزولة لا تملك الوصول لمخزن بيانات الاعتماد. لا تنقل المفتاح إلى هذه البيئة لحل ذلك. **لم يسجل الموصل في إعدادات Codex بعد، ولم يُختبر الاتصال الحقيقي أو صلاحيات أودو أو تشغيل الموصل من مضيف Codex.**

هذه شريحة للقراءة فقط وليست تنفيذًا للتعديلات بعد الموافقة. عند طلب تعديل بعينه يُراجع أثره وتُجهز قيم قبل/بعد وآلية موافقة وتنفيذ خاصة به. لا تضع مفتاح مدير داخل موصل التقارير الحالي.

التحقق دون شبكة: `Test-Connection.ps1` و`Test-Mcp.ps1`. في جلسة Windows العادية يمكن تشغيل `Test-Connection.ps1 -NativeStore`؛ يستخدم سجل TEST عشوائيًا ويحذفه، ولا يلمس المفتاح الحقيقي. الفحص الافتراضي لا يختبر مخزن Windows بسبب قيد البيئة المذكور.

English: local Windows credential bootstrap and bounded read-only Odoo 19 JSON-2 client. No packages/listener/deployment. Pin: `https://baseer.abroj.sa`. Setup is independent of the deployed report MCP identity. Live connectivity and field rights require the owner's API key; they are not certified by offline tests.
