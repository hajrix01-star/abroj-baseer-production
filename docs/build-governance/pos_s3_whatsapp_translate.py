"""Merge verified S3 Arabic with the daily WhatsApp additions."""
import polib

path = '/mnt/qa-evidence/pos_s3_whatsapp_ar.po'
po = polib.pofile(path)
previous = polib.pofile('/mnt/baseer-addons/baseer_pos_summary/i18n/ar.po')
before = len(po.untranslated_entries())
for entry in po:
    old = previous.find(entry.msgid)
    if old and old.msgstr:
        entry.msgstr = old.msgstr
        entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']
translations = {
    'Daily collections': 'مقبوضات اليوم',
    'Daily sales summary': 'ملخص المبيعات اليومي',
    'Daily total': 'إجمالي اليوم',
    'Notes: %s': 'ملاحظات: %s',
    'Save and WhatsApp': 'حفظ وإرسال واتساب',
    'Save and approve all recorded shifts before preparing the daily WhatsApp report.': 'احفظ واعتمد جميع الشفتات المسجلة قبل تجهيز تقرير اليوم للواتساب.',
    'Some scheduled shifts have not been recorded.': 'لم تُسجّل بعض الشفتات المقررة.',
    'Sales summaries': 'ملخصات المبيعات',
    'Sales summary': 'ملخص المبيعات',
}
for entry in po:
    if entry.msgid in translations:
        entry.msgstr = translations[entry.msgid]
        entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']
if not po.find('Direct sales'):
    po.append(polib.POEntry(msgid='Direct sales', msgstr='مبيعات مباشرة',
                           comment='module: baseer_pos_summary',
                           occurrences=[('model:ir.ui.menu,name:point_of_sale.menu_pos_dashboard', '')]))
assert not po.untranslated_entries(), [entry.msgid for entry in po.untranslated_entries()]
assert not po.fuzzy_entries()
po.save(path)
print({'missing_before': before, 'missing_after': 0, 'total': len(po)})
