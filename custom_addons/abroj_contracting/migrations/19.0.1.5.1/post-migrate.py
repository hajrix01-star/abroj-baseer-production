from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    projects = env['project.project'].with_context(active_test=False).search([('account_id', '=', False)])
    projects._abroj_ensure_analytic_account(keep_project_company=True)
    # Link voucher journal entries to their project (field only; lines already
    # carry analytics from approval) and apply analytics to draft project moves.
    Voucher = env['abroj.contracting.voucher'].with_context(active_test=False)
    for voucher in Voucher.search([('payment_id', '!=', False)]):
        move = voucher.payment_id.move_id
        if move and not move.abroj_project_id:
            cr.execute('UPDATE account_move SET abroj_project_id=%s WHERE id=%s', (voucher.project_id.id, move.id))
    env['account.move'].invalidate_model(['abroj_project_id'])
    env['account.move'].search([('abroj_project_id', '!=', False), ('state', '=', 'draft')])._abroj_apply_project_analytic()
