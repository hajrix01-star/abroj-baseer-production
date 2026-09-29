# BP1 — Independent browser-print review

Reviewer: `/root/payment_seed_review`, 2026-09-09. Ownership: review documents only. Baseline: accepted SD4 source1108f2a and published source export5ba4857. No accounting re-audit or application edits by this reviewer.

## BP1-R01 — G0–G3 decision

**GO for implementation of `BROWSER-PRINT.md` with the agreed preparation-before-dialog clarification below.** No core/vendor modification or new server route is approved or needed.

- **G0:** intercept eligible native `qweb-pdf` report actions, preserve original server PDF bytes and report rights, and provide Print / Download PDF / Close in a native Dialog. Non-PDF and specialized flows remain native. This changes presentation and download handling, not report calculations or access. A browser print attempt or dialog close does not prove a physical print.
- **G1:** one authenticated PDF render per handled action. Reuse that blob for preview, retries of Print and Download. Up to five concurrent requests and typical1–20-page PDFs are assumptions to document, not measured capacity. The agreed request timeout is120seconds with AbortController, guaranteed UI unblock in finally, and a clear error on timeout; it may reject a report whose native generation takes longer. Release blob URL/iframe references when the ready dialog closes. No persistent storage or external rendering service.
- **G2:** native report URL construction and merged user/action context must be preserved, including wizard options and active IDs. POST to `/report/download` with native authenticated/CSRF semantics; retain the native response filename and native error conversion. Validate a successful PDF response before creating a blob URL; never render an HTML login/error response as a PDF. Server report attachment caching is an existing native side effect, not a new business-write feature.
- **G3:** existing Odoo19 registry, Owl/Dialog, download/error helpers and browser PDF capabilities. No PDF.js loading, extra dependency, HTML reconstruction or new rendering service. The reusable addon may supply the small transport/preview adapter required to retain the downloaded blob, while matching native behavior rather than replacing the server contract.

## Agreed callback and fallback semantics

Direct source inspection of `webclient/actions/action_service.js` established that **any truthy handler result triggers native `onClose` / `close_on_report_download`; false means try the native handler**. It has no handled-but-cancelled return value. Do not invent a truthy cancellation sentinel, mutate action/options to suppress callbacks, return false after already rendering a report, or resolve success on a failed/aborted fetch.

The selected implementation avoids a cancellable loading dialog: first prepare the PDF under native `ui.block`, with120second timeout/abort and finally-unblock. Failure rejects through the native error path. Only after a valid PDF exists does the preview Dialog open. The handler promise resolves truthy after that ready Dialog closes, letting the native action service perform callbacks exactly once. There is no in-flight fetch owned by this Dialog, so the original proposed abort-on-dialog-destruction requirement is superseded; blob/iframe cleanup on close remains required. Cancelling the system print dialog is not cancelling report preparation and never causes a paper-success claim.

Check the cached native wkhtmltopdf status before rendering. Unsupported/broken/absent states must fall through before a PDF fetch, preserving native HTML/error handling. The `upgrade` warning must also remain native: simplest is to fall through for that status; if explicitly handled, preserve its native warning and verify that behavior. Repeated fallback must not cause two PDF renders.

## Focused evidence before delivery

1. Verify transport and exact same-response bytes for generic IDs and wizard data, merged context, CSRF and server filename. Include denied report, escaped native server error, expired-session/non-PDF response, timeout and unblock behavior.
2. Verify no interception of non-PDF reports, wkhtmltopdf fallback, exactly one report fetch per handled action, and no callback before successful preparation/ready-dialog close. Verify callbacks once, including action-close behavior, and cleanup after close/download/blocked print.
3. Inspect actual QA Arabic and multipage native PDF, native Dialog controls and narrow layout. Show automatic print as an attempt with persistent explicit controls. Native PDF iframe limitations, unsupported browser printing and physical paper output must be reported honestly.
4. Bind addon/source/tests to the release candidate and preserve original business data using the accepted protected deployment. GitHub may receive the clean addon source, not generated employee/payroll PDFs or private browser/test evidence.

No whole-ERP, financial-capacity or physical-printer test is required for this bounded adapter. Final G8 approval awaits implementation and the evidence above; this is a build decision, not a release claim.

## BP1-R02 — Initial implementation review

Reviewed `baseer_browser_print` against Odoo19 report utilities, action service, Dialog service and native network download handling. The extension uses frontend assets only, with no core edits or server route/model. User/action context is merged in the same precedence; generic IDs and wizard options reuse native `getReportUrl`; POST includes authentication/CSRF, and valid PDF bytes are reused for preview and explicit download. Non-ok wkhtmltopdf states fall through before rendering. The native action service retains callback ownership because the handler resolves only after the prepared dialog closes. Blob URL cleanup is registered on component destruction.

Two transport compatibility findings were sent to the implementation owner:

- **P2:** native download maps HTTP502 and network failure to `ConnectionLostError`, while the initial adapter returned a generic error or fetch TypeError. Preserve the native connection-error class; retain the distinct timeout message and native serialized-server-error conversion.
- **Low impact:** native Content-Disposition parsing removes a final semicolon before parsing. Match that normalization so this response form preserves the native filename instead of falling back to the action name.

No financial/source/permission defect was identified in this source pass. Browser PDF iframe behavior, automatic print attempts and actual native error/callback flows remain subject to the focused tests and QA; source inspection alone cannot certify browser print reliability. No implementation edits were made by the reviewer.

