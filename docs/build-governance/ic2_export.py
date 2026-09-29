"""Read-only native template export and translation merge for the two IC2 addons."""
import json
import re
from pathlib import Path
import polib
from odoo.tools.translate import trans_export

_RUNTIME_SEED = re.compile(r'^model:[^:]+:baseer_pos_summary\.payment_seed_.+_company_\d+$')


def static_terms(catalog):
    """Exclude company business-record translations from distributable UI terms."""
    for entry in list(catalog):
        original = entry.occurrences
        entry.occurrences = [item for item in original if not _RUNTIME_SEED.match(item[0])]
        if original and not entry.occurrences:
            catalog.remove(entry)
    return catalog

assert env.cr.dbname == 'baseer_ic1_20260910'
root = Path('/mnt/qa-evidence')
fragment = polib.pofile(str(root / 'ic2-summary-ar.po'))
missing = {}
for module, language_file in (('baseer_financial_correction', 'ar_001.po'), ('baseer_pos_summary', 'ar.po')):
    template = root / ('ic2-' + module + '.pot')
    with template.open('wb') as stream:
        trans_export(None, [module], stream, 'po', env)
    original = static_terms(polib.pofile('/mnt/ic1-addons/' + module + '/i18n/' + language_file))
    translations = {e.msgid: e.msgstr for e in original if e.msgstr}
    translations.update({e.msgid: e.msgstr for e in fragment if e.msgstr})
    fixes = root / 'ic2-translation-fixes.json'
    if fixes.exists():
        translations.update(json.loads(fixes.read_text(encoding='utf8')))
    output = static_terms(polib.pofile(str(template)))
    output.metadata.update({'Language': 'ar_001', 'Content-Type': 'text/plain; charset=UTF-8'})
    for entry in output:
        entry.msgstr = translations.get(entry.msgid, '')
        if entry.msgstr:
            assert entry.msgid.count('%s') == entry.msgstr.count('%s'), entry.msgid
        entry.flags = [flag for flag in entry.flags if flag != 'fuzzy']
    missing[module] = [entry.msgid for entry in output if not entry.msgstr]
    exported = {entry.msgid for entry in output}
    # Keep older native terms too; updating this feature must not discard
    # translations used by another existing summary screen.
    for entry in original:
        if entry.msgid not in exported:
            output.append(entry)
    output.save(str(root / ('ic2-' + module + '.po')))
env.cr.rollback()
(root / 'ic2-translation-missing.json').write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding='utf8')
print(json.dumps(missing, ensure_ascii=False))
