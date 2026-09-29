"""Reviewed Arabic wording for the combined daily-entry form."""
from pathlib import Path
import polib

path = Path('/mnt/qa-evidence/pos_s2_combined_ar.po')
po = polib.pofile(str(path))
translations = {
    '<span class="text-muted">Daily customers</span>': '<span class="text-muted">عملاء اليوم</span>',
    '<span class="text-muted">Daily total including VAT</span>': '<span class="text-muted">إجمالي اليوم شامل الضريبة</span>',
    '<span>Total including VAT</span>': '<span>الإجمالي شامل الضريبة</span>',
    'A linked summary changed. Review and approve it from the sales summaries list.': 'تغيّر أحد الملخصات المرتبطة. راجعه واعتمده من قائمة الملخصات المحفوظة.',
    'All day': 'دوام كامل',
    'Amount Total': 'الإجمالي شامل الضريبة',
    'Approve all saved summaries and post their sales and payments?': 'هل تريد اعتماد جميع الملخصات المحفوظة وترحيل مبيعاتها ومدفوعاتها؟',
    'Approve summaries': 'اعتماد الملخصات',
    'Create payment slots inside a sales entry.': 'أضف مبالغ طرق الدفع من داخل شاشة إدخال المبيعات.',
    'Customer Total': 'إجمالي العملاء',
    'Customer count': 'عدد العملاء',
    'Daily sales entry': 'إدخال المبيعات اليومية',
    'Daily sales payment slot': 'مبلغ طريقة الدفع للمبيعات اليومية',
    'Day Schedule': 'نظام دوام اليوم',
    'Enter sales including VAT for each payment method.': 'أدخل المبيعات شاملة الضريبة لكل طريقة دفع.',
    'Entry': 'الإدخال',
    'Entry status, totals and summary links are controlled by the server.': 'يتولى النظام تحديث حالة الإدخال وإجمالياته وروابط الملخصات؛ لا يمكن تعديلها يدويًا.',
    'Evening shift': 'الشفت المسائي',
    'First Allocation': 'مبالغ طرق الدفع للشفت الأول',
    'First Customers': 'عملاء الشفت الأول',
    'First Notes': 'ملاحظات الشفت الأول',
    'First Total': 'إجمالي الشفت الأول',
    'First Zero Sales': 'تشغيل الشفت الأول دون مبيعات',
    'First shift': 'الشفت الأول',
    'Morning shift': 'الشفت الصباحي',
    'Only the entry creator can use this sales entry.': 'يستطيع مُنشئ الإدخال فقط استخدامه.',
    'Open saved summaries': 'فتح الملخصات المحفوظة',
    'Payment lines must remain in their own shift card.': 'يجب أن تبقى مبالغ طرق الدفع ضمن بطاقة الشفت الخاصة بها.',
    'Payment slot metadata is controlled by the server.': 'يتولى النظام ضبط بيانات طريقة الدفع المرتبطة بالمبلغ؛ لا يمكن تغييرها يدويًا.',
    'Payment slots must be created or edited within their own entry.': 'أضف مبالغ طرق الدفع أو عدّلها من داخل الإدخال الخاص بها.',
    'Save summaries': 'حفظ الملخصات',
    'Save the entry before approving its summaries.': 'احفظ الإدخال قبل اعتماد ملخصاته.',
    'Saved': 'محفوظ',
    'Saved Summary': 'الملخصات المحفوظة',
    'Saved drafts': 'مسودات محفوظة',
    'Second Allocation': 'مبالغ طرق الدفع للشفت الثاني',
    'Second Customers': 'عملاء الشفت الثاني',
    'Second Notes': 'ملاحظات الشفت الثاني',
    'Second Total': 'إجمالي الشفت الثاني',
    'Second Zero Sales': 'تشغيل الشفت الثاني دون مبيعات',
    'Second shift': 'الشفت الثاني',
    'Slot': 'الشفت',
    'The entry company and POS configuration cannot be changed.': 'لا يمكن تغيير شركة الإدخال أو إعدادات نقطة البيع المرتبطة به.',
    'The no-sales declaration must be a checkbox value.': 'يجب تفعيل خيار التشغيل دون مبيعات أو إلغاء تفعيله.',
    'The payment slot does not match its shift card.': 'طريقة الدفع لا تتوافق مع بطاقة الشفت المرتبطة بها.',
    'The summaries are saved as drafts. Approve them to post sales and payments.': 'حُفظت الملخصات كمسودات. اعتمدها لترحيل المبيعات والمدفوعات.',
    'This entry has already created its summaries and cannot be changed.': 'أُنشئت ملخصات هذا الإدخال بالفعل، ولا يمكن تغيير الإدخال.',
    'This shift operated without sales. No accounting entry will be created for it.': 'سُجّل هذا الشفت كتشغيل دون مبيعات، ولن ينشئ قيدًا محاسبيًا.',
    'Use at most 25 distinct payment methods in each shift.': 'استخدم 25 طريقة دفع مختلفة كحد أقصى لكل شفت.',
    'Use only the payment methods configured for this company.': 'استخدم طرق الدفع المضبوطة لهذه الشركة فقط.',
    'id': 'المعرّف',
    'Missing entry': 'لا يوجد ملخص معتمد',
    'Missing Days': 'أيام دون ملخص معتمد',
}
before = len(po.untranslated_entries())
for entry in po:
    if entry.msgid in translations:
        entry.msgstr = translations[entry.msgid]
        entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']

overrides = [
    ('Direct sales', 'مبيعات مباشرة', 'model:ir.ui.menu,name:point_of_sale.menu_pos_dashboard'),
    ('Saved summaries', 'الملخصات المحفوظة', 'model:ir.ui.menu,name:baseer_pos_summary.menu_summary'),
]
for source, target, reference in overrides:
    entry = po.find(source)
    if not entry:
        entry = polib.POEntry(msgid=source, msgstr=target, comment='module: baseer_pos_summary')
        po.append(entry)
    entry.msgstr = target
    if (reference, '') not in entry.occurrences:
        entry.occurrences.append((reference, ''))
assert not po.untranslated_entries(), [e.msgid for e in po.untranslated_entries()]
assert not po.fuzzy_entries()
po.save(str(path))
print({'missing_before': before, 'missing_after': 0, 'total': len(po), 'menu_overrides': 2})
