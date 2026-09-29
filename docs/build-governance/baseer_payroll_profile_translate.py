"""Merge new EOS translations against Odoo's actual exported source references."""
import io, json, polib
from pathlib import Path
from odoo.tools.translate import trans_export
buffer=io.BytesIO()
trans_export('ar_001',['baseer_payroll'],buffer,'po',env)
export=polib.pofile(buffer.getvalue().decode('utf-8'))
current=polib.pofile('/mnt/baseer-addons/baseer_payroll/i18n/ar.po')
extra=polib.pofile('/mnt/qa-evidence/end_service_ar.po.txt')
translations={entry.msgid:entry.msgstr for entry in extra}
missing=[]
for source in export:
    relevant=any('end_service' in location or 'baseer_eos' in location or 'baseer_hr_eos' in location for location,_ in source.occurrences)
    if not relevant:continue
    found=current.find(source.msgid)
    translated=translations.get(source.msgid) or (found.msgstr if found else '') or source.msgstr
    if not translated:
        missing.append(source.msgid)
        continue
    if found:
        found.occurrences=sorted(set(found.occurrences+source.occurrences))
        found.msgstr=translated
        found.comment='\n'.join(dict.fromkeys((found.comment+'\n'+source.comment).strip().splitlines()))
    else:
        source.msgstr=translated
        current.append(source)
current.save('/mnt/qa-evidence/baseer_payroll_profile_ar.po')
Path('/mnt/qa-evidence/baseer_payroll_profile_translation.json').write_text(json.dumps({'missing':missing,'entries':len(current)},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'missing':missing,'entries':len(current)},ensure_ascii=False))
env.cr.rollback()
