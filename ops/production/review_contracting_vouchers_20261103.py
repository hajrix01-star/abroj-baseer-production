"""Bounded owner-authorized operational review. Run in Odoo shell, dry by default.

BASEER_APPLY_VOUCHER_REVIEW=1 enables one transaction after the protected release.
No SQL operational writes; all changes use the reviewed native workflow actions.
"""
import json
import os
from decimal import Decimal

APPLY = os.environ.get('BASEER_APPLY_VOUCHER_REVIEW') == '1'
assert env.cr.dbname == 'baseer_prod', 'This manifest is production-specific.'
COMPANY, PROJECT = 56, 4
env = env(context=dict(env.context, allowed_company_ids=[COMPANY]))
if not APPLY:
    env.cr.execute('SET TRANSACTION READ ONLY')
MANIFEST = {
    8: ('PAY/2026/00003', 1000, 8197, 17944, 17039, 'advance'),
    9: ('PAY/2026/00004', 800, 8196, 17943, 17040, 'direct'),
    10: ('PAY/2026/00005', 2500, 8195, 17942, 17041, 'advance'),
    11: ('REC/2026/00001', 5000, 8194, 17941, 17037, 'advance'),
    12: ('PAY/2026/00006', 400, 8199, 17963, 17040, 'direct'),
}
assert env['ir.module.module'].search([('name', '=', 'abroj_project_dashboard')]).latest_version == '19.0.1.9.0'
project = env['project.project'].browse(PROJECT).with_company(env['res.company'].browse(COMPANY))
assert project.company_id.id == COMPANY
vouchers = env['abroj.contracting.voucher'].search([('project_id', '=', PROJECT)])
assert set(vouchers.ids) == {1, 6, *MANIFEST}, 'Voucher inventory changed; review it again.'
assert set(vouchers.filtered(lambda v: v.state == 'cancelled').ids) == {1, 6}
assert not vouchers.filtered(lambda v: v.state == 'cancelled').payment_id
category = env['abroj.project.budget.line'].browse(14)
assert category.project_id == project and category.budget == 1200
assert sum(Decimal(str(b.budget)) for b in project.abroj_budget_line_ids) == Decimal('170780')
assert not any(project.abroj_budget_line_ids.mapped('manual_actual'))
direct_ids = {source_id for source_id, item in MANIFEST.items() if item[-1] == 'direct'}
assert sum(Decimal(str(s.agreed_amount)) for s in project.subcontractor_ids) == Decimal('17000')
assert all(c.state == 'confirmed' and c.account_move_id.abroj_recognition_voucher_id.id in direct_ids
           for c in project.cost_ids), 'Unreviewed project costs exist; review the inventory again.'
journal = env['account.journal'].browse(415)
account = env['account.account'].browse(3554)  # Existing cleaning expense chart account.
assert journal.company_id.id == COMPANY and journal.type == 'purchase'
assert project.company_id in account.company_ids and account.account_type == 'expense'


def fingerprint(voucher):
    payment = voucher.payment_id
    move = payment.move_id
    return {'voucher': voucher.id, 'payment': payment.id, 'move': move.id,
            'amount': payment.amount, 'date': str(payment.date), 'journal': payment.journal_id.id,
            'partner': payment.partner_id.id, 'direction': payment.payment_type,
            'lines': [(l.id, l.account_id.id, l.partner_id.id, l.debit, l.credit, l.amount_currency,
                       l.currency_id.id, l.analytic_distribution) for l in move.line_ids.sorted('id')]}


before = {}
for source_id, (name, amount, payment_id, move_id, partner_id, purpose) in MANIFEST.items():
    voucher = vouchers.browse(source_id)
    assert (voucher.name, voucher.amount, voucher.payment_id.id, voucher.payment_id.move_id.id,
            voucher.payment_id.partner_id.id, voucher.state) == (name, amount, payment_id, move_id, partner_id, 'issued')
    assert voucher.payment_id.move_id.state == 'posted'
    assert voucher.payment_id.partner_type == ('customer' if voucher.kind == 'receipt' else 'supplier')
    if voucher.workflow_reviewed:
        assert voucher.payment_purpose == purpose, 'A reviewed classification changed.'
        if purpose == 'direct':
            assert voucher.recognition_move_id.ref == 'OWNER-REVIEW/' + name
    before[source_id] = fingerprint(voucher)
payments_before = env['account.payment'].search_count([])
evidence = ('Owner approved the exact 2026-11-03 historical review in the implementation chat, '
            'without additional attachments: container services800+400 recognized as expense '
            'without input-VAT deduction; contractor1000+2500 and customer5000 remain on-account '
            'advances pending supporting invoices. Original payments retained unchanged.')
report = {'mode': 'apply' if APPLY else 'dry_run', 'inventory': list(MANIFEST),
          'original_fingerprints': before, 'approved_budget': 170780}
if APPLY:
    for source_id, (_, _, _, _, partner_id, purpose) in MANIFEST.items():
        voucher = vouchers.browse(source_id)
        if voucher.workflow_reviewed:
            continue
        vals = {'voucher_id': voucher.id, 'purpose': purpose, 'partner_id': partner_id,
                'name': voucher.memo or voucher.name, 'evidence_note': evidence,
                'invoice_date': voucher.date, 'date': voucher.date}
        if purpose == 'direct':
            vals.update(invoice_journal_id=journal.id, account_id=account.id,
                        budget_line_id=category.id, document_reference='OWNER-REVIEW/' + voucher.name)
        env['abroj.project.voucher.review'].create(vals).action_apply()
    if project.abroj_budget != 170780:
        project.action_approve_detailed_budget()
    env.flush_all()
    env.invalidate_all()
    assert env['account.payment'].search_count([]) == payments_before, 'No new cash payment is permitted.'
    assert before == {source_id: fingerprint(vouchers.browse(source_id)) for source_id in MANIFEST}
    assert all(vouchers.browse(source_id).workflow_reviewed for source_id in MANIFEST)
    assert category.actual == 1200
    data = project._abroj_data()
    expected = {'actual': 1200, 'paid': 4700, 'received': 5000, 'liquidity': 300,
                'budget': 170780, 'expected_profit': 4220, 'remaining': 170000,
                'recognized_revenue': 0, 'recognized_profit': -1200, 'contract_profit': 156800}
    assert {key: data[key] for key in expected} == expected, data
    direct = vouchers.filtered(lambda v: v.id in MANIFEST and MANIFEST[v.id][-1] == 'direct')
    assert len(direct.recognition_move_id) == 2
    assert all(move.state == 'posted' and move.amount_residual == 0 for move in direct.recognition_move_id)
    assert sum(direct.recognition_move_id.mapped('amount_total')) == 1200
    assert not any(direct.recognition_move_id.mapped('amount_tax'))
    assert project.total_costs == 18200
    assert len(project.cost_ids) == 2 and set(project.cost_ids.ids) == set(direct.recognition_move_id.abroj_cost_id.ids)
    assert sum(project.cost_ids.mapped('amount')) == 1200
    report.update(metrics=expected, recognition_documents=[(v.id, v.recognition_move_id.id,
                   v.recognition_move_id.name) for v in direct], payment_count_unchanged=True,
                   original_financial_fingerprints_unchanged=True)
    project.message_post(body='Owner-authorized historical voucher review completed: '
        'container expense1200; supplier advances3500; customer advance5000; comparison budget170780. '
        'Original cash movements preserved; supplier bills matched to the original payments.')
    env.cr.commit()
else:
    env.cr.rollback()
print('CONTRACTING_HISTORICAL_REVIEW=' + json.dumps(report, ensure_ascii=True, default=str))
