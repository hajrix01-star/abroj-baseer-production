"""User explicitly requested removal of all legacy experimental payment methods."""
import json
from psycopg2 import sql

assert env.cr.dbname=='baseer_dev'
scoped=env(user=env.ref('base.user_admin').id,context=dict(env.context,allowed_company_ids=[1]))
co=scoped['res.company'].browse(1)
methods=scoped['pos.payment.method'].browse([1,2,3]).exists()
assert len(methods)==3 and all(m.company_id==co for m in methods)
assert not methods.open_session_ids
assert not scoped['pos.payment'].search_count([('payment_method_id','in',methods.ids)])
assert not scoped['baseer.pos.summary.allocation'].search_count([('payment_method_id','in',methods.ids)])
config=co._baseer_pos_identity('config','pos.config')
assert not methods & config.payment_method_ids
def fingerprint():
    scoped.flush_all()
    result={}
    for table in ('account_move','account_move_line','account_payment','pos_order','pos_order_line','pos_payment','pos_session','hr_employee','hr_version'):
        scoped.cr.execute(sql.SQL("SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM {} t").format(sql.Identifier(table)))
        result[table]=scoped.cr.fetchone()[0]
    return result
before=fingerprint()
lines=scoped['baseer.pos.day.entry.line'].search([('payment_method_id','in',methods.ids)])
entries=lines.entry_id
entries._lock('unlink')
entries._require_draft()
assert all(e.company_id==co and not e.saved_summary_ids and not e.saved_closure_id for e in entries)
entry_ids=entries.ids
entries.unlink()
scoped.flush_all()
removed=[{'id':m.id,'name':m.name} for m in methods]
methods.unlink()
categories=scoped['baseer.pos.payment.category'].browse([1,2,3]).exists()
assert len(categories)==3 and all(c.company_id==co for c in categories)
assert not scoped['pos.payment.method'].with_context(active_test=False).search_count([('baseer_category_id','in',categories.ids)])
assert not scoped['baseer.pos.summary.allocation'].search_count([('category_id','in',categories.ids)])
category_names=[{'id':c.id,'name':c.name} for c in categories]
categories.unlink()
config._validate_baseer_setup()
assert len(config.payment_method_ids)==5
assert scoped['pos.payment.method'].search_count([('company_id','=',co.id)])==5
assert before==fingerprint()
scoped.cr.commit()
print('DEDUPE_RESULT='+json.dumps({'deleted_methods':removed,'deleted_categories':category_names,
    'deleted_experimental_draft_entries':entry_ids,'financial_and_hr_unchanged':True,
    'remaining_ARZ_methods':5,'user_authorization':'Delete them; experimental, not needed'},ensure_ascii=False))
