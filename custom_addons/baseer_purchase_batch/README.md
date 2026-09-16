# Baseer purchase batches

This QA feature records up to 50 summarized supplier invoices in one native Odoo form. It creates native vendor bills and, for paid rows, native payments. It does not receive inventory.

## Configuration

Native Odoo selects the expense account for a productless vendor-bill line: supplier history, then the purchase journal default. The batch verifies an active expense/direct-cost/depreciation account belonging to its company. No category, synthetic service product or custom posting map is needed. Missing or unsuitable accounts require review in Accounting.

Native analytic distribution models supply the allocation using their configured criteria, including supplier contact tags. A tag alone is NOT an analytic allocation: a matching native model must exist. Existing completeness/ambiguity validation remains in place for companies requiring spend classification. The batch does not inject a competing distribution or change historical bills.

Paid entries require an existing outgoing bank/cash payment method that can immediately settle the invoice. Enable the explicit Credit switch to pay later; it clears and disables the payment method. With Credit off, a payment method is required. The feature does not modify bank or payment settings.

Suppliers must be active shared contacts or contacts assigned to the batch company; their commercial parent must also be shared or belong to that company. A new supplier is eligible before its first bill when native journal defaults are configured. Native payable accounts and other accounting properties retain their existing company-dependent behavior.

## Entry

1. Select the active company in the Odoo header, then open **Vendors → Purchase Batches**. The list is scoped to that company and new batches inherit it. Its name stays visible and read-only; enter the administrative entry date. A draft opened under a different active company must be edited after switching the header back to its company.
2. Add invoice rows: supplier, invoice date, supplier reference, gross amount, VAT 15% switch, Credit switch and payment method. No category or entry type is requested. Enable VAT for the company's standard purchase tax. Credit defaults off; enable it explicitly for a payable invoice.
3. Description, computed net/tax and original bill links are available as optional columns and in the full row form.
4. Normal **Save** keeps a draft. **Save and approve** validates all rows and creates their native accounting documents in one transaction. Payment date equals each row's invoice date, independently of the batch entry date.
5. Open **Vendor Bills** or a row's original document link to inspect the resulting native records. Print the batch summary from **Print Summary** or the native Print menu.

Approval fails as a whole if a row is invalid; it must not leave partial documents. Approved batch inputs remain immutable. The reviewed financial correction workflow supports historical and productless bills and preserves their original expense account when correcting supplier or amount.

## Mobile and language

The same native one2many uses an editable list on desktop and invoice cards on small screens. Tap a card to open all fields in the row form. English and Arabic labels use Odoo translations and native RTL/LTR controls. There is no additional frontend framework or JavaScript calculation.

Desktop lists, mobile cards and row forms no longer show a category. Text follows the interface direction, dates are centered and monetary values use aligned Western digits. Phone cards group supplier/amount, date/reference and explicit credit/payment/tax status. Intermediate widths retain Odoo's native table scrolling.

Existing rows with a different or historical tax show the actual tax name read-only instead of the 15% switch. A batch containing these rows also shows an Applied Tax column. No existing invoice tax is rewritten by the presentation change.

The batch date fields extend Odoo's native date widget only to display Western digits (0–9) in both languages. Dates, calendar selection, validation and persistence retain their native behavior; no global locale settings are changed.

## Print

The A4 landscape summary groups invoice date, supplier/reference, description, payment and gross/tax/net into seven columns. It has no category column. Money strings come from the backend; QWeb performs no financial arithmetic.

Installation and acceptance in the main database are outside this QA delivery.

## Historical compatibility (NBC1)

The optional readonly `category_map_id` remains for historical evidence only. New public entry/write cannot set it. Old drafts also use productless posting, ignoring their old mapping. Existing bills and distributions are not rewritten. The supplier's old selector and batch category setup menu are removed by migration.

The old mapping model is retained because HR services use it for their own invoices and historical bills retain references. Removing that separate dependency requires a tested migration, not deletion of business data. Decision and evidence: `docs/build-governance/BUILD-GOVERNANCE.md`, NBC1.
