# QA session ticket numbers

2026-11-20. QA release only.

- G0. Cashiers share one counter per new session. Persist the first nonempty order's number, preserve it across payment, kitchen changes and reprints. Existing sessions retain their legacy numbers. Invoice posting, UUIDs and fiscal sequences remain owned by Odoo.
- G1. The owner's critical workload is two devices sharing one session. Verify simultaneous saves, retry, independent sessions and offline recovery. Per-session writes and an indexed uniqueness constraint bound the work to the current session.
- G2. The database allocates the number in the order transaction. Clients read the stored value. Paper combines the originating session ID and number, the cashier sees the short number. A split child or refund is a distinct order. Offline unsaved orders await allocation.
- G3/G4. Use the existing Odoo ORM, PostgreSQL, OWL slots and printing templates. No external dependency. Preserve positions and direction of the printed identifier. Verify Odoo model tests, compiled templates, two-client behavior and paper payloads. Review this contract against runtime sources before deployment.

G5. The first persisted order line assigns a number within the existing order transaction. Odoo's POS sync returns the short number and printable label to the client. The kitchen bridge freezes the same server label in its original job. Native draft and paid receipts render their existing headers. A restaurant's unnamed direct sale gets its number on saving, sending or printing to preserve native transfer-to-table behavior.

G6. On the QA host's isolated POS database, three Odoo model tests passed on November 20. They cover empty orders, protected server fields, retries, rollback, independent sessions and migrated orders. Deployment acceptance additionally exercises two clients in separate transactions.
