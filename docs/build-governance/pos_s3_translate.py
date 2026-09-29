"""Translate the single daily archive and one-step save flow for POS-S3."""
from pathlib import Path
import polib

path = Path('/mnt/qa-evidence/pos_s3_ar.po')
po = polib.pofile(str(path))
translations = {
    'A scheduled shift has not been recorded. Its absence does not mean zero sales. Review the shift details.': 'لم يُسجّل أحد الشفتات المقررة. عدم تسجيله لا يعني أن مبيعاته صفر. راجع تفاصيل الشفتات.',
    'Daily sales summaries': 'ملخصات المبيعات اليومية',
    'Each day appears once. Open it to view its morning and evening shifts together.': 'يظهر كل يوم مرة واحدة. افتحه لعرض شفتَي الصباح والمساء معًا.',
    'Evening sales': 'مبيعات المساء',
    'First Missing': 'الشفت الأول غير مسجل',
    'First State': 'حالة الشفت الأول',
    'Missing shift': 'شفت غير مسجل',
    'Morning sales': 'مبيعات الصباح',
    'Partly approved': 'معتمد جزئيًا',
    'Record your daily sales': 'سجّل مبيعاتك اليومية',
    'Recorded periods': 'الفترات المسجلة',
    'Sales summaries — %s': 'ملخصات المبيعات — %s',
    'Save': 'حفظ',
    'Save records and posts the sales and payments of both shifts together.': 'يحفظ الزر مبيعات ومدفوعات الشفتين ويرحّلها معًا.',
    'Second Missing': 'الشفت الثاني غير مسجل',
    'Second State': 'حالة الشفت الثاني',
    'Select the summaries of one company and one sales day.': 'اختر ملخصات شركة واحدة ويوم مبيعات واحد.',
    'Shift details': 'تفاصيل الشفتات',
    'The daily archive is read-only. Edit an original draft summary instead.': 'الأرشيف اليومي للعرض فقط. يمكن تعديل ملخص أصلي إذا كان ما زال مسودة.',
    'The daily archive is read-only. Original summaries are retained for audit.': 'الأرشيف اليومي للعرض فقط. تُحفظ الملخصات الأصلية للمراجعة والتدقيق.',
    'The daily archive is read-only. Use the sales entry form to create summaries.': 'الأرشيف اليومي للعرض فقط. استخدم نموذج إدخال المبيعات لإنشاء الملخصات.',
    'The saved shifts use different configurations. Open their source details to review them.': 'تستخدم الشفتات المحفوظة إعدادات مختلفة. افتح تفاصيلها الأصلية لمراجعتها.',
    'This day contains saved drafts. Save approves them together; shift details remain available for review.': 'يتضمن هذا اليوم مسودات محفوظة. يعتمدها زر الحفظ معًا، وتبقى تفاصيل الشفتات متاحة للمراجعة.',
    'This day no longer has sales summaries. Refresh the archive.': 'لم تعد هناك ملخصات مبيعات لهذا اليوم. حدّث الأرشيف.',
    'This shift has not been recorded.': 'لم يُسجّل هذا الشفت.',
    'Sales summaries': 'ملخصات المبيعات',
    'Sales summary': 'ملخص المبيعات',
}
before = len(po.untranslated_entries())
for entry in po:
    if entry.msgid in translations:
        entry.msgstr = translations[entry.msgid]
        entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']

# Keep the original native POS menu translation; fresh exports omit external IDs.
direct = po.find('Direct sales')
if not direct:
    direct = polib.POEntry(msgid='Direct sales', msgstr='مبيعات مباشرة', comment='module: baseer_pos_summary')
    po.append(direct)
occurrence = ('model:ir.ui.menu,name:point_of_sale.menu_pos_dashboard', '')
if occurrence not in direct.occurrences:
    direct.occurrences.append(occurrence)
assert not po.untranslated_entries(), [entry.msgid for entry in po.untranslated_entries()]
assert not po.fuzzy_entries()
po.save(str(path))
print({'missing_before': before, 'missing_after': 0, 'total': len(po),
       'single_menu': po.find('Sales summaries').msgstr,
       'single_form': po.find('Sales summary').msgstr})
