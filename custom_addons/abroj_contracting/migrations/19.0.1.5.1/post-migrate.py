from odoo.addons.abroj_contracting.backfill import migrate_cr


def migrate(cr, version):
    # Project analytic accounts only (unprotected tables). Writes to
    # account_move / account_move_line are deferred to the post-deploy
    # ops/production/abroj-analytic-backfill step unless explicitly enabled.
    migrate_cr(cr)
