# PP1 MAIN — Independent predeployment GO

2026-09-10, reviewer `priority_review`. **GO** to the user-authorized MAIN deployment of composite commit `a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c`, using the reviewed `pp1_main_release.py` guarded publish path. This decision permits the prepared deployment; completion still requires its runtime/preservation evidence.

The narrow review reused accepted PP1 G8 (`../2026-09-09-partner-priority/FINAL-REVIEW.md`), its28focused and6independent checks, UI and company-boundary evidence. No repeat application tests or application/runtime changes by this reviewer.

Independent source checks:

- Clean frozen Git HEAD is `a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c`.
- All1126files from current BP1 `80ab864153b9e337090d5a1286150e7a64ad6319` retain exact hashes, including browser printing.
- Exactly9new PP1 files match the approved `9424da9a50ecda8d0462dc44ce2e7f0ab4012427` hashes; no other source changes. Total1135files.
- Recomputed every frozen-file SHA256 and the source archive SHA256; no mismatches. Archive `ef1f61743fce39d604bf1bfed0d7d9a45db637020800844efd6329a7c024cb15` matches candidate.json. integration.json correctly links both accepted sources.

Deployment review compared `docs/build-governance/pp1_main_release.py` with established `bp1_release.py` and inspected the called backup helper. The adapted path verifies exact source/archive identities, old BP1 read-only mounts and pinned image, module state/no pending operations, and the expected compose source boundary before maintenance. It stops MAIN, acquires exclusive maintenance lock, takes coherent database/filestore/config/source backup with zero active database clients, validates dump TOC/attachment references, and fingerprints367protected business tables using all preexisting columns. It installs only PP1, requires unchanged original rows/columns before restart, updates both compose mappings and backup-source guard, and takes the post-release backup while MAIN is still stopped. Failures before restart leave MAIN stopped for evidence-based recovery from saved backup/config; no automatic downgrade or QA data copying.

Post-start checks require HTTP200, pinned-image/read-only frozen mounts, PP1 version19.0.1.0.0 installed, no pending module operations, existing browser-print module still installed, and no favorite seed values. This matches the scope: additive company-dependent favorite metadata and read-only ranking only. Daily backup/source mapping is included in the change.

No predeployment blocker found. The verified backup path does not itself perform a fresh restore rehearsal unless requested by its parameter; this review relies on the established previously exercised backup/recovery workflow and exact unchanged source boundaries, and does not claim a new restore test. Final deployment acceptance must record actual backups,367-table preservation, module/runtime identity and a native supplier-picker smoke check. No unrelated financial or concurrency rerun is required for this unchanged reviewed addon.

## Final MAIN acceptance — 2026-09-10

**GO — deployed MAIN release accepted**, composite commit `a8d533d67ee4ca3e4a7ce06fc44bc5e459fc192c`. Independent review of the completed deployment evidence found no open blocker. This appendix supersedes the predeployment-only status above; it does not expand the accepted application-test claims.

Reviewed runtime.json: HTTP200, PP1 installed19.0.1.0.0, no pending module operations, original pinned Odoo image, and all three addon mounts read-only on the accepted composite candidate. Both compose files and the daily backup helper now reference that same frozen release. Existing BP1 source remains preserved as verified before deployment.

Independently compared protected-before.json with protected-after.json by table/name/count/hash:367tables before,367after, zero differences. main-preservation.json matches the comparison and records only the additive favorite JSONB column. Reviewed coherent pre/post backups: zero-client snapshot flag true,787database tables covered,651filestore attachment references verified in each. The post-release source archive hash matches the accepted composite archive; the pre-release archive retains the prior BP1 source boundary.

Reviewed rehearsal.json: the current MAIN clone installed this composite successfully with BP1 still installed,367original business tables preserved, and frequency-sorted native searches in all3companies. Rehearsal ran without HTTP/cron or a MAIN-filestore mount. This is new deployment rehearsal evidence and supplements the earlier QA acceptance without repeating the unchanged feature suite.

Reviewed browser-evidence.json and independently viewed main-suppliers.png: the Arabic MAIN supplier list displays native stars beside supplier names; the recorded21supplier controls and native bill picker with8suggestions/Search More establish the live component integration. The unsaved form was discarded; no MAIN favorite values were changed. Favorite toggling and per-company independence retain their accepted isolated-QA evidence rather than mutating customer preferences for verification.

No further full-suite, financial-posting or concurrency retest is required for this exact accepted source. The previously documented one-reader capacity and English-text/RTL screenshot limitations remain explicit. Final deployment evidence supports the live PP1 release with original business data and the browser-print module retained.
