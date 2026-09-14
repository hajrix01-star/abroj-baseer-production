"""Detach product history from mutable purchase-option relations.

The former stored related field already created ``product_id``.  Backfill any
legacy gap from the option before Odoo loads the new required snapshot field.
"""


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return bool(cr.fetchone()[0])


def migrate(cr, version):
    history = 'baseer_procurement_price_history'
    option = 'baseer_procurement_purchase_option'
    if not _table_exists(cr, history) or not _table_exists(cr, option):
        return
    cr.execute(
        f"""
        UPDATE {history} history
           SET product_id = purchase_option.product_id
          FROM {option} purchase_option
         WHERE purchase_option.id = history.option_id
           AND history.product_id IS NULL
        """
    )
    cr.execute(f"SELECT count(*) FROM {history} WHERE product_id IS NULL")
    if cr.fetchone()[0]:
        raise RuntimeError('Cannot freeze procurement price history with a missing product snapshot.')

