"""Add lookup indexes for existing vendor-bill settlement.

This upgrade does not create people, accounts, journals, custody movements,
or accounting entries, and it does not settle any historical bill.
"""


def migrate(cr, version):
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_custody_settlement_vendor_bill_uniq
        ON baseer_procurement_custody_settlement (vendor_bill_id)
        WHERE vendor_bill_id IS NOT NULL AND state = 'active'
        """
    )
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_rep_invoice_settlement_vendor_bill_uniq
        ON baseer_procurement_representative_petty_cash_invoice_settlement (vendor_bill_id)
        WHERE vendor_bill_id IS NOT NULL
        """
    )
    cr.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS baseer_vendor_bill_settlement_alloc_uniq
        ON baseer_procurement_vendor_bill_settlement_allocation (settlement_id, advance_id)
        """
    )
