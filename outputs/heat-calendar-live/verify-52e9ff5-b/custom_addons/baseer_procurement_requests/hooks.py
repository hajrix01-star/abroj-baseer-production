"""Install hooks for the procurement custody schema.

Regular model columns are owned by Odoo's ORM.  This hook runs only after a
fresh install has created those tables, so it is the safe place to add the
partial/composite PostgreSQL indexes and build the SQL reporting view.
Existing databases use the versioned migration instead.
"""


def post_init_hook(env):
    env.cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
            baseer_procurement_custody_settlement_active_batch_line_uniq
        ON baseer_procurement_custody_settlement (batch_line_id)
        WHERE state = 'active'
        """
    )
    env.cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_procurement_custody_company_pool_uniq
        ON baseer_procurement_custody (company_id)
        WHERE is_company_pool
        """
    )
    env.cr.execute(
        """
        CREATE INDEX IF NOT EXISTS baseer_procurement_custody_event_pool_lookup_idx
        ON baseer_procurement_custody_event
            (custody_id, representative_partner_id, state, event_date)
        """
    )
    env.cr.execute(
        """
        CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_pool_lookup_idx
        ON baseer_procurement_custody_settlement
            (custody_id, representative_partner_id, state)
        """
    )
    env.cr.execute(
        """
        CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_allocation_idx
        ON baseer_procurement_custody_settlement
            (company_id, custody_id, state, batch_line_id)
        """
    )
    env.cr.execute(
        """
        CREATE INDEX IF NOT EXISTS baseer_procurement_custody_settlement_company_state_idx
        ON baseer_procurement_custody_settlement (company_id, state, batch_line_id)
        """
    )
    env.cr.execute(
        """
        CREATE INDEX IF NOT EXISTS baseer_procurement_bill_allocation_request_line_idx
        ON baseer_procurement_bill_allocation (request_id, batch_line_id)
        """
    )
    env['baseer.procurement.custody.monthly.statement']._rebuild_view()
