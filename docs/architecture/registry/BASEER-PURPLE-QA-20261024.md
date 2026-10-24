# BASEER-PURPLE-QA-20261024

Status: approved colour direction; QA implementation in progress. No LIVE authority.

Impact: CONTROLLED presentation only. Parent reference: LEGION1 and QA-REFRESH-20261023. Base source `06d8364e`; current QA source observed `88422dd5f40d80db90a43f54c26c9f16b0f06362`. The user explicitly approved the final vivid-purple reference and previously requested both icon and theme on current QA.

Palette sampled from the approved reference: light `#7B38B9`, primary `#5B04A0`, dark `#4B0287`. White functional surfaces and native semantic status colours remain. Gentle gradient/glass treatment is restricted to navigation, primary controls and the executive revenue banner.

Owner: existing `baseer_legion_compat`, dependent on the unchanged Legion theme. Extend its SCSS and native WebManifest presentation hook; keep native scope/start URL, shortcuts, service worker, authentication and business logic. Static Baseer icons replace the generic installation icon; no company logo or operational configuration is rewritten.

Verification: native Odoo install/manifest/icon tests and backend asset compilation in a disposable database on the existing local Docker runtime, then QA desktop/mobile visual checks and installed manifest/static-asset verification. The temporary test database is needed because the new inherited manifest hook and QWeb selectors cannot be verified by syntax checks; use is one owner, with no load test or business-data copy.

Delivery: independent scoped review, successful PR checks and merge, then pinned module-only QA policy via the existing GitHub Actions/signed-request wrapper with its recovery pair. No direct writes to runtime release files. Revert through the saved QA recovery release if acceptance fails.

Evidence and exact release identifiers will be appended here.

Source verification: independent `purple_delivery_review` GO-source, no P1/P2. Native Odoo 19 install, public manifest, PNG dimensions/MIME, Apple icon/QWeb inheritance, authenticated webclient and actual `web.assets_web` CSS compilation: two focused tests passed, zero failures/errors on 2026-10-24. First run exposed only an incorrect test assumption about the native bundle name; corrected and rerun successfully on the same disposable database. White text contrast at gradient endpoints measured 6.76:1–12.67:1. No load, financial or concurrency test required for this delta.

Artwork: the Baseer baa icon was generated with built-in image_gen from the earlier reviewed concept; its mint dot is now pale lavender. PNG exports at 180, 192 and 512 pixels are included, with `purpose:any` (no maskable certification). Existing installations may retain cached names/icons until the browser refreshes the installed app metadata.
