# SD2 delivery handoff (pending MAIN promotion)

Candidate:973395f87b62c8d09f1e6fdc301a7d89e2988d56; parent2d2ff102d11a53fc2fca1b8c1707fc81c77537ab. Module baseer_sales_dashboard19.0.1.1.0. Frozen1118files;1109identical,9changed within this addon; all1106other-addon baseline files remain unchanged.

Implemented compact five cards with comparison arrows; combined sales/customer timeline; faded labeled empty preview; actual native top date filter including All time/month/quarter/year/custom; independent shift table/chart metric selection; payment table/chart from actual amount-matched allocation lines and coverage disclosure. Backend owns all financial values and formatting. No core/vendor/dependency/schema/business transaction changes.

Validation:backend75/75(UI/action/date/payment/shift capacity/permissions no-write) andUI34/34 plus actual browser. Historical load measured only serial locally:10years7306current summaries with empty preceding comparison,0.173–0.262s; no claim for100year/concurrent production certification. Dates >100years or source rows>100000 explicitly rejected without truncation. Native filter formatting scoped only to this dashboard. Dynamic actions reuse existing native views.

QA:http://localhost:18070/odoo/dashboards?dashboard_id=9, companyQAARZ. Owner's demo retained683summaries3415allocation reporting fixtures, representing368daily original totals across current/prior184days. Actual6monthcurrentwindowMarch1–August31,2026. No native posting represented by these fixtures. QA stays running. Demo user's credentials were supplied separately, not stored here.

Source/rollback: see candidate.json/candidate-source.zip; protected promotion requires coherent old MAIN backup before moduleupdate, exact protected business-row comparison, then runtimecheck. Do not downgrade against newer metadata blindly; restore coherent DB/filestore/source bundle using recorded backup. MAIN promotion/result section follows after independent GO.

## MAIN promotion completed

Promoted2026-09-09 with independent PREDEPLOY-GO. Runtime19.0.1.1.0, pinned image and three frozen read-only source mounts; HTTP200, no pending moduleoperations. All367protected business tables compare exactly before/after upgrade; no business/schema/previewdata change. Coherent pre-upgrade backup and post-release backup both verify651attachment references; database dump TOC and filestore hashes verified, full restore rehearsal not repeated for this presentation/reporting delta. Current source bundle is included in post-release backup. Original links: http://127.0.0.1:18069/odoo/dashboards?dashboard_id=8 . QA preview link usesdashboard_id=9; recordIDs differ between databases and must not be copied across environments.

Actual MAIN ARZ dashboard opens with native filter, five faded dash cards, decorative preview, empty shifts/payment sections as expected. Screenshot main-empty-ar.png. QA remains running with the owner's synthetic preview; no test fixtures remain from rollback-only backend suite. Preview tab left open on March1–August31,2026.
