# POS-S4 independent gates and delivery review

Reviewer: s2_review — حارس البوابات / المراجع المستقل. Date: 2026-09-08. QA only.

## R1 — G0–G4 before implementation

Read POS-SUMMARY-S4.md, existing pos_configuration.py/configuration_views.xml and installed native point_of_sale_dashboard.xml. Reused QA3 map, permissions and native financial-source evidence. No application or database changes by reviewer.

**G0–G4 approved for bounded implementation.** Reusing the unique dedicated pos.config card in the native dashboard, with two guarded read-only navigation methods, is the shortest safe route. No custom dashboard, JavaScript, schema or financial workflow is needed. Existing one-config-per-company unique index supports deterministic entry defaults. G5–G8 remain pending source/UI/route evidence.

Acceptance conditions:

1. Dedicated card is visible only for the active company even when multiple companies are allowed. This must be enforced in actual dashboard selection/domain, avoiding empty hidden placeholder cards. Native ordinary-register visibility and behavior remain as before.
2. Hide dedicated card's original cashier session buttons/body/menu links that imply a cashier operation; retain server open_ui rejection. Card navigation must check read ACL, active company, dedicated flag and active configuration, then return existing actions with clean company context and explicit archive domain. A stale/wrong-company RPC must not switch company or navigate using another configuration.
3. Merely displaying a card or opening either destination must not create a POS session, summary, closure, order, payment or ledger entry. Do not invoke setup/full posting validation just to navigate; original destination save/post validation remains authoritative.
4. Reuse native Bootstrap/Odoo styles, source English and Arabic translations. Desktop/mobile buttons must fit and remain accessible; no duplicated cashier/new-summary flow. The existing menu paths and source drilldowns remain available.
5. Evidence should include no/active/inactive configuration, multiple allowed companies with active-company switch, wrong-role/company route rejection, destinations, ordinary-register preservation and no record creation. Verify inherited dashboard XML loads against installed Odoo19, and freeze exact source/evidence/QA-only recovery identity before final GO.

## R2 — final bounded QA4 delivery

**GO لمعاينة QA فقط. G5–G8 معتمدة ومقفلة؛ G4 مثبتة بالواجهة الفعلية. لا موانع جوهرية مفتوحة.**

Candidate `baseer_pos_summary 19.0.1.2.1`, manifest `docs/releases/2026-09-08-pos-summary-qa4/manifest.json`. Independently verified26 source files,7 evidence files,26 ZIP entries and archive digest; zero mismatches. SHA256 **79af252077cd38ad5d00ca092b79f1d482be548b9967b32568b5fd390bc7a082**. Comparison to QA3 confirms exactly four changed files: module manifest, Arabic dictionary, pos_configuration.py and configuration_views.xml. Financial source models, calculations, posting and schema are byte-identical to QA3. QA DB backup digest independently matches **a52223a2b8991a1b9611a278473ba8ad8bd50ffc8a1c5bca3d621437af0546b4**.

Read-only source review confirms guarded existing-action navigation, no sudo, no automatic company switch, clean action context, explicit archive company domain and no creation/posting path. The inherited native XML uses three explicit cashier-body/title/user-badge targets and separate dedicated content/menu guards. Ordinary cashier cards retain their original native conditionals and actions.

Reviewed25 successful rollback-only route/default/domain/ACL/compiled-view checks and their executable script/log, including inactive configuration, ordinary-register rejection, non-POS user denial, multiple allowed companies with active-company change, hostile default stripping and unchanged tracked business-row counts. Actual desktop/mobile Arabic screenshots show the dedicated summary card beside the original cashier card, with fitting Enter summary/Saved summaries controls. Lead's native browser journey exercised both destinations and restored a fresh Arabic dashboard tab; stale view caching is documented. Canonical English source and386 translated Arabic terms are preserved.

Capacity impact is one existing native configuration record and two read-only actions; accepted S3 limits remain appropriate. This navigation-only delta justifies focused acceptance rather than re-running unchanged financial suites or claiming a new production load certificate. HANDOFF.md records source/DB recovery, fresh-tab refresh and QA-only destination. No cashier session, sales save, payment or WhatsApp Send was performed for S4 acceptance.

The previously accepted QA3 money/data map remains valid; S4 only adds a native configuration-card entry point. Final GO is limited to the frozen QA4 candidate on port18070 and does not authorize an original-database upgrade or deployment.
