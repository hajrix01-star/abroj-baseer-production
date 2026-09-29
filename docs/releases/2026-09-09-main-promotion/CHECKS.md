# MP3 read-only acceptance

`acceptance-checks.py` adapts FA2 `main-acceptance.py` for the frozen PB2 candidate `807712c3dd78db4bdbec15d6a264b5b72feec951`. It is prepared for root to execute **only after upgrade approval**, first on `baseer_main_rehearsal_20260909`, then on `baseer_dev` at the authorized cutover. No execution is claimed in this preparation note.

The script allowlists those exact databases, rolls back the shell transaction, and explicitly sets PostgreSQL `TRANSACTION READ ONLY` before checks. It always rolls back and writes an external evidence JSON named `acceptance-<database>.json` under the runner's `/mnt/qa-evidence` output path. Failure remains visible in JSON and raises after the evidence is written. It does not create/write/delete business records, invoke seed hooks, initialize missing salary structures, calculate/approve payroll, render PDF attachments, or generate test data on MAIN. View compilation and defaults are read only; a hidden SQL write would be rejected by PostgreSQL.

Coverage:

- Exact installed versions for the 11 promoted Baseer modules and the two OdooMates payroll modules. Total installed module count is reported, not hardcoded to a prior QA inventory.
- Dynamically discover active independent Saudi/SAR companies. Check the explicitly requested MAIN company 3 is among them; no QA company identifiers are used.
- Validate each eligible company's payroll account classifications, reconciliation and journal scope; EOS expense/purchase journal; 15 seeded HR service mappings and company-scoped active expense products. Existing five-rule salary structures are checked by reading; absent lazy structures are reported without creating them.
- PB2 inclusion default, authorized explicit False default, retained field group, readiness metadata and report hook. EOS new-document V2/inclusive defaults retain explicit Gregorian confirmation. These are capability/configuration checks; no legal compliance finding or new employee/payslip is inferred.
- Native English/Arabic forms for payroll, employee, corrections, EOS, HR services, purchase batches and POS; pending badge, detailed run banner and native open-ended contract hint; shared provider and contribution-report namespace.
- SHA1 and byte-size verification for **all** file-backed binary attachment references against database metadata, with safe path containment and deduplicated reads. Database-backed payload rows are counted; their payload integrity and before/after data preservation belong to root's PostgreSQL backup/projection. URL and empty attachments have no file checksum.

This smoke acceptance complements the 228 PB2 functional checks and root's source/archive hashes, rehearsal, before/after accounting/HR projections and filestore backup evidence. It does not replace them. A checksum failure should be investigated against the pre-upgrade backup; the script never repairs or deletes attachments. Root owns execution logs, preservation comparison and promotion decision.
