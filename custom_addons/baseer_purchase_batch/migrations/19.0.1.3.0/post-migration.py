"""Retire the old contact-level posting selector without touching its audit data."""


def migrate(cr, version):
    cr.execute("""
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'baseer_purchase_batch'
           AND name = 'view_partner_purchase_batch_defaults'
           AND model = 'ir.ui.view'
    """)
    row = cr.fetchone()
    if row:
        cr.execute('DELETE FROM ir_model_data WHERE module = %s AND name = %s', [
            'baseer_purchase_batch', 'view_partner_purchase_batch_defaults',
        ])
        cr.execute('DELETE FROM ir_ui_view WHERE id = %s', [row[0]])
