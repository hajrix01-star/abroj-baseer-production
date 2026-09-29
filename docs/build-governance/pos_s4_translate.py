import polib
from odoo.tools.translate import trans_export, TranslationImporter

path = '/mnt/qa-evidence/pos_s4_ar.po'
with open(path, 'wb') as handle:
    trans_export('ar_001', ['baseer_pos_summary'], handle, 'po', env)
po = polib.pofile(path)
previous = polib.pofile('/mnt/baseer-addons/baseer_pos_summary/i18n/ar.po')
translations = {
    '<span class="fw-bold fs-4 d-block">Sales summary</span>': '<span class="fw-bold fs-4 d-block">ملخص المبيعات</span>',
    'Saved summaries': 'الملخصات المحفوظة',
    'Enter summary': 'إدخال ملخص',
    'Morning, evening or DAY OFF': 'صباحي، مسائي أو إجازة',
    'Point of Sale access is required.': 'يلزم توفر صلاحية نقاط البيع.',
    'Choose an active summary configuration.': 'اختر إعدادًا مفعّلًا لملخص المبيعات.',
}
for entry in po:
    old = previous.find(entry.msgid)
    if old and old.msgstr:
        entry.msgstr = old.msgstr
    if entry.msgid in translations:
        entry.msgstr = translations[entry.msgid]
    entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']
if not po.find('Direct sales'):
    po.append(polib.POEntry(msgid='Direct sales', msgstr='مبيعات مباشرة', comment='module: baseer_pos_summary', occurrences=[('model:ir.ui.menu,name:point_of_sale.menu_pos_dashboard', '')]))
assert not po.untranslated_entries(), [e.msgid for e in po.untranslated_entries()]
po.save(path)
imp = TranslationImporter(env.cr)
with open(path, 'rb') as handle:
    imp.load(handle, 'po', 'ar_001')
imp.save(overwrite=True)
env.cr.commit()
print('S4_TRANSLATIONS_OK', len(po))
