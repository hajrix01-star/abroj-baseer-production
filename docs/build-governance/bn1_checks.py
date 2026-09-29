"""Execute in Odoo shell on QA only; all test writes are rolled back."""
import json
import time
import uuid
from pathlib import Path
from lxml import etree
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_service_seed.models.res_partner import legacy_name_parts

assert env.cr.dbname == 'baseer_reports_qa_20260907'
checks = []
def check(name, condition):
    assert condition, name
    checks.append(name)

token = uuid.uuid4().hex[:8]
P = env['res.partner']
C = env['res.company']
try:
    p = P.create({'baseer_name_ar': '  مورد ' + token + '  ', 'baseer_name_en': ' Supplier ' + token + ' ', 'supplier_rank': 1})
    check('supplier compose trimmed', p.name == 'مورد ' + token + ' | Supplier ' + token)
    for term in ('مورد ' + token, 'Supplier ' + token):
        check('native supplier search ' + term, p.id in [r[0] for r in P.name_search(term)])
    p.write({'baseer_name_en': 'New ' + token})
    check('supplier partial edit', p.name == 'مورد ' + token + ' | New ' + token)
    p.write({'baseer_name_en': False})
    check('single language no separator', p.name == 'مورد ' + token)
    try:
        with env.cr.savepoint(): p.write({'baseer_name_ar': False})
    except ValidationError:
        check('reject clearing final name', True)
    else: raise AssertionError('empty name accepted')
    p.write({'name': 'External ' + token})
    check('native rename components stay coherent', p.baseer_name_en == p.name and not p.baseer_name_ar)
    p.write({'baseer_name_ar': 'مورد جديد'})
    check('component edit after native rename', p.name == 'مورد جديد | External ' + token)
    copy = p.copy()
    check('native copy compatible', copy.name != p.name and not copy.baseer_name_ar and not copy.baseer_name_en)
    person = P.create({'name': 'Ordinary ' + token})
    person.write({'name': 'Renamed ' + token})
    check('ordinary contact remains native', person.name == 'Renamed ' + token and not person.baseer_name_ar)
    legacy = P.create({'name': 'قديم ' + token, 'supplier_rank': 1})
    invoice = env['account.move'].create({'move_type': 'in_invoice', 'partner_id': legacy.id})
    env.flush_all()
    env.cr.execute('SELECT row_to_json(m) FROM account_move m WHERE id=%s', [invoice.id])
    invoice_before = env.cr.fetchone()[0]
    legacy._baseer_initialize_name_parts()
    env.flush_all()
    env.cr.execute('SELECT row_to_json(m) FROM account_move m WHERE id=%s', [invoice.id])
    check('backfill leaves invoice and audit metadata untouched', env.cr.fetchone()[0] == invoice_before)
    oldname = legacy.name
    legacy._baseer_initialize_name_parts()
    check('backfill idempotent and preserves name', legacy.name == oldname and legacy.baseer_name_ar == oldname)
    reverse = legacy_name_parts('English | اسم')
    check('ambiguous legacy not mislabeled', reverse['baseer_name_ar'] == 'English | اسم' and not reverse['baseer_name_en'])
    for vals in ({'baseer_name_ar': 'شركة ' + token}, {'baseer_name_en': 'Company ' + token}, {'baseer_name_ar': 'ثنائية ' + token, 'baseer_name_en': 'Bilingual ' + token}):
        c = C.create(vals)
        check('company create no native name ' + c.name, c.name == c.partner_id.name and c.baseer_name_ar == c.partner_id.baseer_name_ar and c.baseer_name_en == c.partner_id.baseer_name_en)
    for term in ('ثنائية ' + token, 'Bilingual ' + token):
        check('native company search ' + term, c.id in [r[0] for r in C.name_search(term)])
    collision = C.create({'name': 'تعارض ' + token})
    native = C.create({'name': 'Native ' + token, 'baseer_name_ar': False, 'baseer_name_en': False})
    check('native company create with blank optional fields', native.name == 'Native ' + token)
    c.write({'baseer_name_ar': collision.name, 'baseer_name_en': 'Final ' + token})
    env.flush_all()
    check('company batched inverse avoids intermediate collision', c.name == collision.name + ' | Final ' + token)
    c.partner_id.write({'baseer_name_en': 'Partner ' + token})
    check('contact edit updates company', c.name == collision.name + ' | Partner ' + token)
    c.write({'baseer_name_ar': False})
    check('company clearing one component', c.name == 'Partner ' + token)
    try:
        with env.cr.savepoint(): c.write({'baseer_name_en': False})
    except ValidationError: check('company rejects empty identity', True)
    else: raise AssertionError('empty company name accepted')
    linked = P.create({'name': 'Linked ' + token, 'is_company': True})
    lc = C.create({'partner_id': linked.id, 'baseer_name_ar': 'مرتبطة ' + token, 'baseer_name_en': 'Linked company ' + token})
    check('company create with existing partner', lc.partner_id == linked and lc.name == linked.name)
    replacement = P.create({'name': 'Replacement ' + token, 'is_company': True})
    lc.write({'partner_id': replacement.id, 'baseer_name_ar': 'بديلة ' + token, 'baseer_name_en': 'Replacement company ' + token})
    check('company partner replacement plus names', lc.partner_id == replacement and lc.name == replacement.name == 'بديلة ' + token + ' | Replacement company ' + token)
    internal = env['res.users'].create({'name': 'BN1 Internal', 'login': 'bn1-' + token, 'group_ids': [(6, 0, [env.ref('base.group_user').id])]})
    try:
        with env.cr.savepoint(): c.with_user(internal).write({'baseer_name_ar': 'Not allowed'})
    except AccessError: check('company write requires native access', True)
    else: raise AssertionError('company access bypass')
    for lang in ('en_US', 'ar_001'):
        for model, ref in ((P, 'base.view_partner_form'), (C, 'base.view_company_form')):
            arch = etree.fromstring(model.with_context(lang=lang).get_view(env.ref(ref).id, 'form')['arch'])
            check('two language fields ' + ref + lang, len(arch.xpath("//field[@name='baseer_name_ar']")) == 1 and len(arch.xpath("//field[@name='baseer_name_en']")) == 1)
            titles = arch.xpath("//h1/field[@name='name']")
            check('all native titles protected ' + ref + lang, all('baseer_name_ar' in t.get('readonly','') for t in titles))
    start = time.perf_counter()
    for i in range(50):
        P.name_search('Supplier', limit=20)
    check('bounded native search timings recorded', True)
    result = {'passed': len(checks), 'checks': checks, 'fifty_searches_seconds': round(time.perf_counter() - start, 3), 'rolled_back': True}
finally:
    env.cr.rollback()
Path('/mnt/qa-evidence/bn1-results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
