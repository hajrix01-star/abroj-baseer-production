"""Analytic backfill that touches protected accounting tables.

Production deploys verify byte-identical snapshots of account_move /
account_move_line, so module migrations must not write there.  The backfill
below is run separately after deploy via ops/production/abroj-analytic-backfill
(or during migration only when the config parameter
``abroj_contracting.install_analytic_backfill`` is truthy, e.g. on QA).
"""
from odoo import SUPERUSER_ID, api

PARAM = 'abroj_contracting.install_analytic_backfill'


def install_backfill_enabled(env):
    value = env['ir.config_parameter'].sudo().get_param(PARAM, '')
    return str(value).strip().lower() in ('1', 'true', 'yes')


def ensure_project_analytic_accounts(env):
    """Safe during install: only account_analytic_account / project_project."""
    projects = env['project.project'].with_context(active_test=False).search([('account_id', '=', False)])
    projects._abroj_ensure_analytic_account(keep_project_company=True)
    return len(projects)


def run_analytic_backfill(env):
    """Link vouchers/bot bills to projects and apply analytics to draft moves."""
    cr = env.cr
    stats = {'projects': ensure_project_analytic_accounts(env)}
    Voucher = env['abroj.contracting.voucher'].with_context(active_test=False)
    linked = 0
    for voucher in Voucher.search([('payment_id', '!=', False)]):
        move = voucher.payment_id.move_id
        if move and not move.abroj_project_id:
            cr.execute('UPDATE account_move SET abroj_project_id=%s WHERE id=%s', (voucher.project_id.id, move.id))
            linked += 1
    stats['voucher_moves_linked'] = linked
    if 'abroj.contracting.inbox' in env \
            and 'abroj_invoice_bill_id' in env['abroj.contracting.inbox']._fields:
        cr.execute("""UPDATE account_move m SET abroj_project_id = i.project_id
                      FROM abroj_contracting_inbox i
                      WHERE i.abroj_invoice_bill_id = m.id AND i.project_id IS NOT NULL
                        AND m.abroj_project_id IS NULL""")
        stats['inbox_bills_linked'] = cr.rowcount
    env['account.move'].invalidate_model(['abroj_project_id'])
    drafts = env['account.move'].search([('abroj_project_id', '!=', False), ('state', '=', 'draft')])
    drafts._abroj_apply_project_analytic()
    stats['draft_moves_processed'] = len(drafts)
    return stats


def migrate_cr(cr):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ensure_project_analytic_accounts(env)
    if install_backfill_enabled(env):
        run_analytic_backfill(env)
