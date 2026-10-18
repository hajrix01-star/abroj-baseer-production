# BWORK-BRAND-20261018 — Approved identity adoption

## G0–G3 contract (before app changes)

Fingerprint: source `daa8cee5` (app `78cd3907`, trial 0.1.8/build9), clean dedicated worktree. Owner explicitly approved supplied bwork ribbon logo and requested a reusable complete identity file plus application now. CONTROLLED presentation-only change; no new application, backend deployment, protocol or data model.

G0 scope: preserve approved artwork; deliver logo/icon/header/login assets, bilingual usage guide, source provenance, central tokens, editable presentation sources and a ZIP; apply name/identity to existing Odoo trial app, version0.1.9/build10. Keep package `com.baseer.bchat.trial`, storage namespace, app scheme, signing certificate and existing session/outbox so install is an update. No user data, financial logic, ACL, membership, company isolation, server origin/database or transport changes. No new features or animations. Approval is visual, not a legal clearance claim. Existing comparison research remains a provenance note, not grounds to reject owner's design decision.

G1 reuse: existing CW34–37 trial capacity/continuity baseline unchanged (owner's two-account trial, bounded outbox/media/cache). This delta adds fixed bundled artwork only, no reads/writes or polling. Check decoded image dimensions/byte size and launch/login/list narrow/wide layout. No new environment/load test: visual-only difference has no new backend capacity risk; actual usage remains two-account trial. No production capacity claim.

G2 ownership: existing ChatEngine/Odoo owns auth, UUID/ACK, permissions, rooms/receipts; untouched. RN owns branding presentation. Central `ui/Brand.tsx` and tokens in `ui/components.tsx` are reused across login/header/drawer; app.config.ts owns native label/icons/splash/version. Artwork byte-for-byte master is retained separately; any CSS/SVG display crop is explicitly a raster composition, not invented vector artwork. Do not redraw the approved logo. No schema/migration or changes to signed-in cache required. Rollback code from previous release; APK downgrade is device-dependent, so never instruct uninstall/clear-data as routine rollback.

G3 direct path: retain installed Expo/RN/react-native-svg and build chain, no new dependencies or library research/replacement. Source checks: existing check:odoo/test:odoo plus focused brand asset/config assertions. Build: existing low-worker native recipe, keep R8/release checks. Native acceptance via existing synthetic UI preview for AR/EN narrow/wide/login/drawer, plus normal-entry installed APK/version/signature/upgrade. No synthetic seams in shipped bundle. Distribution preserves established limited binary trial GitHub prerelease PAGE workflow and disclosure that published baseline source archives do not represent local source; no main/source push or QA/Live deployment authority inferred.

## G4 centralized identity and acceptance

| Before | After | Why |
| --- | --- | --- |
| BChat trial visible title and upstream assets | approved bwork artwork and BWork app name | owner-approved identity |
| generic blue palette | centralized blue/ink/surface/cyan/violet tokens | one maintainable visual source |
| no reusable brand export package | versioned artwork, guide and templates | future reuse without rediscovery |

Keep AR/EN RTL/LTR behavior, menu physical-edge convention and keyboard geometry. Never mirror logo. Western0–9 for numeric display. No financial decimals or calculations introduced. Keep semantic warning/danger colors separate from decorative palette. Fixed logo dimensions avoid layout shifts. No typography dependency update inside app; guide describes current UI system font unless fonts explicitly packaged and tested.

## Gate ledger

| Gate | State | Evidence / independent owner |
| --- | --- | --- |
| G0 | in_review | this contract; gate reviewer pending |
| G1 | in_review | inherited no-IO scope; architect/reviewer pending |
| G2 | in_review | unchanged identity/storage/backend contracts; reviewer pending |
| G3 | in_review | unchanged dependencies/build; reviewer pending |
| G4 | draft | existing approved logo + central component plan |
| G5–G8 | not_started | implementation/tests/build/delivery pending |

## Append-only operations

BW1 intent/read: root selected alpha-build-team first per owner instructions, followed scoped architecture/orchestration/brand/emil skills. Read current trial CW37 acceptance and exact UI/config owners; avoided unrelated root dirty worktree. Current baseline clean. Branch creation initially denied by filesystem; escalated only the narrow git branch command. No app code modified before independent gate review.

BW2 next intent: independent gate owner reviews G0–G4 before implementation; independent brand producer owns only new output package while root owns app integration/build. All collaborators preserve others' edits. Tests scale to visual change; no repeated backend load/auth/ERP certification.

BW3 implementation after BW-GATE-01 approval: root introduced central fixed-size accessible `Brand` component, consumed by login/header/drawer; replaced only central palette and visible app dictionary label. app.config selects trial-only BWork assets and0.1.9/build10, preserving package/scheme/upstream configuration. Independent producer rendered exact-source horizontal/icon/adaptive compositions and supplied master, inspected early assets; root copies these four files without alteration. Unit checks plus native prebuild will verify metadata and visual upgrade; no backend, transport, storage or dependencies touched. Official icon references checked: https://docs.expo.dev/develop/user-interface/splash-screen-and-app-icon/ and https://developer.android.com/codelabs/basic-android-kotlin-compose-training-change-app-icon ; adaptive glyph constrained to central66/108 safe circle. No store submission claimed.

BW4 tests/prebuild: brand assertions initially failed due to test-root path and an accidental duplicate asset-copy destination; corrected test paths, copied assets to canonical `assets/bwork`, verified duplicate hashes and removed only redundant copies/empty task-created nesting. Brand3/3 PASS, installed TypeScript PASS. Existing suite140/141 PASS; one old navigation assertion expected visible text rather than newly approved artwork. Updated that assertion to the actual Brand presence/absence on list/phone/wide with a named test seam; rerun only affected navigation+brand. No production behavior weakened. Expo prebuild completed with package.json unchanged and regenerated ignored Android label/icons/version, but also removed generated local.properties; restored ONLY prior SDK/NDK locations via apply_patch. Will verify certificate matches previous artifact before delivery. No operational data deleted or credentials accessed.

BW5 source review: independent reviewer reran16/16 affected tests, visually inspected all four PNGs and confirmed preserved original hash, unchanged backend/storage/dependencies. Corrected pre-existing README's initial-trial-uninstall wording to explicitly prohibit routine uninstall/clear-data on current branding update and prefer forward correction. Preview build denied Gradle cache lock by sandbox before execution; rerun narrow build command escalated, no code/config safety relaxation. Preview uses existing isolated package/fixture, never production entry. Await native evidence and final source freeze.

### BW-GATE-01 — independent G0–G4 decision, 2026-10-18

Reviewer: `bwork_gate_review`, independent of app implementation and brand production. Intent/read: reviewed this contract, alpha-build-team and its build-governance/central-design-system-catalog references, registry INDEX current CW37 baseline, app.config.ts, central ui/components.tsx and package.json. Read-only checks confirmed HEAD `daa8cee5`, existing app baseline `78cd3907`, version0.1.8/build9, package `com.baseer.bchat.trial`, existing scheme `bchat-trial`, and no app modifications at review. No unrelated architecture or backend re-audit performed.

| Gate | Independent decision | Evidence and acceptance boundary |
| --- | --- | --- |
| G0 | approved | Owner-approved artwork and presentation-only adoption have explicit acceptance, exclusions, rollback and separate source/artifact ownership. No authority to change data, transport, backend, auth or publish outside existing trial workflow. |
| G1 | approved | CW37 inherited trial/continuity baseline remains valid for fixed bundled artwork and two-account use; decode size and narrow/wide display are the relevant new limits. No new IO or concurrency and no claim of broader capacity. |
| G2 | approved | Existing engine/Odoo contracts and session/outbox ownership stay untouched; package, signing identity, storage and scheme must remain stable so update preserves device data. |
| G3 | approved | Retains existing Expo/RN/SVG/build toolchain; no dependency changes. TypeScript, focused asset/config checks, existing relevant UI checks and signed normal-entry APK upgrade acceptance are proportionate. |
| G4 | approved | Uses one central identity component at `mobile/chatwoot/src/odoo/ui/Brand.tsx` and shared tokens at `ui/components.tsx`; consumers use named login/header/drawer variants with fixed geometry, contain scaling and an accessible label where informative. Preserve existing RTL/LTR and physical menu edge, never mirror artwork, keep warning/danger semantic colors, and verify AR/EN at narrow/wide widths. Native label/icons/splash belong only to app.config.ts. |

G4 artifact contract: preserve supplied raster master byte-for-byte and document provenance. Raster compositions may be placed in editable HTML/CSS/SVG containers but must not be described as a true-vector redrawn master or transparent cutout. Retain white containment as needed. Use current UI font; package no new font dependency. Brand package must identify which files are artwork, compositions, source layouts and usage guidance; acceptance includes visual inspection and archive completeness. No new motion, screen family or public component abstraction is justified.

Result: G0–G4 approved for the stated delta; implementation may proceed. G5–G8 remain unapproved until implementation/build evidence exists. Reopen relevant gate if any contract, dependency, IO, identity or scope changes. This appendix supersedes the earlier pending states only for G0–G4; original history is retained. Impact: governance only; rollback by a subsequent corrective ledger entry, no app/data action.

### BW-GATE-02 — independent G5/G7 source review, 2026-10-18

Reviewer: `bwork_gate_review`. Intent/read: reviewed complete tracked diff against `daa8cee5`, new Brand.tsx/brand.node.test.cjs and four bundled PNGs, plus BW3/BW4. Ran `node --test src/odoo/ui/brand.node.test.cjs src/odoo/ui/navigation-layout.node.test.cjs` independently from mobile/chatwoot: **16/16 PASS**. `git diff --check` produced no whitespace errors. Did not rerun unchanged backend/auth/load checks; TypeScript and full existing suite are producer-reported evidence in BW4, not claimed as independently rerun here.

Source result: **G5 approved; G7 source implementation approved** for the presentation slice. Complete diff stays within visible artwork/name, central palette, trial metadata, documentation and focused tests; no engine/runtime/transport/storage/schema/backend/dependency-lock changes. Navigation test update replaces obsolete title-text detection with Brand component detection while retaining phone/wide/header/menu behavior assertions. Brand has fixed dimensions, contain scaling, accessible name, LTR art and no transforms; all three consumers use it. Trial0.1.9/build10 changes preserve package/scheme; upstream Chatwoot identity/artwork are conditional and retained. No new business numbers, financial authority or ACL path introduced. Existing architecture map remains valid.

Asset inspection: independently opened all four PNGs; approved lower-b ribbon and wordmark remain recognizable, white-contained, and are not presented as vector or transparent originals. SHA256: original `B85F025BF140E1269B3D070029C9758C630C567D03EABE53667693AF7F05DD8A`; horizontal `4878F4B09A78F63D2BCF491ABFFA01C5E6ECD90285E05C08B976CAE0A0DA58A6`; icon `CE5996677DBF99EE941413714926B56869EF9965D126A053A1035D33E69DE09D`; adaptive `E2FDBEFA30176B9CA1F3F29E0879E279EB11882ADDC86D11BDA05F4B66583433`. Native exports are1024px and151978/260892bytes; horizontal147588bytes; original1208050bytes. These bounded assets introduce no new IO or load scenario; G6 inherits the unchanged trial capacity boundary, not a fresh capacity certification.

Open delivery documentation item BW-DOC-01 (P2): ODOO-TRIAL.md initial introduction text still describes removing trial package as rollback. Clarify before final handoff that branding is an in-place update and routine rollback must preserve device data; Android downgrade is version/signing-dependent. Root notified with exact file/line. No app behavior changes requested by this review.

Limits: G7 final freeze and G8 delivery remain pending signed APK/source fingerprint, native normal-entry upgrade/signature/version checks, AR/EN narrow/wide visual evidence, and reusable identity archive review. This is approval to freeze/build reviewed source, not permission to assert native acceptance or publish. Impact: review/documentation only; no app/data mutation by reviewer.
