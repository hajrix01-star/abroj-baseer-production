# SD2 browser acceptance — 2026-09-09

Final QA module19.0.1.1.0. Existing read-only demo.sales user157, company6. Actual native DateFilter widget in native ControlPanel slot, inherited local formatting only. No custom bodyfilter. Browser:1280desktop and390mobile.

- Native month changes every section; Augustdaily chart31days. Shift metric select updates bars between sales/customers/bill values without replacing server values.
- Custom range selected with actual calendar date cells (not programmatic value injection): March1–August31,2026. Both inputs stay Western01/03/2026 and31/08/2026 after final scoped rekey. Sixmonthly bars; exact five established KPIs935779.00/15282/5085.76/83.05/61.23 retained after demo enrichment.
- All time:2025-08-29–2026-09-09, beyond366days, no fabricated previous comparison. Year2026 returnsfullJan–Dec monthly; native nextarrowYear2027 shows labeled faded illustration and five dashes, zero canvases/no invented values.
- Payment source click HungerStation succeeds after explicit act_window views fix; opens original allocation list341rows for same period, showing summary/date/method/category/amount. No create button; source evidence screenshot.
- Phone390:body scrollWidth390, dashboardclient/scroll360, both tablesclient/scroll318; no horizontaloverflow. Long bilingual names wrap. Charts stack below tables.
- English labels confirmed; a fresh page uses native LTR (qa-en-ltr.png). Arabic screenshots RTL. An existing tab after language switching retained prior native CSSdirection until fresh page; no global language addon edits made in this release.
- Initial stale res.users.settings toast disappeared after fresh QApage; read-only checks confirm demo user's ordinary internal/POS rights, ownsettings exists. No permission changes.
- QA demo is explicitly synthetic:683summaries3415allocations preserve all368originaldaily totals and nativeledger/POS fingerprints. MAIN has no preview transactions.

Evidence images:qa-native-filter-ar.png,qa-six-months-ar.png,qa-month-ar.png,qa-shifts-ar.png,qa-mobile-shifts-ar.png,qa-mobile-payments-ar.png,qa-payment-source-ar.png,qa-alltime-en.png,qa-empty-en.png,qa-en-ltr.png. Earlier screenshots document UI before final date/link-only fix; finalnativefilter/source images verify fixes. Final component34andbackend75hashes separately bound to candidate at review.
