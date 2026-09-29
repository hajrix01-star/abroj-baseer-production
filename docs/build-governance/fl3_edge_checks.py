"""Three bounded POS ledger edge cases; separate from the accepted main matrix."""
import json
import traceback
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from odoo import Command, fields
from odoo.addons.baseer_pos_summary.models.common import native_quote

assert env.su and env.cr.dbname == 'baseer_ic1_20260910'
result = {'status': 'FAIL', 'checks': [], 'rollback': False}
models = ('account.move', 'account.move.line', 'account.payment', 'pos.config', 'pos.session',
          'pos.order', 'pos.payment', 'res.currency.rate', 'account.cash.rounding')
def counts():
    return {m: env[m].search_count([]) for m in models}
def check(name, condition):
    assert condition, name
    result['checks'].append(name)
def dec(value):
    return Decimal(str(value or 0)).quantize(Decimal('0.01'))
before = counts()
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('FL3 edge fixtures cannot commit'))
guard.start()
try:
    source = env['pos.config'].search([('baseer_summary_only', '=', True)]).filtered(lambda c: c.currency_id.name == 'SAR')[:1]
    company = source.company_id
    admin = env(context={'allowed_company_ids': company.ids, 'lang': 'en_US', 'tracking_disable': True, 'generate_pdf': False})
    today = fields.Date.context_today(admin['account.move'])
    product, tax = source.baseer_summary_product_id, source.baseer_summary_tax_id
    ar = company.account_default_pos_receivable_account_id
    partner = admin['res.partner'].create({'name': 'FL3 edge customer', 'company_id': company.id,
                                         'property_account_receivable_id': ar.id})
    income = product._get_product_accounts()['income']
    expense = admin['account.account'].search([('company_ids', 'in', company.ids), ('account_type', '=', 'expense_direct_cost')], limit=1)
    if not expense:
        expense = admin['account.account'].create({'name': 'FL3 synthetic COGS', 'code': '519991',
            'account_type': 'expense_direct_cost', 'company_ids': [Command.set(company.ids)]})
    asset = admin['account.account'].create({'name': 'FL3 synthetic inventory', 'code': '119991',
        'account_type': 'asset_current', 'company_ids': [Command.set(company.ids)]})
    serial = [0]
    def posted(gross=115, paid=None, currency=None, rounding=None):
        serial[0] += 1
        n = serial[0]
        currency = currency or company.currency_id
        journal = admin['account.journal'].create({'name': 'FL3 edge cash ' + str(n), 'code': 'E3' + str(n),
            'type': 'cash', 'company_id': company.id, 'currency_id': currency.id})
        sale_journal = admin['account.journal'].create({'name': 'FL3 edge sales ' + str(n), 'code': 'S3' + str(n),
            'type': 'sale', 'company_id': company.id, 'currency_id': currency.id})
        method = admin['pos.payment.method'].create({'name': 'FL3 edge method ' + str(n), 'company_id': company.id,
            'journal_id': journal.id, 'receivable_account_id': ar.id})
        cfg = admin['pos.config'].create({'name': 'FL3 edge POS ' + str(n), 'company_id': company.id,
            'journal_id': sale_journal.id, 'invoice_journal_id': source.invoice_journal_id.id,
            'payment_method_ids': [Command.set(method.ids)], 'cash_control': True, 'use_presets': False,
            'cash_rounding': bool(rounding), 'rounding_method': rounding.id if rounding else False,
            'only_round_cash_method': bool(rounding)})
        s = admin['pos.session'].create({'config_id': cfg.id})
        s.set_opening_control(0, 'FL3 edge fixture')
        quote = native_quote(dec(gross), tax, product, company)
        order = admin['pos.order'].create({'session_id': s.id, 'company_id': company.id, 'partner_id': partner.id,
            'amount_total': gross, 'amount_tax': float(quote['tax']), 'amount_paid': 0, 'amount_return': 0,
            'lines': [Command.create({'product_id': product.id, 'qty': 1, 'price_unit': float(quote['unit_price']),
                'price_subtotal': float(quote['net']), 'price_subtotal_incl': gross,
                'tax_ids': [Command.set(tax.ids)], 'full_product_name': 'FL3 edge sale'})]})
        admin['pos.payment'].create({'pos_order_id': order.id, 'payment_method_id': method.id,
            'amount': gross if paid is None else paid})
        order.lines._onchange_amount_line_all()
        order._compute_prices()
        order.action_pos_order_paid()
        s._compute_cash_balance()
        s.cash_register_balance_end_real = s.cash_register_balance_end
        s._compute_cash_balance()
        s.action_pos_session_closing_control()
        assert s.state == 'closed'
        return s, order
    def total(s):
        payload = admin['account.move'].baseer_financial_register_kpis([('id', '=', s.move_id.id)])
        currency_group = next(c for c in payload['currency_groups'] if c['currency_id'] == company.currency_id.id)
        return Decimal(currency_group['sections'][0]['cards'][0]['display'].replace(',', ''))

    cost_session, _order = posted()
    cost_session.move_id.button_draft()
    cost_session.move_id.write({'line_ids': [Command.create({'account_id': expense.id, 'name': 'Fixture COGS debit', 'debit': 20}),
        Command.create({'account_id': asset.id, 'name': 'Fixture inventory credit', 'credit': 20})]})
    cost_session.move_id.action_post()
    check('balanced COGS/inventory ledger additions do not inflate sales', dec(cost_session.move_id.amount_total_signed) == 135
          and total(cost_session) == 115 and dec(sum(cost_session.move_id.line_ids.mapped('balance'))) == 0)
    result['stock_scope'] = 'Native posted POS entry plus balanced synthetic COGS/inventory lines; not an end-to-end stock valuation workflow.'

    rounding = admin['account.cash.rounding'].create({'name': 'FL3 native cash rounding', 'rounding': 0.05,
        'strategy': 'add_invoice_line', 'rounding_method': 'HALF-UP', 'profit_account_id': income.id,
        'loss_account_id': expense.id})
    rounded_session, rounded_order = posted(115.02, 115.00, rounding=rounding)
    check('native cash rounding uses posted receivable115 not unrounded order115.02', dec(rounded_order.amount_total) == Decimal('115.02')
          and total(rounded_session) == 115 and dec(rounded_session.move_id.line_ids.filtered(lambda l: l.account_id == ar).balance) == 115)

    usd = admin.ref('base.USD')
    usd.active = True
    existing_rate = admin['res.currency.rate'].search([('company_id', '=', company.id), ('currency_id', '=', usd.id), ('name', '=', today)])
    if existing_rate:
        existing_rate.rate = 0.25
    else:
        admin['res.currency.rate'].create({'name': today, 'currency_id': usd.id, 'company_id': company.id, 'rate': 0.25})
    foreign_session, foreign_order = posted(115, currency=usd)
    ledger_gross = dec(sum(foreign_session.move_id.line_ids.filtered(lambda l: l.account_id == ar).mapped('balance')))
    check('foreign POS displays historical company ledger currency instead of order currency', foreign_order.currency_id == usd
          and ledger_gross != 115 and total(foreign_session) == ledger_gross
          and dec(foreign_session.move_id.baseer_register_amount) == ledger_gross)
    result['foreign_company_amount'] = str(ledger_gross)
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    env.invalidate_all()
    guard.stop()
    result['rollback'] = before == counts()
    result['hard_commit_guard'] = True
    result['passed'] = len(result['checks'])
    Path('/mnt/qa-evidence/fl3-edge-checks.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
assert result['status'] == 'PASS' and result['rollback']