## BP1-R03 — Compatible viewer delta, reopened G3/G4/G5

**GO for the bounded compatibility implementation; final release approval remains pending.** Actual QA found the native PDF iframe blank without a load event after 20 seconds in the in-app browser. This evidence supersedes R01's exclusion of PDF.js: reuse Odoo's existing `/web/static/lib/pdfjs/web/viewer.html` in the same-origin iframe, without adding a dependency or changing core/vendor files.

Keep the native viewer as primary when `navigator.pdfViewerEnabled !== false`; switch to the bundled compatible viewer when unsupported or after the agreed five-second load timeout, and retain an explicit compatible-preview button for a blank native viewer that nevertheless reports loaded. Both viewers and Download reuse the already validated original PDF blob. No second report render, server route, business write or callback-contract change is introduced.

Direct inspection of the bundled `viewer.js` confirms that `PDFViewerApplication` and `PDFViewerApplicationOptions` are exposed, but `beforePrint()` requires `pdfViewer.pageViewsReady`. Await application initialization, the document and `pdfViewer.pagesPromise`, then verify `pageViewsReady` before enabling or attempting print. The `documentloaded` event alone only waits for download information and the first page and is insufficient. Same-origin blob URLs satisfy the existing viewer origin check. Guard all asynchronous continuations after destruction or viewer replacement and clear timers/listeners on cleanup.

Retain the bundled 150 dpi print default. Compatible printing uses the bundled raster print service and must not be described as vector-identical printing; the downloaded PDF bytes remain original. No physical-printer result is claimed. Persistent Print, Download and Close controls remain available as appropriate, including a visible failure state if compatible readiness cannot be established.

R02 transport findings are closed by source inspection: network/502 responses now become `ConnectionLostError`, trailing disposition semicolons are normalized, and the timer's `try/finally` covers request-body construction. The test owner reports the pre-fallback 29 focused checks passed; that result does not cover this new viewer path. Add focused native/compatible readiness, timeout/manual-switch, close-during-await and single-blob checks, then actual compatible-viewer QA before freezing the release candidate.

## BP1-R04 — Fallback implementation and deployment guard review

The current fallback source reuses the original object URL in Odoo's bundled same-origin viewer. It waits for application initialization and page readiness, verifies readiness again before Print, and guards continuations after dialog destruction. The original Download path and action callback ownership remain unchanged. README accurately distinguishes the bundled 150 dpi raster print path from the original downloadable PDF. No additional dependency, model, route, permission or vendor modification was found.

Two bounded follow-ups were sent to the owner: immediately select the compatible viewer when the browser explicitly reports `pdfViewerEnabled === false`, and provide bounded warning feedback if the compatible iframe itself never emits load. The current five-second native timeout covers neither an immediate unsupported-browser path nor a subsequent compatible-frame load failure. Final acceptance awaits these clarifications and the updated focused tests/browser evidence.

Read `bp1_release.py`: freeze copies the accepted SD4 manifest's 1118 files byte-for-byte and permits only the new browser-print addon; candidate verification checks the frozen inventory, baseline hashes and ZIP hash. Publication requires a review document identifying the candidate, existing accepted image/read-only mounts, no pending module operations, a maintenance lock and a stopped-MAIN backup. Installation uses only the new module with HTTP/cron disabled. Existing rows and all existing columns across the accepted 367 protected business tables must match before restart. The helper explicitly leaves MAIN stopped on installation/preservation failure and documents backup-based recovery. This is preservation of the defined business-table projection, not a claim that all Odoo module/asset metadata remains identical. G8 will independently bind final evidence/source hashes and inspect the frozen ZIP; current status-only test-file checks in freeze are not themselves proof of that correspondence.

Read the existing four-report QA evidence: Arabic and English invoices, an Arabic payslip and a three-page invoice selection rendered native PDFs with signatures and recorded hashes; existing rows were preserved and the transaction rolled back. These four sequential renders are not a concurrency/load test, and they do not prove browser print delivery. No release GO is issued by this intermediate source review.

## BP1-R05 — Frozen candidate G8 closure

**GO** issued for `80ab864153b9e337090d5a1286150e7a64ad6319` in `docs/releases/2026-09-09-browser-print/PREDEPLOY-GO.md`. Independently matched 1126 frozen/ZIP files, all 1118 unchanged baseline files and the eight new addon files; final 45/45 focused checks match the transport/dialog/XML hashes. R04's two follow-ups and the test owner's duplicate-load print/timer races are closed in final source. Actual compatible-preview screenshot and recorded Print/Download/Close evidence reviewed. The post-install stopped-MAIN backup addition and current SD4 runtime baseline were verified. Physical output, separate-browser/mobile coverage and load testing remain explicitly unverified; final deployment closure is pending.

## BP1-R06 — Deployment closure

**Final GO** recorded in `docs/releases/2026-09-09-browser-print/FINAL-REVIEW.md` for the same candidate. Runtime evidence confirms installed `19.0.1.0.0`, HTTP 200, no pending operations and frozen read-only mounts. Independently compared all 367 protected before/after projections and verified every listed pre/post backup file hash; both captures record 651 attachment references and coherent capture. No fresh restore drill was performed. Independently queried successful GitHub Actions run `34404186973` on source commit `216c0a04091ed3bc367317f8967ab5a3ac22c8ce`. Existing test/browser limitations remain explicit; no broad re-audit or source retest was needed.
