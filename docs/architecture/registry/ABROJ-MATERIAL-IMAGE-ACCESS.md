# ABROJ-MATERIAL-IMAGE-ACCESS — Selected-company image delivery

- Scope: Abroj project-costing material-library images on QA. No change to production or to Odoo core.
- Owner: `abroj_project_costing`; version candidate `19.0.1.5.2`.
- Root cause: the 36 Abroj material images are stored, but `/web/image` is a separate HTTP GET without the selected-company context sent in the web client's RPC calls. The global record rule therefore evaluates the user's default company, rejects the Abroj material, and Odoo returns its image placeholder with HTTP 200.
- Boundary: only `abroj.cost.material/image_1920` reads the first company ID from Odoo's `cids` cookie. The ID must belong to the current user; Odoo's native record lookup then runs under that single selected-company context and still enforces ACLs and all record rules. Other models/fields are unchanged. Material-image access tokens are rejected. Callers without a browser cookie retain the existing Odoo context and checks.
- Data: no migration or image mutation. Uploaded images remain attached to their original company. Rollback is the previous module code.
- Verification: isolated QA database clone upgraded and selected-company authorization tests passed, including permitted, disabled, unauthorized, malformed-cookie, unrelated-model, and token cases. The production QA visual result must be confirmed separately after deployment; HTTP 200 alone is not proof of the image bytes.
