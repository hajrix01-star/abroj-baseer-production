# LIVE1 — Bounded public-source audit

2026-09-09. **No confirmed publication blocker found in the inspected frozen source.** This is a bounded source/privacy and notice check, not a full security audit or a legal redistribution opinion. No source files, databases, containers or repository remotes were changed by this review.

## Source and coverage

- Frozen source: `.local-backups/sales-dashboard-application-share-20260909/candidate`.
- Identity: `1108f2a8fc0edee2f61d728135feee02590a8f46`, checked against `docs/releases/2026-09-09-sales-dashboard-application-share/candidate.json`.
- **1,118/1,118** physical source files match their manifest SHA-256. Only `custom_addons` and `third_party_addons` are present in that inventory.
- Included the contents of both vendor ZIPs: **316** file members. Scanned **1,209** UTF-8 text streams across physical files and archives.
- Checked common private-key markers, provider/API token formats, quoted/unquoted password and secret assignments, credential-bearing connection URLs, bearer literals, personal-field literals, long numeric identifiers, employee/payroll data records and SQL data dumps. Inspected matched test contexts with literal values redacted.
- Export-specific wrapper files and Git history are outside this source-only review; the separate LIVE1 export review owns them. The intended public allowlist excludes local documentation, operational evidence, backups, environment/configuration secrets and database/filestore exports.

## Classified findings

| Path / type | Count | Classification |
|---|---:|---|
| All inspected text: real credentials, private keys, recognizable service tokens or credential-bearing URLs | 0 confirmed | No blocker found by these patterns; not a guarantee against every encoding or custom secret format. |
| `third_party_addons/erp_heritage_19/eh_account_base/tests/test_move_seal.py`: access-token literals | 3 source occurrences; repeated in both ZIPs | Synthetic security-test inputs in raw-RPC-write and unsealed-delivery lifecycle rejection tests. No live service credential established. |
| `third_party_addons/odoomates_19/om_hr_payroll/data/hr_payroll_demo.xml` and `third_party_addons/openhrms_19/hr_payroll_community/data/hr_payroll_community_demo.xml` | 2 employee demo records | Bundled vendor demo data; no imported operating-company employee dataset found. |
| `third_party_addons/openhrms_19/hr_payroll_account_community/tests/test_hr_payroll_account.py` | 1 bank-account literal match | Vendor transaction-test fixture alongside generated employee/payroll test records, not an identified private payroll import. |
| `custom_addons/baseer_service_seed/models/catalog.py` | 20 generic providers; 3 VAT literals | Public corporate supplier seed metadata; classification resolved below. No numbers reproduced here. |
| `security/ir.model.access.csv` under custom/vendor modules | 11 files | All CSVs are model-access declarations. No employee spreadsheet, payroll import, SQL dump, `.env`, private-key file or database file found in the physical inventory. |

The three supplier identifiers belong to **الشركة السعودية للطاقة / Saudi Energy (SEC, formerly Saudi Electricity), شركة الاتصالات السعودية / stc, and شركة اتحاد اتصالات / Mobily**. These are major corporate utility/telecommunications providers, not the user's private employees or company account records. All three literals match the locally documented public-source records in `docs/build-governance/common_service_parties_vat_research.json` exactly. That research, dated 2026-09-08, marks them `officially_published` and cites the provider's public certificate, invoice page or company page. `COMMON-SERVICE-PARTIES-SEED-DECISIONS.md` independently records the generic seed scope and source links. This review did not reverify current tax-registration status or repeat live website retrieval; that accuracy limitation does not make these public supplier identifiers secrets.

## Preserved notices

- All **9** third-party addon manifests retain license, author and website metadata: **8 LGPL-3**, **1 AGPL-3**. The AGPL addon is `third_party_addons/erp_heritage_19/legion_enterprise_theme`; do not describe the entire export as having one replacement permissive license.
- Third-party physical text retains copyright notices in **159** files, LGPL references in **57** files and an AGPL reference in **1** file. Counts overlap. Byte identity to the frozen manifest establishes that these source notices have not been stripped by this review.
- `custom_addons/baseer_report_layout/static/fonts/LICENSE.txt` retains the SIL Open Font License 1.1 notice for the **2** bundled fonts.
- Both original vendor ZIP archives were included in the scan. No obvious missing-license or proprietary-only manifest declaration was found. This does not establish every upstream asset's rights or replace compliance with its existing license.

## Limits and disposition

No imported private employee/payroll/business dataset was identified in the inspected text and structured-data files. The **209** bitmap images/GIFs are under third-party addons; they were inventoried but not individually OCR/visually audited. SVG text was included where UTF-8 decodable; arbitrary encoded payloads and full Git history were not exhaustively analyzed. No credential was tested against an external service.

**Disposition: no confirmed source-secret/privacy blocker for the authorized public allowlist export.** Preserve existing module/font notices and keep operational data/configuration outside the export. The public export's final manifest, added wrapper files and actual push remain the root/release reviewer's responsibility.
