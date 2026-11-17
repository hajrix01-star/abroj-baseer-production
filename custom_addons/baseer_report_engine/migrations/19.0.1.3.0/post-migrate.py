from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    installed = dict(env['res.lang'].get_installed())
    records = (
        ('report_profit_and_loss', 'الربح والخسارة', 'baseer_report_definition'),
        ('action_profit_and_loss', 'الربح والخسارة (جديد)', 'ir_act_client'),
        ('menu_profit_and_loss', 'الربح والخسارة (جديد)', 'ir_ui_menu'),
    )
    for xmlid, name, table in records:
        record = env.ref('baseer_report_engine.' + xmlid)
        active = {lang: name for lang in ('ar_001', 'ar') if lang in installed}
        if active:
            record.update_field_translations('name', active)
        # Odoo's translation API rejects inactive languages. Update their stored
        # translations too, so a later reactivation cannot restore old names.
        for lang in ('ar_001', 'ar'):
            if lang not in installed:
                cr.execute(
                    f"UPDATE {table} SET name = jsonb_set(name, %s, to_jsonb(%s::text)) WHERE id = %s",
                    ([lang], name, record.id),
                )
        record.invalidate_recordset(['name'])
