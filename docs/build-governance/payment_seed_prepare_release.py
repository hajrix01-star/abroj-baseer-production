"""Reuse accepted frozen-release backup workflow for the bounded POS seed."""
from pathlib import Path
root = Path(__file__).resolve().parents[2]
folder = root / 'docs/build-governance'
source = (folder / 'ws5_release.py').read_text(encoding='utf8')
for old, new in [('2026-09-09-unified-time-picker','NEWREL'),('unified-time-picker-20260909','NEWBACK'),
                 ('2026-09-09-pos-empty-shift','OLDREL'),('pos-empty-shift-20260909','OLDBACK')]:
    source = source.replace(old,new)
for old,new in [('NEWREL','2026-09-09-pos-payment-seed'),('NEWBACK','pos-payment-seed-20260909'),
                ('OLDREL','2026-09-09-unified-time-picker'),('OLDBACK','unified-time-picker-20260909')]:
    source = source.replace(old,new)
source = source.replace('baseer_work_schedule','baseer_pos_summary').replace('19.0.1.1.2','19.0.1.5.0')
source = source.replace('ws5-ui.json','payment-seed-checks.json')
source = source.replace('codex/unified-time-picker','codex/pos-payment-seed')
source = source.replace('Unify schedule time selection and fix narrow modal layout','Seed bilingual POS payments and platform clearing for companies')
# Master records are intentionally added and unused configuration links updated.
# Protect every existing transaction and all HR/work-schedule tables, not masters.
start = source.index('    return json.loads(b.sql(b.MAIN,',source.index('def columns():'))
end = source.index('\n\n',start)
source = source[:start] + '''    query = "SELECT json_object_agg(table_name,cols) FROM (SELECT table_name,json_agg(column_name ORDER BY ordinal_position) cols FROM information_schema.columns WHERE table_schema='public' AND (table_name LIKE 'hr_%' OR table_name LIKE 'resource_%' OR (table_name LIKE 'baseer_%' AND table_name NOT LIKE 'baseer_pos_payment_category%') OR table_name IN ('account_move','account_move_line','account_payment','account_partial_reconcile','account_full_reconcile','account_bank_statement','account_bank_statement_line','pos_order','pos_order_line','pos_payment','pos_session','res_company','res_partner')) GROUP BY table_name)t"
    return json.loads(b.sql(b.MAIN, query))''' + source[end:]
source = source.replace('Frontend time widget and styles only; no business schema or row changes',
    'Company-scoped payment/category/account/journal/product/config defaults; existing financial transactions and HR records preserved')
(folder / 'payment_seed_release.py').write_text(source,encoding='utf8')
print('Prepared release helper; MAIN unchanged')
