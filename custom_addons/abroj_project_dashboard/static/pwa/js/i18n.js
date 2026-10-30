'use strict';
const translations = {
  "toggleProjects": {"ar": "توسيع أو طي المشاريع", "en": "Expand or collapse projects"},
  "archive": {"ar": "أرشيف", "en": "Archive"},
  "activeProjects": {"ar": "المشاريع النشطة", "en": "Active projects"},
  "newProject": {"ar": "مشروع جديد", "en": "New project"},
  "projectName": {"ar": "اسم المشروع", "en": "Project name"},
  "s0": {
    "ar": "أخرى",
    "en": "Other"
  },
  "s1": {
    "ar": "أنواع المشاريع",
    "en": "Project types"
  },
  "s2": {
    "ar": "إجمالي المشاريع",
    "en": "Total projects"
  },
  "s3": {
    "ar": "إضافة",
    "en": "Add"
  },
  "s4": {
    "ar": "إضافة إلى",
    "en": "Add to"
  },
  "s5": {
    "ar": "إضافة بند",
    "en": "Add item"
  },
  "s6": {
    "ar": "إضافة مرحلة",
    "en": "Add phase"
  },
  "s7": {
    "ar": "إلغاء",
    "en": "Cancel"
  },
  "s8": {
    "ar": "إيقاف التسجيل",
    "en": "Stop recording"
  },
  "s9": {
    "ar": "إيقاف ورفع التسجيل",
    "en": "Stop and upload recording"
  },
  "s10": {
    "ar": "ابدأ التسجيل أولاً",
    "en": "Start recording first"
  },
  "s11": {
    "ar": "اتفاقية العميل",
    "en": "Client agreement"
  },
  "s12": {
    "ar": "اختر",
    "en": "Select"
  },
  "s13": {
    "ar": "اختر ملفاً أولاً",
    "en": "Choose a file first"
  },
  "s14": {
    "ar": "اعتماد / إصدار",
    "en": "Confirm / issue"
  },
  "s15": {
    "ar": "افتح الكاميرا أولاً",
    "en": "Open the camera first"
  },
  "s16": {
    "ar": "الاسم",
    "en": "Name"
  },
  "s17": {
    "ar": "البحث عن مشروع",
    "en": "Search projects"
  },
  "s18": {
    "ar": "البند",
    "en": "Item"
  },
  "s19": {
    "ar": "البيان",
    "en": "Description"
  },
  "s20": {
    "ar": "التاريخ",
    "en": "Date"
  },
  "s21": {
    "ar": "التصنيف",
    "en": "Category"
  },
  "s22": {
    "ar": "التقاط الصورة غير مدعوم؛ استخدم اختيار الصورة.",
    "en": "Photo capture is not supported; choose a photo instead."
  },
  "s23": {
    "ar": "التقاط صورة أو اختيار ملف",
    "en": "Take a photo or choose a file"
  },
  "s24": {
    "ar": "التقاط ورفع",
    "en": "Capture and upload"
  },
  "s25": {
    "ar": "التكلفة التقديرية",
    "en": "Estimated cost"
  },
  "s26": {
    "ar": "التكلفة الفعلية",
    "en": "Actual cost"
  },
  "s27": {
    "ar": "الحالة",
    "en": "Status"
  },
  "s28": {
    "ar": "الخط الزمني",
    "en": "Timeline"
  },
  "s29": {
    "ar": "الخط الزمني للمشاريع",
    "en": "Project timeline"
  },
  "s30": {
    "ar": "الربح",
    "en": "Profit"
  },
  "s31": {
    "ar": "الرقم الضريبي للمشتري",
    "en": "Buyer tax number"
  },
  "s32": {
    "ar": "السندات",
    "en": "Vouchers"
  },
  "s33": {
    "ar": "السيولة",
    "en": "Liquidity"
  },
  "s34": {
    "ar": "الطرف",
    "en": "Party"
  },
  "s35": {
    "ar": "العقود والاتفاقيات",
    "en": "Contracts and agreements"
  },
  "s36": {
    "ar": "العقود والسندات",
    "en": "Contracts and vouchers"
  },
  "s37": {
    "ar": "العميل",
    "en": "Client"
  },
  "s38": {
    "ar": "الفعلي",
    "en": "Actual"
  },
  "s39": {
    "ar": "الفعلي اليدوي",
    "en": "Manual actual"
  },
  "s40": {
    "ar": "الفواتير والمصروفات",
    "en": "Invoices and expenses"
  },
  "s41": {
    "ar": "القيمة",
    "en": "Value"
  },
  "s42": {
    "ar": "المالية",
    "en": "Finance"
  },
  "s43": {
    "ar": "المبلغ",
    "en": "Amount"
  },
  "s44": {
    "ar": "المتأخرة والمتعثرة",
    "en": "Delayed and stalled"
  },
  "s45": {
    "ar": "المتابعة",
    "en": "Tracking"
  },
  "s46": {
    "ar": "المدة (أيام)",
    "en": "Duration (days)"
  },
  "s47": {
    "ar": "المراحل",
    "en": "Phases"
  },
  "s48": {
    "ar": "المرفقات",
    "en": "Attachments"
  },
  "s49": {
    "ar": "المستفيد",
    "en": "Beneficiary"
  },
  "s50": {
    "ar": "المشاريع",
    "en": "Projects"
  },
  "s51": {
    "ar": "المشاريع المتأخرة والمتعثرة",
    "en": "Delayed and stalled projects"
  },
  "s52": {
    "ar": "المشاريع المكتملة",
    "en": "Completed projects"
  },
  "s53": {
    "ar": "المشروع غير متاح",
    "en": "Project unavailable"
  },
  "s54": {
    "ar": "المكان",
    "en": "Place"
  },
  "s55": {
    "ar": "الملاحظات",
    "en": "Notes"
  },
  "s56": {
    "ar": "الملاحظة",
    "en": "Note"
  },
  "s57": {
    "ar": "الملخص",
    "en": "Summary"
  },
  "s58": {
    "ar": "الملفات والصور",
    "en": "Files and photos"
  },
  "s59": {
    "ar": "المورد",
    "en": "Vendor"
  },
  "s60": {
    "ar": "الميزانية",
    "en": "Budget"
  },
  "s61": {
    "ar": "الميزانية والتكلفة",
    "en": "Budget and cost"
  },
  "s62": {
    "ar": "النظرة العامة",
    "en": "Overview"
  },
  "s63": {
    "ar": "الوصف",
    "en": "Description"
  },
  "s64": {
    "ar": "بحث",
    "en": "Search"
  },
  "s65": {
    "ar": "بدء التسجيل",
    "en": "Start recording"
  },
  "s66": {
    "ar": "بدء التسجيل الصوتي",
    "en": "Start voice recording"
  },
  "s67": {
    "ar": "بدون مواد",
    "en": "Labor only"
  },
  "s68": {
    "ar": "بنود الميزانية",
    "en": "Budget items"
  },
  "s69": {
    "ar": "تاريخ الإصدار",
    "en": "Issue date"
  },
  "s70": {
    "ar": "تاريخ الاستحقاق",
    "en": "Due date"
  },
  "s71": {
    "ar": "تاريخ الانتهاء",
    "en": "End date"
  },
  "s72": {
    "ar": "تاريخ البدء",
    "en": "Start date"
  },
  "s73": {
    "ar": "تاريخ البداية",
    "en": "Start date"
  },
  "s74": {
    "ar": "تاريخ النهاية",
    "en": "End date"
  },
  "s75": {
    "ar": "تجاوز",
    "en": "Over budget"
  },
  "s76": {
    "ar": "تجاوز الميزانية",
    "en": "Budget overrun"
  },
  "s77": {
    "ar": "تحميل PDF",
    "en": "Download PDF"
  },
  "s78": {
    "ar": "تحويل بنكي",
    "en": "Bank transfer"
  },
  "s79": {
    "ar": "تعديل",
    "en": "Edit"
  },
  "s80": {
    "ar": "تعديل المرحلة",
    "en": "Edit phase"
  },
  "s81": {
    "ar": "تعديل المشروع",
    "en": "Edit project"
  },
  "s82": {
    "ar": "تعذر بدء التسجيل. تحقق من إذن الميكروفون والاتصال الآمن.",
    "en": "Could not start recording. Check microphone permission and secure connection."
  },
  "s83": {
    "ar": "تعذر تحميل البيانات. تحقق من صلاحياتك.",
    "en": "Could not load data. Check your permissions."
  },
  "s84": {
    "ar": "تعذر تنفيذ العملية. تحقق من صلاحياتك.",
    "en": "Could not complete the operation. Check your permissions."
  },
  "s85": {
    "ar": "تعذر رفع الملف",
    "en": "Could not upload file"
  },
  "s86": {
    "ar": "تعذر فتح الكاميرا. تحقق من الإذن والاتصال الآمن.",
    "en": "Could not open camera. Check permission and secure connection."
  },
  "s87": {
    "ar": "تفاصيل المشروع",
    "en": "Project details"
  },
  "s88": {
    "ar": "تم السداد",
    "en": "Paid"
  },
  "s89": {
    "ar": "تنزيل",
    "en": "Download"
  },
  "s90": {
    "ar": "جار التحميل...",
    "en": "Loading..."
  },
  "s91": {
    "ar": "جارية",
    "en": "Ongoing"
  },
  "s92": {
    "ar": "حفظ",
    "en": "Save"
  },
  "s93": {
    "ar": "داخل الميزانية",
    "en": "Within budget"
  },
  "s94": {
    "ar": "ر.س",
    "en": "SAR"
  },
  "s95": {
    "ar": "رجوع",
    "en": "Back"
  },
  "s96": {
    "ar": "رفع الملف",
    "en": "Upload file"
  },
  "s97": {
    "ar": "رقم الفاتورة",
    "en": "Invoice number"
  },
  "s98": {
    "ar": "سند أمر",
    "en": "Promissory note"
  },
  "s99": {
    "ar": "سند صرف",
    "en": "Payment voucher"
  },
  "s100": {
    "ar": "سند قبض",
    "en": "Receipt voucher"
  },
  "s101": {
    "ar": "شامل المواد",
    "en": "Including materials"
  },
  "s102": {
    "ar": "شامل مواد",
    "en": "Including materials"
  },
  "s103": {
    "ar": "شروط الدفع",
    "en": "Payment terms"
  },
  "s104": {
    "ar": "طريقة الدفع",
    "en": "Payment method"
  },
  "s105": {
    "ar": "عرض وإضافة المرفقات",
    "en": "View and add attachments"
  },
  "s106": {
    "ar": "عقد الباطن",
    "en": "Subcontract"
  },
  "s107": {
    "ar": "عقد باطن",
    "en": "Subcontract"
  },
  "s108": {
    "ar": "على المسار",
    "en": "On track"
  },
  "s109": {
    "ar": "غير محدد",
    "en": "Undefined"
  },
  "s110": {
    "ar": "فاتورة مقاول",
    "en": "Contractor invoice"
  },
  "s111": {
    "ar": "فتح الكاميرا",
    "en": "Open camera"
  },
  "s112": {
    "ar": "قيد التنفيذ",
    "en": "In progress"
  },
  "s113": {
    "ar": "قيمة العقد",
    "en": "Contract value"
  },
  "s114": {
    "ar": "قيمة عقد المورد",
    "en": "Vendor contract value"
  },
  "s115": {
    "ar": "كل أنواع المشاريع",
    "en": "All project types"
  },
  "s116": {
    "ar": "كل الحالات",
    "en": "All statuses"
  },
  "s117": {
    "ar": "لا توجد بنود",
    "en": "No items"
  },
  "s118": {
    "ar": "لا توجد عقود أو سندات",
    "en": "No contracts or vouchers"
  },
  "s119": {
    "ar": "لا توجد مراحل",
    "en": "No phases"
  },
  "s120": {
    "ar": "لا توجد مرفقات",
    "en": "No attachments"
  },
  "s121": {
    "ar": "لا توجد مستندات",
    "en": "No documents"
  },
  "s122": {
    "ar": "لا توجد مشاريع",
    "en": "No projects"
  },
  "s123": {
    "ar": "لوحة التحكم",
    "en": "Dashboard"
  },
  "s124": {
    "ar": "متأخرة",
    "en": "Delayed"
  },
  "s125": {
    "ar": "متابعة المشاريع",
    "en": "Project tracking"
  },
  "s126": {
    "ar": "متعثر",
    "en": "Off track"
  },
  "s127": {
    "ar": "متعثرة",
    "en": "Stalled"
  },
  "s128": {
    "ar": "متوقف",
    "en": "On hold"
  },
  "s129": {
    "ar": "مدة الإنجاز بالأيام",
    "en": "Duration in days"
  },
  "s130": {
    "ar": "مراحل",
    "en": "phases"
  },
  "s131": {
    "ar": "مراحل الدفع بالإنجليزية",
    "en": "Payment schedule in English"
  },
  "s132": {
    "ar": "مراحل الدفع بالعربية",
    "en": "Payment schedule in Arabic"
  },
  "s133": {
    "ar": "مرجع عقد المورد",
    "en": "Vendor contract reference"
  },
  "s134": {
    "ar": "مرحلة / مهمة",
    "en": "Phase / task"
  },
  "s135": {
    "ar": "مرفق أو صورة / كاميرا",
    "en": "Attachment or photo / camera"
  },
  "s136": {
    "ar": "مرفقات المشروع",
    "en": "Project attachments"
  },
  "s137": {
    "ar": "مستخلص المقاول",
    "en": "Contractor invoice"
  },
  "s138": {
    "ar": "مشاريع أبروج",
    "en": "Abroj Projects"
  },
  "s139": {
    "ar": "مشروع",
    "en": "projects"
  },
  "s140": {
    "ar": "مصروف مشروع",
    "en": "Project expense"
  },
  "s141": {
    "ar": "معالجة الفاتورة",
    "en": "Invoice treatment"
  },
  "s142": {
    "ar": "معرّض للخطر",
    "en": "At risk"
  },
  "s143": {
    "ar": "مقطوعية",
    "en": "Lump sum"
  },
  "s144": {
    "ar": "مكتمل",
    "en": "Done"
  },
  "s145": {
    "ar": "مكتملة",
    "en": "Completed"
  },
  "s146": {
    "ar": "ملاحظات",
    "en": "Notes"
  },
  "s147": {
    "ar": "ملاحظة",
    "en": "Note"
  },
  "s148": {
    "ar": "ملاحظة صوتية",
    "en": "Voice note"
  },
  "s149": {
    "ar": "ملخص المشاريع",
    "en": "Project overview"
  },
  "s150": {
    "ar": "مواد باسم أبروج",
    "en": "Materials in Abroj's name"
  },
  "s151": {
    "ar": "مواد باسم المقاول",
    "en": "Materials in contractor's name"
  },
  "s152": {
    "ar": "نسبة الإنجاز",
    "en": "Progress"
  },
  "s153": {
    "ar": "نسبة الضريبة",
    "en": "Tax percentage"
  },
  "s154": {
    "ar": "نسبة الضمان",
    "en": "Retention percentage"
  },
  "s155": {
    "ar": "نص الملاحظة",
    "en": "Note text"
  },
  "s156": {
    "ar": "نطاق العمل",
    "en": "Scope of work"
  },
  "s157": {
    "ar": "نقداً",
    "en": "Cash"
  },
  "s158": {
    "ar": "نوع العقد",
    "en": "Contract type"
  },
  "s159": {
    "ar": "نوع القيمة",
    "en": "Value type"
  },
  "s160": {
    "ar": "نوع المشروع",
    "en": "Project type"
  },
  "s161": {
    "ar": "هدف المشروع بالإنجليزية",
    "en": "Project goal in English"
  },
  "s162": {
    "ar": "هدف المشروع بالعربية",
    "en": "Project goal in Arabic"
  },
  "s163": {
    "ar": "يوم",
    "en": "days"
  },
  "myDay": {"ar": "مهامي اليوم", "en": "My Day"},
  "myDayEmpty": {"ar": "لا توجد مراحل لهذا اليوم", "en": "No phases for today"},
  "assignee": {"ar": "المسؤول", "en": "Assignee"},
  "unassigned": {"ar": "غير معيّن", "en": "Unassigned"},
  "english": {"ar": "English", "en": "English"},
  "logout": {"ar": "تسجيل الخروج", "en": "Log out"},
  "sessionExpired": {"ar": "انتهت الجلسة", "en": "Session expired"},
  "menu": {"ar": "القائمة", "en": "Menu"},
  "switchLanguage": {"ar": "تغيير اللغة", "en": "Change language"},
  "arabic": {"ar": "العربية", "en": "العربية"},
  "languageError": {"ar": "تعذر تغيير اللغة.", "en": "Could not change language."},
  "state_": {"ar": "", "en": ""},
  "state_draft": {"ar": "مسودة", "en": "Draft"},
  "state_issued": {"ar": "صادر", "en": "Issued"},
  "state_paid": {"ar": "مدفوع", "en": "Paid"},
  "state_cancelled": {"ar": "ملغي", "en": "Cancelled"},
  "state_cancel": {"ar": "ملغي", "en": "Cancelled"},
  "state_confirmed": {"ar": "معتمد", "en": "Confirmed"}
};

