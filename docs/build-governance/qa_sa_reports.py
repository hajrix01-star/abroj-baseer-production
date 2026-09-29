"""Run via Odoo shell ONLY against the isolated reports QA database."""
import json
from pathlib import Path
from odoo import Command
from odoo.exceptions import AccessError

assert env.cr.dbname == 'baseer_reports_qa_20260907', 'QA database required'
assert not env['res.company'].search([('name', '=', 'QA ARZ')]), 'Fixture already exists'
out = Path('/mnt/qa-evidence')
out.mkdir(exist_ok=True)
admin = env.ref('base.user_admin')
country = env.ref('base.sa')
sar = env.ref('base.SAR')
sar.active = True
companies = []
checks = []

def assert_money(actual, expected, label):
    assert sar.compare_amounts(actual, expected) == 0, (label, actual, expected)
    checks.append({'check': label, 'actual': actual, 'expected': expected})

for index, name in enumerate(['QA ARZ', 'QA المعلم الشامي', 'QA دوحة المستهلك'], 1):
    c = env['res.company'].create({
        'name': name, 'country_id': country.id, 'currency_id': sar.id,
        'city': 'Al Khobar', 'email': 'qa@example.invalid', 'iap_enrich_auto_done': True,
    })
    env['account.chart.template'].with_company(c)._load('sa', c, install_demo=False)
    companies.append(c)
    admin.write({'company_ids': [Command.link(c.id)]})
    ctx = dict(env.context, allowed_company_ids=[c.id], tracking_disable=True)
    accounts = env['account.account'].with_company(c).with_context(ctx)
    def account(kind):
        result = accounts.search([('company_ids', 'in', [c.id]), ('account_type', '=', kind)], limit=1)
        assert result, kind
        return result
    income, expense = account('income'), account('expense')
    equity = accounts.create({'name': 'QA Opening Capital', 'code': 'QA3000',
        'account_type': 'equity', 'company_ids': [Command.set([c.id])]})
    ar, ap = account('asset_receivable'), account('liability_payable')
    journals = env['account.journal'].with_company(c).with_context(ctx)
    bank = journals.search([('company_id', '=', c.id), ('type', '=', 'bank')], limit=1)
    cash = journals.search([('company_id', '=', c.id), ('type', '=', 'cash')], limit=1)
    if not cash:
        cash = journals.create({'name': 'QA Cash', 'code': 'QAC', 'type': 'cash', 'company_id': c.id})
    if not bank:
        bank = journals.create({'name': 'QA Bank', 'code': 'QAB', 'type': 'bank', 'company_id': c.id})
    general = journals.search([('company_id', '=', c.id), ('type', '=', 'general')], limit=1)
    for journal in [cash, bank]:
        for method in journal.inbound_payment_method_line_ids + journal.outbound_payment_method_line_ids:
            method.payment_account_id = journal.default_account_id
    partner = env['res.partner'].with_company(c).with_context(ctx).create({
        'name': 'QA Counterparty ' + str(index), 'company_id': c.id,
        'property_account_receivable_id': ar.id, 'property_account_payable_id': ap.id,
    })
    moves = env['account.move'].with_company(c).with_context(ctx)
    def entry(date, lines):
        m = moves.create({'date': date, 'journal_id': general.id, 'ref': 'QA synthetic',
            'line_ids': [Command.create({'name': 'QA synthetic', 'account_id': a.id,
                'debit': d, 'credit': cr}) for a, d, cr in lines]})
        m.action_post()
        return m
    def invoice(kind, amount, a):
        m = moves.create({'move_type': kind, 'partner_id': partner.id,
            'invoice_date': '2026-09-01', 'date': '2026-09-01',
            'invoice_line_ids': [Command.create({'name': 'QA tax-neutral service',
                'account_id': a.id, 'quantity': 1, 'price_unit': amount, 'tax_ids': [Command.clear()]})]})
        m.action_post()
        return m
    def pay(m, amount):
        direction = 'inbound' if m.move_type == 'out_invoice' else 'outbound'
        methods = cash.inbound_payment_method_line_ids if direction == 'inbound' else cash.outbound_payment_method_line_ids
        wizard = env['account.payment.register'].with_company(c).with_context(
            ctx, active_model='account.move', active_ids=m.ids).create({
                'journal_id': cash.id, 'payment_method_line_id': methods[0].id,
                'amount': amount, 'payment_date': '2026-09-02'})
        payments = wizard._create_payments()
        assert payments and all(p.move_id.state == 'posted' for p in payments)
        return payments
    options = {'date': {'date_from': '2026-09-01', 'date_to': '2026-09-30'},
        'company_ids': [c.id], 'posted_only': True, 'show_zero': False,
        'cash_flow_reconciled': True}
    reports = env['eh.account.dynamic.report'].with_user(admin).with_company(c).with_context(ctx)
    pnl = reports.search([('code', '=', 'profit_and_loss')], limit=1)
    cf = reports.search([('code', '=', 'cash_flow')], limit=1)
    def results():
        return pnl.render(options), cf.render(options)
    p, f = results()
    assert_money(p['totals']['net_profit'], 0, name + ': empty P&L')
    assert_money(f['totals']['closing_cash_balance'], 0, name + ': empty cash')
    entry('2026-08-31', [(cash.default_account_id, 1000 * index, 0), (equity, 0, 1000 * index)])
    sale = invoice('out_invoice', 1000 * index, income)
    p, f = results()
    assert_money(p['totals']['net_profit'], 1000 * index, name + ': unpaid invoice accrual')
    assert_money(f['totals']['net_change_in_cash'], 0, name + ': unpaid invoice no cash')
    pay(sale, 400 * index)
    assert_money(sale.amount_residual, 600 * index, name + ': partial invoice residual')
    p, f = results()
    assert_money(p['totals']['net_profit'], 1000 * index, name + ': collection not repeated income')
    assert_money(f['totals']['net_change_in_cash'], 400 * index, name + ': partial collection')
    bill = invoice('in_invoice', 200 * index, expense)
    pay(bill, 150 * index)
    entry('2026-09-03', [(bank.default_account_id, 75 * index, 0), (cash.default_account_id, 0, 75 * index)])
    p, f = results()
    assert_money(p['totals']['net_profit'], 800 * index, name + ': unpaid expense included')
    assert_money(f['totals']['net_change_in_cash'], 250 * index, name + ': internal transfer net zero')
    # Standard reversal creates the credit note; settle it as an outgoing cash refund.
    reversal = env['account.move.reversal'].with_company(c).with_context(
        ctx, active_model='account.move', active_ids=sale.ids).create({
            'reason': 'QA partial refund', 'date': '2026-09-04', 'journal_id': sale.journal_id.id})
    reversal.reverse_moves(is_modify=False)
    refund = reversal.new_move_ids
    assert len(refund) == 1 and refund.state == 'draft'
    refund.invoice_line_ids.filtered(lambda l: l.display_type == 'product').write({'price_unit': 100 * index})
    refund.action_post()
    # Odoo offsets a reversal against the still-unpaid invoice automatically.
    # Explicitly unmatch that offset to exercise a cash refund instead.
    refund.line_ids.filtered(lambda l: l.account_id.account_type == 'asset_receivable').remove_move_reconcile()
    pay(refund, 100 * index)
    p, f = results()
    assert_money(p['totals']['net_profit'], 700 * index, name + ': refund reduces income')
    assert_money(f['totals']['net_change_in_cash'], 150 * index, name + ': actual net cash')
    assert_money(f['totals']['opening_cash_balance'], 1000 * index, name + ': opening cash')
    assert_money(f['totals']['closing_cash_balance'], 1150 * index, name + ': closing cash')
    assert_money(f['totals']['balance_check'], 0, name + ': cash reconciles')
    for code, payload in [('profit_and_loss', p), ('cash_flow', f)]:
        (out / ('company_%s_%s.json' % (c.id, code))).write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding='utf-8')
    if index == 1:
        for code, report in [('profit_and_loss', pnl), ('cash_flow', cf)]:
            content = report.render_xlsx(options)
            assert content[:2] == b'PK'
            (out / (code + '.xlsx')).write_bytes(content)

