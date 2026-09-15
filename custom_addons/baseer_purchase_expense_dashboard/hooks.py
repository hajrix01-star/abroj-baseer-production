def post_init_hook(env):
    """Keep the bounded dashboard query index-owned as history grows."""
    env.cr.execute("""
        CREATE INDEX IF NOT EXISTS baseer_supplier_bill_dashboard_lookup_idx
        ON account_move (company_id, invoice_date, currency_id)
        WHERE state = 'posted' AND move_type IN ('in_invoice', 'in_refund')
    """)
