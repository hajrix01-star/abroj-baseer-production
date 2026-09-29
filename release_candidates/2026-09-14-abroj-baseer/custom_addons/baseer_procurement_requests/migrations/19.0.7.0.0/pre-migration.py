"""Upgrade PRC-CUSTODY2 databases before the report view is rebuilt.

Migration scripts are not executed on a fresh install.  Therefore these
defensive ALTER statements can support older databases without reintroducing
the fresh-install failure caused by DDL in an ``_auto = False`` model's init.
"""


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", [table])
    return bool(cr.fetchone()[0])


def migrate(cr, version):
    if _table_exists(cr, 'baseer_procurement_custody_settlement'):
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "ADD COLUMN IF NOT EXISTS state varchar DEFAULT 'active' NOT NULL"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "ADD COLUMN IF NOT EXISTS reversal_move_id integer"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "ADD COLUMN IF NOT EXISTS reversal_reason varchar"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "ADD COLUMN IF NOT EXISTS representative_partner_id integer"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "DROP CONSTRAINT IF EXISTS baseer_procurement_settlement_unique"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_settlement "
            "DROP CONSTRAINT IF EXISTS "
            "baseer_procurement_custody_settlement_batch_line_id_unique"
        )
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                baseer_procurement_custody_settlement_active_batch_line_uniq
            ON baseer_procurement_custody_settlement (batch_line_id)
            WHERE state = 'active'
            """
        )
        cr.execute(
            """
            CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_pool_lookup_idx
            ON baseer_procurement_custody_settlement
                (custody_id, representative_partner_id, state)
            """
        )
        cr.execute(
            """
            CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_allocation_idx
            ON baseer_procurement_custody_settlement
                (company_id, custody_id, state, batch_line_id)
            """
        )
        cr.execute(
            """
            CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_company_state_idx
            ON baseer_procurement_custody_settlement
                (company_id, state, batch_line_id)
            """
        )

    if _table_exists(cr, 'baseer_procurement_custody_event'):
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_event "
            "ADD COLUMN IF NOT EXISTS representative_partner_id integer"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody_event "
            "ADD COLUMN IF NOT EXISTS procurement_request_id integer"
        )
        cr.execute(
            """
            CREATE INDEX IF NOT EXISTS baseer_procurement_custody_event_pool_lookup_idx
            ON baseer_procurement_custody_event
                (custody_id, representative_partner_id, state, event_date)
            """
        )

    if _table_exists(cr, 'baseer_procurement_custody'):
        cr.execute(
            "ALTER TABLE baseer_procurement_custody "
            "ADD COLUMN IF NOT EXISTS representative_partner_id integer"
        )
        cr.execute(
            "ALTER TABLE baseer_procurement_custody "
            "ADD COLUMN IF NOT EXISTS is_company_pool boolean DEFAULT false NOT NULL"
        )
        cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_procurement_custody_company_pool_uniq
            ON baseer_procurement_custody (company_id)
            WHERE is_company_pool
            """
        )

    if _table_exists(cr, 'baseer_procurement_bill_allocation'):
        cr.execute(
            """
            CREATE INDEX IF NOT EXISTS baseer_procurement_bill_allocation_request_line_idx
            ON baseer_procurement_bill_allocation (request_id, batch_line_id)
            """
        )
