# Baseer POS invoice discount

New orders use Odoo 19's native `pos_discount` button, discount lines, tax computation, synchronization, invoices and Saudi EDI. The button offers a fixed tax-inclusive amount alongside the native percentage when fixed discounts are enabled and the cashier is authorized. Fixed discounts recalculate as the basket changes; the configured amount cap is tax-inclusive, and zero means no extra cap. Percentage discounts retain the existing percentage limit.

A POS manager can enable fixed discounts and allow all cashiers or only POS managers. The server checks the configuration, cashier identity, cap, eligible total and computed amounts when an order synchronizes; it records the approval in the order chatter. The client cannot grant itself manager access.

Use **Set up company discount product** in POS settings to create or reuse a dedicated company-owned product and assign it as the native discount product. Set the legacy discount income account first if needed. The action is manager-only; installation and upgrade do not automatically create products. The print bridge excludes native and legacy discount lines from kitchen/preparation tickets.

Discounts may be applied offline, but payment of an order containing a fixed discount requires a connection. The server is the authority and this prevents two devices from paying different snapshots of a shared order. Native synchronization handles ordinary shared drafts, including removal of server-cancelled orders on other devices.

The server stores exact, rounded per-product discount shares for reporting and native refunds. Partial refunds use those shares, with the final refund consuming the remaining rounded amount. Historical legacy discounts and refunds retain their original lineage and reporting allocation. Legacy RPCs and fields remain available for existing orders, including the manager's stuck-draft recovery and remote-status checks.

Legacy retirement is staged: phase 1 (now) disables the legacy flow for new orders while preserving existing state; phase 2 removes legacy JavaScript only after QA proof and an owner decision; phase 3 considers dropping legacy fields after a data retention review. The legacy maximum percentage and income account remain relevant to native configuration and enforcement; the old amount limit and product are retained for historical operations.

## Verification

Run the module's Node tests and Odoo tests on an isolated database. See `docs/build-governance/POS-GLOBAL-DISCOUNT-QA.md` for accounting and Saudi EDI acceptance evidence and outstanding QA gates. A successful XML export alone does not establish ZATCA acceptance.
