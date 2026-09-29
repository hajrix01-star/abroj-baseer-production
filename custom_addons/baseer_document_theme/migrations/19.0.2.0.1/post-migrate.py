"""Move companies from the superseded Baseer header to Baseer Boxed."""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    legacy_layout = env.ref('baseer_document_theme.external_layout_baseer_theme')
    boxed_layout = env.ref('baseer_document_theme.external_layout_baseer_boxed')
    env['res.company'].with_context(active_test=False).search([
        ('external_report_layout_id', '=', legacy_layout.id),
    ]).write({
        'external_report_layout_id': boxed_layout.id,
    })
