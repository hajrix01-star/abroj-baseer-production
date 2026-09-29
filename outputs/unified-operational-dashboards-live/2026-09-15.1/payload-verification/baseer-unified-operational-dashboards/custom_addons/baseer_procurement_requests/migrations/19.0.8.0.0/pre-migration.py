"""Prepare legacy option keys for product-backed catalogue defaults.

PostgreSQL UNIQUE constraints consider NULL values distinct.  Older rows used
NULL for an empty packaging note, so one deterministic row per product/UoM is
promoted to the canonical empty-string key.  Other legacy duplicates remain
untouched and available; all newly created defaults use the canonical key.
"""


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return bool(cr.fetchone()[0])


def migrate(cr, version):
    if not _table_exists(cr, 'baseer_procurement_purchase_option'):
        return
    cr.execute(
        """
        WITH canonical AS (
            SELECT MIN(candidate.id) AS id
              FROM baseer_procurement_purchase_option candidate
             WHERE candidate.packaging_note IS NULL
               AND NOT EXISTS (
                    SELECT 1
                      FROM baseer_procurement_purchase_option existing
                     WHERE existing.company_id = candidate.company_id
                       AND existing.product_id = candidate.product_id
                       AND existing.uom_id = candidate.uom_id
                       AND existing.packaging_note = ''
               )
             GROUP BY candidate.company_id, candidate.product_id, candidate.uom_id
        )
        UPDATE baseer_procurement_purchase_option option
           SET packaging_note = ''
          FROM canonical
         WHERE option.id = canonical.id
        """
    )
