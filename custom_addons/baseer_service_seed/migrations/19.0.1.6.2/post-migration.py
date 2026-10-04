"""Restore the exact service-seed XMLID flag before final module validation."""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    cr.execute("SELECT to_regclass('pg_temp.baseer_service_seed_retained_view')")
    if not cr.fetchone()[0]:
        return
    cr.execute('SELECT xmlid_id, noupdate FROM baseer_service_seed_retained_view')
    xmlid_id, noupdate = cr.fetchone()
    cr.execute('UPDATE ir_model_data SET noupdate = %s WHERE id = %s AND noupdate = TRUE', [noupdate, xmlid_id])
    if cr.rowcount != 1:
        raise RuntimeError('Service-seed retained-view state changed unexpectedly during upgrade.')
    api.Environment(cr, SUPERUSER_ID, {})['ir.model.data'].browse(xmlid_id).invalidate_recordset(['noupdate'])
    cr.execute('DROP TABLE baseer_service_seed_retained_view')
