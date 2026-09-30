# ABROJ-MATERIAL-IMAGE-ACCESS — Selected-company image delivery

- Scope: Abroj project-costing material-library images on QA. No change to production or to Odoo core.
- Owner: `abroj_project_costing`; version candidate `19.0.1.5.2`.
- Root cause: the 36 Abroj material images are stored, but `/web/image` is a separate HTTP GET without the selected-company context sent in the web client's RPC calls. The global record rule therefore evaluates the user's default company, rejects the Abroj material, and Odoo returns its image placeholder with HTTP 200.
- Boundary: only `abroj.cost.material/image_1920` reads the first company ID from Odoo's `cids` cookie. The ID must belong to the current user; Odoo's native record lookup then runs under that single selected-company context and still enforces ACLs and all record rules. Other models/fields are unchanged. Material-image access tokens are rejected. Callers without a browser cookie retain the existing Odoo context and checks.
- Original access fix: no migration or image mutation. Uploaded images remain attached to their original company. Rollback for that fix is the previous module code. A later, separately approved QA-only image optimization is recorded below.
- Verification: isolated QA database clone upgraded and selected-company authorization tests passed, including permitted, disabled, unauthorized, malformed-cookie, unrelated-model, and token cases. The production QA visual result must be confirmed separately after deployment; HTTP 200 alone is not proof of the image bytes.

## QA outcome

- Source commit `f6b2e389` deployed to QA only after a fresh database dump and module archive; module upgraded to `19.0.1.5.2` and only the QA Odoo service restarted.
- With the real administrator and material 109, selected-company cookie `56` returned the record and 3,178,828 base64 image bytes; cookies `1` and `999` were denied. All 36 Abroj material images remain stored; other companies have none.
- The browser permission verifier was unavailable, so a visual browser assertion is not claimed. The user should refresh the material list with Abroj selected for final visual acceptance. Live deployment remains out of scope.
- Follow-up after the owner still saw placeholders: Odoo's image widget uses the material `write_date` as its image URL cache key. The permission fix did not change those dates, so previously cached placeholders could persist without a new `/web/image` request. On QA, an ORM write of each material's unchanged `active=True` value advanced the cache key for exactly the 36 imaged Abroj materials; assertions verified their names, categories, codes, and reference costs stayed identical. No image bytes or other companies were changed. A fresh browser load remains the visual acceptance check.

## QA image optimization (2026-09-30)

- After the owner confirmed images were visible, they approved compression while retaining the existing backgrounds. This was an operational-data change through the Odoo ORM, not a module or Odoo-core change. It affected only the 36 imaged Abroj materials (company 56); no images were added for other companies.
- The original 1254×1254 PNGs were resized with LANCZOS to 800×800 and encoded as WebP, quality 82. Total stored image bytes fell from 64.02 MiB to 1.34 MiB (97.9% reduction). Names, codes, categories, reference costs, and active flags were asserted unchanged before commit.
- Recovery artifacts on QA: `qa/backups/baseer_qa_pre_material_image_optimization_20260930.dump` and `qa/backups/baseer_material_images_original_20260930.tar` under `/srv/abroj-baseer-production/`. The tar contains all 36 original PNGs and a SHA-256 manifest.
- Post-write verification reopened all 36 ORM images and confirmed WebP encoding at 800×800; all 36 backing attachments had MIME `image/webp` and matching byte sizes. Browser visual confirmation after the optimization remains with the owner; it is not claimed here.
