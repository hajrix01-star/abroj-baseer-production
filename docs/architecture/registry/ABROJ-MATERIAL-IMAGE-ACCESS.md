# ABROJ-MATERIAL-IMAGE-ACCESS — Selected-company image delivery

- Scope: Abroj project-costing material-library images on QA. No change to production or to Odoo core.
- Owner: `abroj_project_costing`; version candidate `19.0.1.5.2`.
- Root cause: the 36 Abroj material images are stored, but `/web/image` is a separate HTTP GET without the selected-company context sent in the web client's RPC calls. The global record rule therefore evaluates the user's default company, rejects the Abroj material, and Odoo returns its image placeholder with HTTP 200.
- Boundary: only `abroj.cost.material/image_1920` reads the first company ID from Odoo's `cids` cookie. The ID must belong to the current user; Odoo's native record lookup then runs under that single selected-company context and still enforces ACLs and all record rules. Other models/fields are unchanged. Material-image access tokens are rejected. Callers without a browser cookie retain the existing Odoo context and checks.
- Data: no migration or image mutation. Uploaded images remain attached to their original company. Rollback is the previous module code.
- Verification: isolated QA database clone upgraded and selected-company authorization tests passed, including permitted, disabled, unauthorized, malformed-cookie, unrelated-model, and token cases. The production QA visual result must be confirmed separately after deployment; HTTP 200 alone is not proof of the image bytes.

## QA outcome

- Source commit `f6b2e389` deployed to QA only after a fresh database dump and module archive; module upgraded to `19.0.1.5.2` and only the QA Odoo service restarted.
- With the real administrator and material 109, selected-company cookie `56` returned the record and 3,178,828 base64 image bytes; cookies `1` and `999` were denied. All 36 Abroj material images remain stored; other companies have none.
- The browser permission verifier was unavailable, so a visual browser assertion is not claimed. The user should refresh the material list with Abroj selected for final visual acceptance. Live deployment remains out of scope.