admin.write({'company_id': companies[0].id, 'company_ids': [Command.set([c.id for c in companies])]})
restricted = env['res.users'].with_context(no_reset_password=True).create({
    'name': 'QA Restricted Accountant', 'login': 'qa_restricted',
    'company_id': companies[0].id, 'company_ids': [Command.set([companies[0].id])],
    'group_ids': [Command.set([env.ref('base.group_user').id, env.ref('eh_account_base.group_eh_user').id])],
})
for code in ['profit_and_loss', 'cash_flow']:
    report = env['eh.account.dynamic.report'].with_user(restricted).with_context(
        allowed_company_ids=[companies[0].id]).search([('code', '=', code)], limit=1)
    own_opts = dict(options, company_ids=[companies[0].id])
    own = report.render(own_opts)
    expected_key, expected = ('net_profit', 700) if code == 'profit_and_loss' else ('net_change_in_cash', 150)
    assert_money(own['totals'][expected_key], expected, 'restricted own company ' + code)
    try:
        with env.cr.savepoint():
            report.render(dict(own_opts, company_ids=[companies[1].id]))
    except AccessError:
        checks.append({'check': 'restricted cross-company rejected ' + code, 'passed': True})
    else:
        raise AssertionError('Cross-company access permitted: ' + code)

env['ir.cron'].search([]).write({'active': False})
env['ir.mail_server'].search([]).write({'active': False})
env.cr.commit()
(out / 'sa_scenarios.json').write_text(json.dumps({'checks': checks, 'companies': [{'id': c.id, 'name': c.name} for c in companies]}, ensure_ascii=False, indent=2), encoding='utf-8')
print('QA_SUCCESS', len(checks), 'checks; company ids:', [c.id for c in companies])
