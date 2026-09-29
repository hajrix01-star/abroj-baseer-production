# IC1 postdeployment independent acceptance

Decision: GO

Scope: MAIN runtime and original-data preservation for source `24bc64d2a778590e8e8e6577eb3866d18727bc24`, module `baseer_financial_correction` version `19.0.1.0.0`. Reviewer: icons_release; no production financial test mutations.

The parser-only first initialization failure was recovered using the separately approved, hash-bound runner. Frozen source and acceptance evidence were preserved. Runtime evidence shows HTTP 200, the pinned Odoo image and all three accepted addon mounts read-only, installed version 19.0.1.0.0, and no pending or unrelated module changes.

Independently compared the before/after projections: all 368 protected tables retain their original column values, user memberships/company access and role presets are identical, the new permission default is true, and the correction audit is empty. The read-only MAIN smoke records Arabic/English view availability, five source entry locations and the settings field, with no business mutations. No QA data was migrated.

Both coherent stopped-service backups record 661 verified attachment references. All eighteen backup file sizes and SHA256 hashes were independently checked. A fresh database restore rehearsal was not performed; the backup manifests explicitly record that limit.

The clean public checkout at `7a2e0057640f63a43be6193e7e51b8fe8c027fdd` independently matches all 1,177 frozen source hashes. Final `github-publication.json` records the exact remote main commit, source-only publication and successful syntax/checksum verification. GitHub Actions run `34504859260` completed successfully for that exact head. Publication acceptance is complete.

The accepted functional scope and limitations remain those in `IC1-REVIEW.md`: cashier cannot use the shared correction action; accountants require the per-user flag; existing native draft/edit actions retain their prior permissions. No residual runtime/data blocker was found within that scope.
