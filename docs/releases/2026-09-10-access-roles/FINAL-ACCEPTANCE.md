# AR1 final independent acceptance

Decision: GO

Accepted deployed source: `98f9d4dced9f7a844d3d44e63f89d8d0d8218664`.

Reviewed runtime.json and main-preservation.json: MAIN responds HTTP 200, uses the accepted frozen read-only addon mounts and pinned image, reports roles module 19.0.1.0.0, three role groups and no pending module operation. All 367 protected business-table projections remain exact; existing module versions match the reviewed release expectation. Existing user group/company membership snapshots were independently compared and are identical. No existing user received a preset.

Coherent pre/post backup manifests record no connected clients and 651 verified attachment references each. Independently verified every recorded backup artifact size and SHA256 against files on disk. These backups have database_restore_verified=false; this acceptance does not claim a new restore drill.

Source acceptance remains backed by 300 passing integration checks with rollback, 12 lifecycle checks and nine UI evidence groups. Exact frozen source/archive/evidence binding is documented in PREDEPLOY-GO.md and AR1-REVIEW.md. Their stated scope and test limitations remain applicable.

Reviewed github.json records source-only publication of all 1156 accepted source files at GitHub commit `c021ceac3a7ce2c980687e1fd46f073a2ab21426` and successful workflow run `34482110786`. This publication evidence was supplied by the deployment owner; this reviewer did not perform the push or repeat remote CI execution.

No residual release blocker identified. Existing users continue with their previous access until an administrator explicitly assigns a preset. No MAIN mutation or browser action was performed by this independent reviewer.
