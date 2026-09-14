"""Verify the immutable product snapshot after the schema upgrade."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT count(*)
          FROM baseer_procurement_price_history history
          LEFT JOIN product_product product ON product.id = history.product_id
         WHERE history.product_id IS NULL OR product.id IS NULL
        """
    )
    if cr.fetchone()[0]:
        raise RuntimeError('Procurement price history contains an invalid product snapshot.')

