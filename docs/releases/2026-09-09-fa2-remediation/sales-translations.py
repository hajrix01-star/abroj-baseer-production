assert env.cr.dbname == 'baseer_fix_sales_20260909'
import io, json
from pathlib import Path
import polib
from odoo.tools.translate import trans_export
translations={
'Cancelled for correction':'ملغى للتصحيح',
'Reviewed sales summary correction':'تصحيح ملخص المبيعات بعد المراجعة',
'Only the correction creator can use this request.':'يمكن لمن أنشأ طلب التصحيح فقط استخدامه.',
'Replacement sales summary':'ملخص المبيعات البديل',
'Only an approved summary can be corrected.':'يمكن تصحيح ملخص معتمد فقط.',
'Enter a correction reason of at most 2000 characters.':'أدخل سبب التصحيح بما لا يتجاوز 2000 حرف.',
'The original summary accounting is incomplete; review it before correction.':'القيود الأصلية للملخص غير مكتملة؛ راجعها قبل التصحيح.',
'An original entry is no longer posted or already has a reversal. Review the previous receipt or accounting correction before correcting sales.':'أحد القيود الأصلية غير مرحّل أو سبق عكسه. راجع تصحيح الإيصال أو القيد السابق قبل تصحيح المبيعات.',
'External settlements are linked to this summary. Review and undo those settlements using their original accounting workflow before correcting sales.':'توجد تسويات خارجية مرتبطة بهذا الملخص. راجع تلك التسويات وألغِ مطابقتها من مسارها المحاسبي الأصلي قبل تصحيح المبيعات.',
'Correction of %s: %s':'تصحيح %s: %s',
'The native correction entries did not reverse the original summary exactly.':'لم تعكس قيود التصحيح الأصلية مبالغ الملخص بالكامل وبالدقة المطلوبة.',
'Review replacement sales summary':'مراجعة ملخص المبيعات البديل',
'Summary journal evidence cannot be edited, reset or deleted. Use Correct summary from its original sales summary.':'لا يمكن تعديل قيود الملخص أو إعادتها إلى مسودة أو حذفها. استخدم «تصحيح الملخص» من ملخص المبيعات الأصلي.',
'Summary accounting ownership is controlled by the server.':'يتحكم الخادم بروابط ملكية قيود الملخص.',
'Use Correct summary to reverse sales. Only an unreversed original receipt can be reversed separately.':'استخدم «تصحيح الملخص» لعكس المبيعات. يمكن عكس إيصال أصلي لم يُعكس سابقًا بصورة مستقلة فقط.',
'Reverse summary receipts one company at a time.':'اعكس إيصالات الملخص لشركة واحدة في كل مرة.',
'Summary receipt links are controlled by the server.':'يتحكم الخادم بروابط إيصالات الملخص.',
'Summary correction history is controlled by the server.':'يتحكم الخادم بسجل تصحيح الملخص.',
'A replacement must retain the original sales date and shift.':'يجب أن يحتفظ البديل بتاريخ المبيعات والفترة الأصليين.',
'A correction replacement must be retained for review and audit.':'يجب الاحتفاظ ببديل التصحيح للمراجعة والتدقيق.',
'Only a fully reversed summary correction may cancel its retained POS order.':'لا يمكن إلغاء طلب نقطة البيع المحفوظ إلا بعد عكس جميع قيود الملخص بالكامل ضمن التصحيح.',
'The dedicated summary product must be a service. Use a separate product for stock operations.':'يجب أن يكون منتج الملخص المخصص خدمة. استخدم منتجًا منفصلًا لعمليات المخزون.',
'The dedicated summary product must remain a service. Assign a separate summary service before changing its type.':'يجب أن يبقى منتج الملخص المخصص خدمة. عيّن خدمة مستقلة للملخص قبل تغيير نوعه.',
'%s — summary service':'%s — خدمة الملخص',
'Choose whether a day has a missing shift.':'اختر ما إذا كان اليوم يتضمن فترة ناقصة.',
'The missing-shift filter supports at most 5000 saved dates. Use the daily report for a bounded period.':'يدعم مرشح الفترة الناقصة 5000 تاريخ محفوظ كحد أقصى. استخدم التقرير اليومي لفترة محددة.',
'Operating closures':'فترات الإغلاق',
'Closures':'الإغلاقات',
'Correct sales summary':'تصحيح ملخص المبيعات',
'Correct summary':'تصحيح الملخص',
'Correction history':'سجل التصحيح',
'Reverse and prepare replacement':'عكس القيود وإعداد البديل',
'The original entries will be reversed on the sales date and retained. A linked replacement draft will open for review and approval. Closed periods and external settlements must be reviewed first.':'ستُعكس القيود الأصلية بتاريخ المبيعات مع الاحتفاظ بها. سيُفتح بديل مرتبط في حالة مسودة للمراجعة والاعتماد. يجب مراجعة الفترات المقفلة والتسويات الخارجية أولًا.',
'Correction Reason':'سبب التصحيح',
'Corrected By':'صحّح بواسطة',
'Corrected At':'تاريخ التصحيح',
'Replacement':'البديل',
'Replaces':'بديل عن',
'Reversal Move':'قيود العكس',
'Baseer Pos Summary':'ملخص مبيعات بصير',
'Reason':'السبب',
'Summary':'الملخص',
}
buffer=io.BytesIO();trans_export('ar_001',['baseer_pos_summary'],buffer,'po',env)
catalog=polib.pofile(buffer.getvalue().decode('utf-8'))
applied=[]
for message in catalog:
    if message.msgid in translations:message.msgstr=translations[message.msgid];applied.append(message.msgid)
Path('/mnt/qa-evidence/sales-ar.po').write_text(str(catalog),encoding='utf-8')
Path('/mnt/qa-evidence/sales-translations.json').write_text(json.dumps({'applied':applied,'missing_mapping_in_export':sorted(set(translations)-set(applied))},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'applied':len(applied),'missing_mapping_in_export':sorted(set(translations)-set(applied))}))
env.cr.rollback()
