# Delivery status — purchase classification dashboard

## Frozen candidate

- Repository: `hajrix01-star/abroj-baseer-production`
- Branch: `codex/purchase-classification-dashboard-20260915`
- Candidate commit: `9b726f26e496e3e1697fa9bbcdac38b1c1397692`
- Live baseline: `f54d83bcda4ac3f771661b997c49ad7c193a35df`
- GitHub comparison: 18 commits ahead, 0 behind, merge base is the live
  baseline. The change allowlist is the receipt, the new
  `baseer_purchase_classification` module, and the purchase dashboard only.
- Archive: `baseer-purchase-classification-dashboard-9b726f2.tar.gz`
  (`10467c8aad2a94ef84d3ad2d891257e0d082a550b3538e526fcd83177b4ca891`).
- Payload receipt: 923 files,
  `a56526f36b8be9b1acac72318b542716cf216624cac5da7162d482cf8cb76ba5`.

## Evidence completed

- Fresh isolated installation from the frozen source completed.
- Focused upgrade test rerun from the frozen source completed: 11 loaded, 0
  failed, 0 errors. See `FROZEN-UPGRADE-TEST-TRANSCRIPT.txt`.
- Cross-company rule writes/moves are blocked and covered by regression tests.
- The dashboard no longer truncates parent category rows.
- Historical vendor bills are not modified or backfilled.

## Production decision: NOT YET READY

No live deployment has occurred. The remaining P1 is a Hostinger rehearsal of
the exact archive with an isolated production DB + filestore copy, verified
backup/restore evidence, and a host-specific maintenance/ingress block. Public
traffic must remain blocked until all local verification and rollback windows
have ended. The generic cutover template intentionally refuses to run unless
the host supplies matching enable/disable maintenance commands.
