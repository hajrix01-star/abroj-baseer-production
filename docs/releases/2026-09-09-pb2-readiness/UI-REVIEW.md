# PB2 UI verification

Reviewed frozen overlay commit `41c5dfe6e7a88f6511af0b2133c84b67a7d682eb`, version19.0.1.5.0, on isolated `baseer_pb2_test_20260909` with pinned native Odoo engine and actual158-module QA baseline. Browser origin `localhost:18072` isolates the session from the user's QA origin. No live payroll or contract was edited.

Desktop1440×1000 and mobile390×844, Arabic and English:

- New employee form starts with **Include in monthly payroll** checked and salary0, without invented start date; inspected and discarded without saving. `new-employee-default.png`.
- Employee payroll tab retains native HR contract controls and one native payroll section. Open-ended hint is present in both languages. `employee-ar-desktop.png`, `employee-en-desktop.png`.
- Mixed October run147 in cloned QA ARZ contains ready Emma8000 and fixture employee456 with missing start, effective amount0. Ready Emma was already present in the clone source, not created or changed by this test. The new fixture demonstrates the missing-start case without modifying an existing employment contract.
- Desktop shows a short yellow **بيانات ناقصة / Needs setup** badge, detailed warning column and run-level banner. Native wide payroll table retains horizontal scrolling; long cell text truncates using the existing native table behavior, with full warning available in the detail dialog. `run-ar-desktop.png`, `run-en-desktop.png`.
- Fresh mobile load uses existing native kanban cards. Full Arabic/English missing-start warning, name and zero amounts fit the card; ready row remains8000. `run-ar-mobile.png`, `run-en-mobile.png`. Resizing a previously loaded desktop form alone can retain its native list mode until reload; this is existing Odoo adaptive-view selection, not a new widget.
- Clicking the pending mobile card opens its detail dialog with the full warning, zero salary components and a link to employee456. `slip-ar-mobile.png`. Dialog discarded without writing.

The readiness feature has no new JavaScript or CSS. UI evidence complements backend checks for approval denial, roles, repeat refresh and concurrent writes; screenshots do not establish financial correctness themselves.

Final source 807712c3dd78db4bdbec15d6a264b5b72feec951 changes only the native field-access handling of explicit create defaults since the reviewed UI build. All UI/view/PO assets are unchanged. Server restarted on the final overlay and new-employee default screenshot repeated successfully; earlier language/layout evidence remains applicable to identical presentation files.
