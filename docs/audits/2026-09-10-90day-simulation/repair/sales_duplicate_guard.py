"""One real duplicate native receipt on the isolated clone, fully rolled back."""
import json
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from odoo import api

assert env.cr.dbname == 'baseer_sim90_fix_20260911'
root = Path('/tmp/sim90/repair')
local = api.Environment(env.cr, 5, {'allowed_company_ids': [2], 'lang': 'en_US', 'tz': 'Asia/Riyadh'}, su=False)
checks = []
result = {'status': 'FAIL', 'database': env.cr.dbname, 'checks': checks, 'rollback': False}
models = ('account.payment', 'account.move', 'account.move.line', 'account.partial.reconcile', 'pos.order', 'pos.session')


def counts():
    return {name: local[name].with_context(active_test=False).search_count([]) for name in models}


def verify(label, value):
    checks.append({'label': label, 'passed': bool(value)})
    assert value, label


def state():
    return {'company_id': 2, 'date_to': date(2026, 1, 31), 'visits': 0, 'diagnostics': set()}


class RollbackProbe(Exception):
    pass


before = counts()
guard = patch.object(type(env.cr), 'commit', side_effect=AssertionError('Duplicate fixture cannot commit'))
guard.start()
try:
    payment = local['account.payment'].browse(179)
    verify('existing bank receipt exact source', payment.pos_session_id.id == 6 and payment.amount == 460)
    handler = local['eh.account.dynamic.report.handler.baseer_cash_categories']
    cancelled = local['baseer.pos.summary'].search([('company_id', '=', 2), ('state', '=', 'cancelled')], limit=1)
    reversal = cancelled.reversal_move_ids.filtered(lambda move: move.reversed_entry_id == cancelled.move_id)[:1]
    reversal_state = state()
    verify('retained summary reversal has exact independent ledger proof',
           handler._baseer_pos_exact_reversal(cancelled.move_id, reversal, reversal_state))
    charged = reversal_state['visits']
    verify('repeated reversal proof reuses budgeted evidence', charged > 0
           and handler._baseer_pos_exact_reversal(cancelled.move_id, reversal, reversal_state)
           and reversal_state['visits'] == charged)
    counterpart = payment._seek_for_lines()[1]
    baseline = handler._baseer_pos_receipt_boundary(counterpart, Decimal('460'), state())
    verify('single native receipt proves original460', sum(fragment['gross'] for fragment in baseline) == 460
           and all(fragment.get('sale_collection') and not fragment.get('unknown') for fragment in baseline))
    try:
        with env.cr.savepoint():
            method = payment.pos_payment_method_id
            duplicate = local['account.payment'].create({'payment_type': payment.payment_type,
                'partner_type': payment.partner_type, 'company_id': payment.company_id.id,
                'currency_id': payment.currency_id.id, 'amount': payment.amount, 'date': payment.date,
                'journal_id': payment.journal_id.id, 'pos_session_id': payment.pos_session_id.id,
                'pos_payment_method_id': method.id,
                'force_outstanding_account_id': method.outstanding_account_id.id,
                'destination_account_id': counterpart.account_id.id})
            duplicate.action_post()
            verify('real duplicate payment posts balanced native ledger', duplicate.move_id.state == 'posted'
                   and sum(Decimal(str(line.balance)) for line in duplicate.move_id.line_ids) == 0)
            for source in (payment, duplicate):
                line = source._seek_for_lines()[1]
                fragments = handler._baseer_pos_receipt_boundary(line, Decimal('460'), state())
                verify('duplicate source%s retains460 without fabricated sales/VAT' % source.id,
                    sum(fragment['gross'] for fragment in fragments) == 460
                    and all(fragment.get('unknown') and not fragment.get('sale_collection')
                            and fragment['gross'] == fragment['net'] for fragment in fragments))
            raise RollbackProbe()
    except RollbackProbe:
        pass
    local.invalidate_all()
    verify('all duplicate fixture rows rolled back', counts() == before)
    payment = local['account.payment'].browse(179)
    restored = handler._baseer_pos_receipt_boundary(payment._seek_for_lines()[1], Decimal('460'), state())
    verify('original proof restored after rollback', all(fragment.get('sale_collection') and not fragment.get('unknown') for fragment in restored))
    result['status'] = 'PASS'
except Exception:
    result['error'] = traceback.format_exc()
finally:
    env.cr.rollback()
    local.invalidate_all()
    result['rollback'] = counts() == before
    guard.stop()
    (root / 'sales-duplicate-guard.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print('SALES_DUPLICATE_GUARD', result['status'], len(checks), result['rollback'], flush=True)
assert result['status'] == 'PASS' and result['rollback'], result.get('error')