const mediaText={gallery:['اختيار صور وملفات','Choose photos and files'],native:['كاميرا الجهاز','Device camera'],switch:['تبديل الكاميرا','Switch camera'],flash:['الفلاش','Torch'],capture:['التقاط','Capture'],retry:['إعادة المحاولة','Retry'],queued:['بانتظار الاتصال','Waiting for connection'],uploading:['جارٍ الرفع','Uploading'],done:['تم الرفع','Uploaded'],failed:['فشل الرفع','Upload failed'],record:['بدء التسجيل','Start recording'],pause:['إيقاف مؤقت','Pause'],resume:['استئناف','Resume'],stop:['إيقاف','Stop'],discard:['حذف وإعادة التسجيل','Discard and record again'],save:['حفظ التسجيل','Save recording'],preview:['معاينة التسجيل','Recording preview']};
Object.entries(mediaText).forEach(([key,value])=>translations['media_'+key]={ar:value[0],en:value[1]});

Object.entries({voiceTitle:['تسجيل صوتي','Voice recording'],microphone:['الميكروفون','Microphone'],camera:['الكاميرا','Camera'],insecure:['يلزم اتصال آمن HTTPS لاستخدام هذا الجهاز.','A secure HTTPS connection is required.'],unsupported:['المتصفح لا يدعم هذه الميزة.','This browser does not support this feature.'],denied:['لم يتم السماح بالوصول.','Access was denied.'],deviceError:['تعذر الوصول إلى الجهاز. تحقق من توصيله وأعد المحاولة.','Could not access the device. Check it and try again.'],androidMic:['في Chrome على Android: اضغط رمز القفل ← الأذونات ← الميكروفون ← السماح.','Chrome on Android: tap the lock icon → Permissions → Microphone → Allow.'],androidCamera:['في Chrome على Android: اضغط رمز القفل ← الأذونات ← الكاميرا ← السماح.','Chrome on Android: tap the lock icon → Permissions → Camera → Allow.'],iosMic:['في iOS: الإعدادات ← Safari ← الميكروفون ← سماح.','On iOS: Settings → Safari → Microphone → Allow.'],iosCamera:['في iOS: الإعدادات ← Safari ← الكاميرا ← سماح.','On iOS: Settings → Safari → Camera → Allow.'],close:['إغلاق','Close'],cancel:['إلغاء','Cancel'],delete:['حذف','Delete'],send:['إرسال','Send'],retake:['إعادة الالتقاط','Retake'],holdRecord:['اضغط مطوّلاً للتسجيل','Press and hold to record'],slideCancel:['اسحب للإلغاء','Slide to cancel']}).forEach(([key,value])=>translations['media_'+key]={ar:value[0],en:value[1]});

Object.entries({choosePhotos:['اختيار الصور','Choose photos'],photoPreview:['معاينة الصورة','Photo preview'],addPhoto:['إضافة صورة','Add photo'],caption:['أضف وصفاً…','Add a caption…'],zoom:['التكبير','Zoom']}).forEach(([key,value])=>translations['media_'+key]={ar:value[0],en:value[1]});
