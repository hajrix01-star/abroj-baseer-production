from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Link bot-created vendor bills to their project and apply analytics to drafts."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""UPDATE account_move m SET abroj_project_id = i.project_id
                  FROM abroj_contracting_inbox i
                  WHERE i.abroj_invoice_bill_id = m.id AND i.project_id IS NOT NULL
                    AND m.abroj_project_id IS NULL""")
    env['account.move'].invalidate_model(['abroj_project_id'])
    env['account.move'].search([('abroj_project_id', '!=', False), ('state', '=', 'draft')])._abroj_apply_project_analytic()
