# POS invoice discounts

New orders use Odoo 19 `pos_discount` and the Baseer fixed-amount extension. The extension enforces permissions and caps on the server, records approvals, allocates exact shares to product lines, and validates share-based refunds. A manager can set up a company-owned native discount product in POS settings. Payment of an order with a fixed discount requires a connection; ordinary offline sales, synchronization and removal of server-cancelled orders on other devices are native Odoo behaviour.

The former custom invoice discount and shared-draft/offline discount flows were retired on 2026-11-25. Their stored fields, audit events and historical reporting allocations remain available. Legacy-discounted orders cannot be refunded in POS (that would refund items at full price): accounting issues a credit note on the order's invoice instead. Unsynchronized orders containing old discount evidence are retained on the device for manager review.
