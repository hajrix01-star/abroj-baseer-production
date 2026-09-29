# HR services — supplier/provider source review

Date: 2026-09-08. Read-only source study of `D:/Codex/Baseer-ERP`; no application or database changes. Scope: supplier/provider identity, input defaults and employee-service references. Existing Odoo source reviewed only for integration points; live records and report behavior belong to the other reviewers.

## Source findings

- `apps/api/prisma/schema.prisma:269,3888`: one `FinanceSupplier` model, with `supplierType = PURCHASE | EXPENSE`. There is no separate HR service-provider master in the inspected path. Fields: `tenantId`, `companyId`, optional `counterpartyIdentityId`, default `categoryId`, Arabic/English names, phone, tax number, VAT-registration flag, favorite flag and active/archive status. Services, outflow documents and supplier dues reference this same supplier model.
- `schema.prisma:3852`: `FinanceCategory` owns `accountId`, optional `suggestedSupplierId`, parent, code, kind, posting flag and company/tenant. Supplier-to-default-category and category-to-suggested-supplier are distinct convenience links.
- `apps/web/src/finance-supplier-form-dialog.tsx:45`: supplier input chooses invoice type (purchase/expense); default category choices must be active, posting categories of that type. API `finance-master-data.service.ts:167` also validates the match.
- `apps/web/src/finance-setup-workspace.tsx:8`: finance workspace has a suppliers view. `finance-copy.ts` labels the common list "الموردون". No separate provider UI was found in the finance supplier paths inspected.
- `apps/api/src/hr/hr.service.ts:586`: a service supplier must be active and belong to the same tenant/company; its category must be an active posting EXPENSE category. HR's inspected validation does not additionally restrict the supplierType enum, so it is inaccurate to claim that only EXPENSE suppliers can currently be selected there.
- `hr.service.ts:599,660` and `apps/web/src/hr-services-workspace-runtime.tsx:35,175`: service type proposes category and that category's suggested supplier; explicit user choices prevail. Default codes: issuance/renewal/exit-reentry → E2-4; sponsorship transfer → E2-8; medical insurance → E4-2; health certificate → E2-9. Flight tickets and OTHER have no automatic code in this mapping.
- `apps/api/src/finance/finance-foundation-seeds.ts:148`: standard selectable supplier seeds include utilities, ministries and platforms (Passports, HRSD, Qiwa, Absher Business, Muqeem, Wafid etc.). These are source templates, not evidence that all exist in a live company.
- `company-finance-setup.service.ts:90`: selected provider seeds become ordinary company suppliers with category/type links. Automatic category suggested-supplier assignments in this routine cover electricity/STC/water only; the mere presence of Passports or Muqeem does not guarantee an HR category's suggestion is filled.

## Recommended Odoo adaptation

1. Use the same native `res.partner` supplier for purchases and HR services. A "service provider" filter/tag can give a convenient list without duplicating legal parties. Do not create a new provider ledger or master model.
2. Preserve the agreed company visibility policy; company-specific defaults must not leak across companies. The old code deliberately separates company-owned financial supplier records from optional tenant-wide identity, so cross-company partner merging should not be inferred from matching names.
3. Configure each service type with a service product, company expense account/category and optional suggested provider. Keep employee-service type authoritative for suggesting the expense category; a provider may offer several services, so its single default must never lock the account for every transaction.
4. Reuse the current Odoo `baseer_purchase_category_map_id` on partners where appropriate: `custom_addons/baseer_purchase_batch/models/res_partner.py:10` already defines a company-dependent, accounting-manager-controlled default. Avoid adding a competing global partner default.
5. Native product expense properties are company-dependent (`odoo/addons/account/models/product.py:57,75`); use the product/category account resolution, not a separate chart per provider.
6. The service links to its native supplier bill/line, so its expense is booked once. Reuse an already-entered supplier invoice when applicable instead of creating another bill through HR.
7. Seed missing configuration only after explicit, stable matching; do not reproduce the old seed's name-only matching or overwrite existing category choices. Generic providers and tax numbers are not facts to invent for a new company.

Practical example: the employee gets a ticket service; the vendor is the existing travel agency partner; the selected service product supplies the travel expense account; the supplier bill and its payment are ordinary Odoo documents. HR reports filter by employee/service, supplier reports filter by partner, and the general ledger groups the same single expense by account.
