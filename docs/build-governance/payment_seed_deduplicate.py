"""Explicit user-authorized cleanup of unused legacy ARZ payment duplicates."""
import json
from odoo.addons.baseer_pos_summary.models.day_entry import PosDayEntryLine
from psycopg2 import sql

assert env.cr.dbname == 'baseer_dev'
co=env['res.company'].browse(1)
scoped=env(user=env.ref('base.user_admin').id,context=dict(env.context,allowed_company_ids=co.ids))
co=scoped['res.company'].browse(co.id)
config=co._baseer_pos_identity('config','pos.config')
cash=co._baseer_pos_identity('method_cash','pos.payment.method')
bank=co._baseer_pos_identity('method_bank','pos.payment.method')
legacy=scoped['pos.payment.method'].browse(1).exists()
assert legacy and legacy.company_id==co and not legacy.config_ids
assert legacy.baseer_category_id.kind=='cash' and cash in config.payment_method_ids
assert not scoped['pos.payment'].search_count([('payment_method_id','=',legacy.id)])
assert not scoped['baseer.pos.summary.allocation'].search_count([('payment_method_id','=',legacy.id)])
def financial_fingerprint():
    result={}
    scoped.flush_all()
    for table in ('account_move','account_move_line','account_payment','pos_order','pos_order_line','pos_payment','pos_session','hr_employee','hr_version'):
        scoped.cr.execute(sql.SQL("SELECT md5(coalesce(string_agg(row_to_json(t)::text,'' ORDER BY id),'')) FROM {} t").format(sql.Identifier(table)))
        result[table]=scoped.cr.fetchone()[0]
    return result
before=financial_fingerprint()
lines=scoped['baseer.pos.day.entry.line'].search([('payment_method_id','in',[1,2]),('entry_id.config_id','=',config.id)])
entries=lines.entry_id
entries._lock()
entries._require_draft()
assert all(not e.saved_summary_ids and e.company_id==co for e in entries)
amounts={line.id:line.amount for line in lines}
relinked=[]
for old,new in ((1,cash),(2,bank)):
    target=lines.filtered(lambda line:line.payment_method_id.id==old)
    # Controlled atomic transient migration: validate the complete mapping below,
    # rather than rejecting the intermediate state while another old slot remains.
    super(PosDayEntryLine,target).write({'payment_method_id':new.id})
    relinked += [{'line':line.id,'from':old,'to':new.id,'amount':line.amount} for line in target]
entries._validate_lines()
assert {line.id:line.amount for line in lines}==amounts
scoped.cr.execute("SELECT c.conrelid::regclass::text,a.attname FROM pg_constraint c JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1] WHERE c.contype='f' AND c.confrelid='pos_payment_method'::regclass")
for table,column in scoped.cr.fetchall():
    scoped.cr.execute(sql.SQL('SELECT count(*) FROM {} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(column)),[legacy.id])
    assert scoped.cr.fetchone()[0]==0,(table,column)
removed_name=legacy.name
legacy.unlink()
# Ordinary POS card keeps its native accounting; it no longer needs obsolete
# summary-only classification now that dedicated summary methods exist.
card=scoped['pos.payment.method'].browse(2)
assert card.company_id==co and card.config_ids and not any(card.config_ids.mapped('baseer_summary_only'))
assert not scoped['baseer.pos.summary.allocation'].search_count([('payment_method_id','=',card.id)])
card.write({'baseer_category_id':False})
categories=scoped['baseer.pos.payment.category'].browse([1,2,3]).exists()
assert len(categories)==3 and all(c.company_id==co for c in categories)
assert not scoped['pos.payment.method'].with_context(active_test=False).search_count([('baseer_category_id','in',categories.ids)])
assert not scoped['baseer.pos.summary.allocation'].search_count([('category_id','in',categories.ids)])
removed_categories=[{'id':c.id,'name':c.name} for c in categories]
categories.unlink()
config._validate_baseer_setup()
assert len(config.payment_method_ids)==5
assert before==financial_fingerprint()
scoped.cr.commit()
print('DEDUPE_RESULT='+json.dumps({'removed_method':{'id':1,'name':removed_name},'removed_categories':removed_categories,
    'relinked_unapproved_slots':relinked,'amounts_preserved':True,'financial_and_hr_unchanged':True,
    'ordinary_card_and_customer_account_retained':True},ensure_ascii=False))
