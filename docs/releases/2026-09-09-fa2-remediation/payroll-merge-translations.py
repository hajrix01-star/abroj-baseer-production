"""Append/refresh only approved FA2 translation entries from the native PO export."""
import ast,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[3]
out=Path(__file__).parent
mapping=json.loads((out/'payroll-translations.json').read_text(encoding='utf-8'))
def msg(block):
    fields={};field=None
    for line in block.splitlines():
        if line.startswith(('msgid ','msgstr ')):
            field,value=line.split(' ',1);fields[field]=ast.literal_eval(value)
        elif line.startswith('"') and field:fields[field]+=ast.literal_eval(line)
    return fields
export=(out/'payroll-runtime/payroll-export-ar.po').read_text(encoding='utf-8')
path=root/'custom_addons/baseer_payroll/i18n/ar.po'
existing=path.read_text(encoding='utf-8')
blocks=existing.split('\n\n');indices={msg(block).get('msgid'):i for i,block in enumerate(blocks)}
matched=set()
for block in export.split('\n\n'):
    ident=msg(block).get('msgid')
    if ident not in mapping:continue
    matched.add(ident)
    body=re.sub(r'msgstr ""(?:\n"[^\n]*")*|msgstr "[^\n]*"',lambda _: 'msgstr '+json.dumps(mapping[ident],ensure_ascii=False),block)
    if ident in indices:blocks[indices[ident]]=body
    else:blocks.append(body)
assert not mapping.keys()-matched,mapping.keys()-matched
path.write_text('\n\n'.join(blocks).rstrip()+'\n',encoding='utf-8')
print('FA2 translated',len(matched))
