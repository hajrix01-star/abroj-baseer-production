"""Mark one reusable legacy inventory-UoM option as each product default."""


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
        """,
        [table, column],
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    table = 'baseer_procurement_purchase_option'
    if not _column_exists(cr, table, 'catalog_default_key'):
        return
    cr.execute(
        """
        WITH reusable AS (
            SELECT DISTINCT ON (option.company_id, option.product_id)
                   option.id,
                   option.product_id::varchar AS default_key
              FROM baseer_procurement_purchase_option option
              JOIN product_product product ON product.id = option.product_id
              JOIN product_template template ON template.id = product.product_tmpl_id
             WHERE option.active
               AND option.uom_id = template.uom_id
               AND COALESCE(option.packaging_note, '') = ''
               AND template.active
               AND template.purchase_ok
               AND template.type = 'consu'
               AND template.company_id = option.company_id
             ORDER BY option.company_id, option.product_id, option.sequence, option.id
        )
        UPDATE baseer_procurement_purchase_option option
           SET catalog_default_key = reusable.default_key
          FROM reusable
         WHERE option.id = reusable.id
           AND option.catalog_default_key IS NULL
        """
    )
