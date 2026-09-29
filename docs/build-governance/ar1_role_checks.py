"""AR1 isolated Odoo integration checks. Run through Odoo shell; never MAIN.

Every fixture and seeded update is rolled back, including on assertion failure.
Evidence contains check labels and timings, not employee/customer data.
"""
import hashlib
import json
import traceback
from decimal import Decimal
from pathlib import Path
from time import perf_counter

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError

assert env.cr.dbname.startswith('baseer_ar1_'), 'AR1 checks require an isolated baseer_ar1_ database'
assert env.su, 'Run isolated checks with Odoo shell administrative environment'

checks, timings = [], []
result = {'status': 'FAIL', 'checks': checks, 'timings': timings, 'rollback': False}
OUT = Path('/mnt/qa-evidence/ar1-role-checks.json')
PREFIX = 'AR1 ROLLBACK '


def check(label, condition):
    assert condition, label
    checks.append(label)


def deny(label, call, exceptions=(AccessError,)):
    try:
        with env.cr.savepoint():
            call()
    except exceptions:
        checks.append(label)
    else:
        raise AssertionError(label + ': access unexpectedly allowed')


def deny_report(label, call):
    """QWeb wraps the underlying AccessError; never accept unrelated failures."""
    try:
        with env.cr.savepoint():
            call()
    except Exception as error:
        cursor, seen = error, set()
        while cursor is not None and id(cursor) not in seen:
            if isinstance(cursor, AccessError):
                checks.append(label)
                return
            seen.add(id(cursor))
            cursor = cursor.__cause__ or cursor.__context__
        raise
    raise AssertionError(label + ': report unexpectedly rendered')


def cents(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))


def native_counts():
    return {model: env[model].search_count([]) for model in (
        'res.users', 'baseer.purchase.batch', 'baseer.purchase.batch.line',
        'account.move', 'account.move.line', 'account.payment')}


def users_stamp():
    rows = env['res.users'].with_context(active_test=False).search([]).read(
        ['baseer_access_role', 'group_ids', 'company_id', 'company_ids'])
    payload = json.dumps(rows, sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def user_env(user, company):
    scoped = env(user=user.id, su=False, context={
        'allowed_company_ids': company.ids, 'lang': 'en_US', 'tz': 'Asia/Riyadh',
        'tracking_disable': True, 'mail_create_nolog': True,
    })
    assert not scoped.su
    return scoped


def make_user(label, role, company):
    return env['res.users'].with_context(no_reset_password=True).create({
        'name': PREFIX + label, 'login': 'ar1-rollback-' + label,
        'company_id': company.id, 'company_ids': [Command.set(company.ids)],
        'baseer_access_role': role,
    })


try:
    before = native_counts()
    existing_users = users_stamp()
    env['baseer.access.role.seed']._setup_roles()
    env['baseer.access.role.seed']._setup_roles()
    check('seed repeat leaves all existing user roles, groups and companies unchanged', users_stamp() == existing_users)
    check('three role groups resolve once', len({env.ref('baseer_access_roles.group_' + key).id for key in ('owner', 'accountant', 'cashier')}) == 3)

    mappings = env['baseer.purchase.category.map'].search([('active', '=', True)])
    mapping = mappings.filtered(lambda row: row.company_id.currency_id.name == 'SAR' and row.product_id.active)[:1]
    assert mapping, 'Isolated clone needs an existing active SAR purchase category mapping'
    company = mapping.company_id
    other = env['res.company'].search([('id', '!=', company.id), ('currency_id', '=', company.currency_id.id)], limit=1)
    assert other, 'Isolated clone needs a second company for denial checks'
    local_admin = env(context={'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True})
    account = lambda kind: local_admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', kind)], limit=1)
    supplier = local_admin['res.partner'].create({
        'name': PREFIX + 'supplier', 'company_id': company.id,
        'property_account_payable_id': account('liability_payable').id,
        'property_account_receivable_id': account('asset_receivable').id,
    })
    tax = company.account_purchase_tax_id
    assert tax and tax.active and tax.amount == 15, 'Fixture company needs its seeded default purchase VAT'

    started = perf_counter()
    first = make_user('cashier-a', 'cashier', company)
    second = make_user('cashier-b', 'cashier', company)
    accountant = make_user('accountant', 'accountant', company)
    owner = make_user('owner', 'owner', company)
    timings.append({'operation': 'create_four_role_users', 'seconds': round(perf_counter() - started, 4)})
    a, b, acc, own = (user_env(user, company) for user in (first, second, accountant, owner))
    check('owner grants every current company', set(owner.company_ids.ids) == set(env['res.company'].search([]).ids))
    check('owner has settings and core application administration', all(own.user.has_group(ref) for ref in (
        'base.group_system', 'account.group_account_manager', 'purchase.group_purchase_manager',
        'point_of_sale.group_pos_manager', 'sales_team.group_sale_manager')))
    check('cashier has POS but no general invoice rights', a.user.has_group('point_of_sale.group_pos_user') and not a.user.has_group('account.group_account_invoice'))
    check('accountant has four workflow groups', all(acc.user.has_group(ref) for ref in (
        'account.group_account_invoice', 'purchase.group_purchase_manager',
        'point_of_sale.group_pos_user', 'sales_team.group_sale_salesman_all_leads')))
    check('accountant is not system or POS administrator', not acc.user.has_group('base.group_system') and not acc.user.has_group('point_of_sale.group_pos_manager'))

    serial = 0
    def row(**extra):
        global serial
        serial += 1
        value = {'partner_id': supplier.id, 'invoice_date': fields.Date.today(),
                 'supplier_ref': PREFIX + str(serial), 'category_map_id': mapping.id,
                 'gross_amount': 115, 'vat_enabled': True, 'is_credit': True}
        value.update(extra)
        return value

    def batch(actor, **extra):
        vals = {'company_id': company.id, 'line_ids': [Command.create(row())]}
        vals.update(extra)
        return actor['baseer.purchase.batch'].create(vals)

    first_batch = batch(a)
    second_batch = batch(b)
    check('cashier saves own native-tax draft', first_batch.state == 'draft' and cents(first_batch.amount_gross) == Decimal('115.00') and cents(first_batch.amount_tax) == Decimal('15.00'))
    check('draft has no accounting document', not first_batch.sudo().line_ids.move_id)
    first_batch.line_ids.write({'description': 'Updated own draft'})
    check('cashier can edit own draft row', first_batch.line_ids.description == 'Updated own draft')
    check('cashier search excludes another cashier batch', second_batch.id not in a['baseer.purchase.batch'].search([]).ids)
    check('cashier line search excludes another cashier row', second_batch.line_ids.id not in a['baseer.purchase.batch.line'].search([]).ids)
    deny('other cashier batch direct read denied', lambda: a['baseer.purchase.batch'].browse(second_batch.id).read(['name']))
    deny('other cashier batch direct write denied', lambda: a['baseer.purchase.batch'].browse(second_batch.id).write({'entry_date': fields.Date.today()}))
    deny('other cashier batch unlink denied', lambda: a['baseer.purchase.batch'].browse(second_batch.id).unlink())
    deny('other cashier line direct read denied', lambda: a['baseer.purchase.batch.line'].browse(second_batch.line_ids.id).read(['supplier_ref']))
    deny('other cashier line direct write denied', lambda: a['baseer.purchase.batch.line'].browse(second_batch.line_ids.id).write({'description': 'forbidden'}))
    deny('other cashier line unlink denied', lambda: a['baseer.purchase.batch.line'].browse(second_batch.line_ids.id).unlink())
    deny('cannot append rows to other cashier batch', lambda: a['baseer.purchase.batch.line'].create(dict(row(), batch_id=second_batch.id)))
    deny('cannot create batch in unassigned company', lambda: batch(a, company_id=other.id))
    deny('forged allowed_company_ids cannot authorize another company', lambda: batch(a(context={'allowed_company_ids': other.ids}), company_id=other.id))
    deny('cashier cannot approve draft', first_batch.action_approve)
    deny('cashier cannot forge approved state', lambda: first_batch.write({'state': 'approved'}))
    deny('cashier cannot forge document link', lambda: first_batch.line_ids.write({'move_id': 1}))
    forged = batch(a, create_uid=second.id)
    check('ORM strips forged creator identity', forged.create_uid.id == first.id)
    clean_defaults = batch(a(context=dict(a.context, default_state='approved', default_approved_by_id=owner.id)))
    check('context defaults cannot forge approval', clean_defaults.state == 'draft' and not clean_defaults.approved_by_id)

    starting_moves = native_counts()
    acc_batch = acc['baseer.purchase.batch'].browse(first_batch.id)
    acc_batch.action_approve()
    bill = first_batch.sudo().line_ids.move_id
    check('accountant approves cashier batch through native invoice', bill.state == 'posted' and bill.move_type == 'in_invoice' and cents(bill.amount_total) == Decimal('115.00'))
    check('native bill net and tax retain draft quote', cents(bill.amount_untaxed) == Decimal('100.00') and cents(bill.amount_tax) == Decimal('15.00'))
    check('native bill is balanced', sum((cents(line.balance) for line in bill.line_ids), Decimal(0)) == Decimal(0))
    check('credit approval creates no payment', not first_batch.sudo().line_ids.payment_id)
    check('accountant approval retains approver audit', first_batch.sudo().approved_by_id.id == accountant.id)
    once = native_counts()
    acc_batch.action_approve()
    check('accountant repeat approval does not duplicate ledger documents', native_counts() == once)
    first_batch.invalidate_recordset()
    check('cashier reads own approved batch', first_batch.read(['name', 'state', 'amount_gross'])[0]['state'] == 'approved')
    projection = first_batch._get_print_data()
    check('cashier own approved print includes only own fixed batch rows', projection['name'] == first_batch.name and len(projection['rows']) == 1 and projection['rows'][0]['invoice'] == bill.name)
    check('cashier can request own batch report', first_batch.action_print()['type'] == 'ir.actions.report')
    read_spec = {'id': {}, 'supplier_ref': {}, 'baseer_bill_reference': {}}
    own_line = first_batch.line_ids.web_read(read_spec)
    check('cashier own approved line web_read returns safe bill reference',
          len(own_line) == 1 and own_line[0]['baseer_bill_reference'] == bill.name)
    deny('other cashier approved line web_read denied',
         lambda: b['baseer.purchase.batch.line'].browse(first_batch.line_ids.id).web_read(read_spec))
    report_id = 'baseer_purchase_batch.action_report_purchase_batch'
    for lang in ('en_US', 'ar_001'):
        report = a['ir.actions.report'].with_context(lang=lang)
        html, html_type = report._render_qweb_html(report_id, first_batch.ids)
        check('cashier own approved native HTML report renders ' + lang,
              html_type == 'html' and bool(html) and bill.name.encode() in html)
        deny_report('other cashier native HTML report denied ' + lang,
                    lambda lang=lang: b['ir.actions.report'].with_context(lang=lang)._render_qweb_html(report_id, first_batch.ids))
        wkhtml_state = report.get_wkhtmltopdf_state()
        if wkhtml_state in ('ok', 'upgrade', 'workers'):
            started = perf_counter()
            pdf, pdf_type = report._render_qweb_pdf(report_id, res_ids=first_batch.ids)
            check('cashier own approved native PDF report renders ' + lang,
                  pdf_type == 'pdf' and pdf.startswith(b'%PDF-') and len(pdf) > 1000)
            timings.append({'operation': 'own_batch_native_pdf_' + lang,
                            'seconds': round(perf_counter() - started, 4), 'bytes': len(pdf)})
            deny_report('other cashier native PDF report denied ' + lang,
                        lambda lang=lang: b['ir.actions.report'].with_context(lang=lang)._render_qweb_pdf(report_id, res_ids=first_batch.ids))
        else:
            result.setdefault('not_tested', []).append('native PDF ' + lang + ': wkhtmltopdf state ' + str(wkhtml_state))
    deny('other cashier cannot request batch report', lambda: b['baseer.purchase.batch'].browse(first_batch.id).action_print())
    deny('other cashier cannot read print projection', lambda: b['baseer.purchase.batch'].browse(first_batch.id)._get_print_data())
    deny('cashier approved shortcut cannot enter accounting', first_batch.action_approve)
    deny('cashier native batch invoice action denied', first_batch.action_view_bills)
    deny('cashier native row invoice action denied', first_batch.line_ids.action_view_bill)
    deny('cashier direct vendor invoice read denied', lambda: a['account.move'].browse(bill.id).read(['name', 'amount_total']))
    deny('cashier direct vendor invoice line read denied', lambda: a['account.move.line'].browse(bill.line_ids[:1].id).read(['balance']))
    deny('cashier approved batch edit denied', lambda: first_batch.write({'entry_date': fields.Date.today()}), (UserError,))
    deny('cashier approved row edit denied', lambda: first_batch.line_ids.write({'gross_amount': 230}), (UserError,))
    deny('cashier approved batch deletion denied', first_batch.unlink, (UserError,))

    methods = local_admin['account.payment.method.line'].search([
        ('company_id', '=', company.id), ('payment_type', '=', 'outbound'), ('code', '=', 'manual')])
    method = methods.filtered(lambda rec: rec.journal_id.active and rec.journal_id.type in ('cash', 'bank') and rec.payment_account_id and rec.payment_account_id == rec.journal_id.default_account_id and rec.payment_account_id.account_type == 'asset_cash')[:1]
    assert method, 'Fixture company needs a configured native cash/bank outbound payment method'
    paid = batch(a, line_ids=[Command.create(row(is_credit=False, payment_method_line_id=method.id))])
    acc['baseer.purchase.batch'].browse(paid.id).action_approve()
    payment = paid.sudo().line_ids.payment_id
    check('accountant approval creates actual native paid/reconciled bill', bool(payment) and paid.sudo().line_ids.move_id.payment_state == 'paid' and cents(paid.sudo().line_ids.move_id.amount_residual) == 0)
    deny('cashier direct native payment read denied', lambda: a['account.payment'].browse(payment.id).read(['amount']))
    check('cashier paid batch approved summary stays printable', bool(paid._get_print_data()['rows'][0]['invoice']))

    for actor, label in ((a, 'cashier'), (acc, 'accountant')):
        # Environment.user is deliberately sudo in native Odoo. RPC browses the
        # model in the caller environment instead; test that actual boundary.
        actor_user = actor['res.users'].browse(actor.uid)
        assert not actor_user.env.su
        deny(label + ' cannot assign owner role', lambda actor_user=actor_user: actor_user.write({'baseer_access_role': 'owner'}))
        deny(label + ' cannot clear own role', lambda actor_user=actor_user: actor_user.write({'baseer_access_role': False}))
        deny(label + ' cannot add system group through user write', lambda actor_user=actor_user: actor_user.write({'group_ids': [Command.link(env.ref('base.group_system').id)]}))
        deny(label + ' cannot add own membership through group write', lambda actor=actor: actor['res.groups'].browse(env.ref('base.group_system').id).write({'user_ids': [Command.link(actor.uid)]}))
        deny(label + ' cannot create an elevated group with own membership', lambda actor=actor: actor['res.groups'].create({'name': PREFIX + 'forbidden group', 'implied_ids': [Command.link(env.ref('base.group_system').id)], 'user_ids': [Command.link(actor.uid)]}))

    deny('admin cannot silently add unrelated grant to cashier preset', lambda: first.write({'group_ids': [Command.link(env.ref('account.group_account_invoice').id)]}), (UserError,))
    owner.write({'baseer_access_role': 'cashier', 'company_ids': [Command.set(company.ids)], 'company_id': company.id})
    downgraded = user_env(owner, company)
    check('owner to cashier downgrade removes settings and invoice grants', not downgraded.user.has_group('base.group_system') and not downgraded.user.has_group('account.group_account_invoice') and downgraded.user.has_group('baseer_access_roles.group_cashier'))
    deny('downgraded owner cannot regain owner role', lambda: downgraded['res.users'].browse(downgraded.uid).write({'baseer_access_role': 'owner'}))

    fixture_models = (
        ('crm.lead', {'name': PREFIX + 'lead', 'company_id': company.id}),
        ('project.project', {'name': PREFIX + 'project', 'company_id': company.id}),
        ('project.task', {'name': PREFIX + 'task', 'company_id': company.id}),
        ('hr.employee', {'name': PREFIX + 'employee', 'company_id': company.id}),
    )
    for model, values in fixture_models:
        if model not in env.registry:
            continue
        fixture = local_admin[model].create(values)
        for actor, label in ((a, 'cashier'), (acc, 'accountant')):
            if model == 'hr.employee':
                # Native Odoo deliberately projects public employee fields to
                # support contact/POS lookups when the private model is denied.
                # A display_name read therefore cannot prove private HR access.
                check(label + ' native public employee name lookup remains available',
                      actor[model].browse(fixture.id).read(['display_name'])[0]['display_name'] == fixture.display_name)
                deny(label + ' private employee email read denied',
                     lambda actor=actor, fixture=fixture: actor['hr.employee'].browse(fixture.id).read(['private_email']))
                deny(label + ' private employee search_read denied',
                     lambda actor=actor, fixture=fixture: actor['hr.employee'].search_read([('id', '=', fixture.id)], ['private_email']))
                deny(label + ' private employee write denied',
                     lambda actor=actor, fixture=fixture: actor['hr.employee'].browse(fixture.id).write({'private_email': 'ar1-rollback@example.invalid'}))
                continue
            deny(label + ' unrelated ' + model + ' direct read denied', lambda actor=actor, model=model, fixture=fixture: actor[model].browse(fixture.id).read(['display_name']))
            check(label + ' unrelated ' + model + ' search exposes no fixture', fixture.id not in actor[model].search([]).ids) if actor[model].has_access('read') else check(label + ' unrelated ' + model + ' has no read ACL', True)
    if 'hr.payslip' in env.registry:
        for actor, label in ((a, 'cashier'), (acc, 'accountant')):
            deny(label + ' payroll read access denied', lambda actor=actor: actor['hr.payslip'].check_access('read'))

    started = perf_counter()
    measured = [batch(a) for index in range(10)]
    timings.append({'operation': 'create_ten_one_row_cashier_drafts', 'seconds': round(perf_counter() - started, 4)})
    started = perf_counter()
    found = a['baseer.purchase.batch'].search_read([], ['name', 'state', 'amount_gross'], limit=20)
    elapsed = perf_counter() - started
    timings.append({'operation': 'own_batch_paginated_search_20', 'fixture_batches': 10, 'seconds': round(elapsed, 4), 'target_seconds': 2})
    check('bounded own-batch query finds all measured fixtures', {rec.id for rec in measured}.issubset({rec['id'] for rec in found}))
    check('bounded own-batch search meets isolated 2 second target', elapsed < 2)
    result['status'] = 'PASS'
except Exception as error:
    result['error_type'] = type(error).__name__
    result['error'] = str(error)
    result['traceback'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    result['rollback'] = native_counts() == before and users_stamp() == existing_users
    result['passed'] = len(checks)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    print('AR1_ROLE_CHECKS', result['status'], result['passed'], 'ROLLBACK', result['rollback'])

assert result['status'] == 'PASS', result.get('error', 'AR1 role checks failed')
assert result['rollback'], 'AR1 fixtures were not fully rolled back'
