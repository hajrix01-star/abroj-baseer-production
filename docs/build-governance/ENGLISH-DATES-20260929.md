# ENGLISH-DATES-20260929 — English dates with an Arabic Odoo interface

Architecture impact: `CONTROLLED` shared UI component. Registry baseline `docs/architecture/registry/INDEX.md`; `lastVerifiedCommit=f7a00748389346f86c984d9056286548223201b1`; owner Baseer web customization, backup Odoo integration maintainer. Affects the shared web localization service and consumers of Luxon-backed date inputs, pickers, and list/form fields. Does not change ORM fields, stored dates, APIs, permissions, monetary values, or report templates. Risk is a locale initialization race or third-party widget bypassing Odoo's date service; acceptance checks exercise both standard and custom-module screens.

## G0 — Scope and acceptance

- The Arabic Odoo interface currently renders date inputs and picker headings with Arabic month names and Arabic-Indic digits. The requested result is English month/day names and Latin digits for dates across Odoo screens and installed modules, without switching the UI translation language.
- Scope: the shared Odoo web date/datetime rendering and picker used by modules, plus the known Baseer cash-category report month selector which directly invokes `Intl.DateTimeFormat` and bypasses that shared path. Preserve each language's date order, timezone, Arabic interface labels, accounting data, and existing stored dates. English-language sessions already satisfy the requirement and should be unchanged.
- The screenshot and acceptance target are the interactive web client. Report-specific QWeb formatting and dates embedded in free text are excluded pending a separate report-path audit; this is an explicit interpretation of “all modules,” not a claim that PDF dates are covered. Disclose this boundary to the user.
- Also out of scope: monetary number formatting, language records, and a production rollout.
- Acceptance: an Arabic session displays a date and date-picker month/weekdays in English with Latin digits; date entry parses and saves the same calendar day; a second module uses the same behavior; Arabic translated interface text remains Arabic; temporal relative-time/duration text rendered by Luxon is intentionally English too; no model or database schema changes.

## G1 — Capacity and lifecycle

- The override runs once when the existing localization service starts per browser session. No RPC, scheduled job, persistent data, or new network service is introduced. Workload is constant per session; no throughput assumption is needed.
- Lifecycle: Odoo initializes translations/localization, then this addon sets Luxon's locale and numbering system for Arabic sessions. Existing Odoo formatting/parsing and timezone behavior remain the single path.

## G2 — Ownership and source of truth

- Odoo `res.lang` and localization service remain the source of date order, translations, week start, and timezone. Luxon owns date names and numerals in the browser. Setting Luxon's global locale also changes Luxon-humanized durations and relative-time labels (e.g. mail notifications, remaining-days fields). This is the explicit presentation policy for English temporal values in the Arabic interface, while static translated UI text stays Arabic. Source scan of QA Odoo 19 located `toHuman` in `mail/notification_message.js` and `web/dates.js`, and `toRelative` in `mail/relative_time.js`, `web/remaining_days_field.js`, and website/project widgets; no custom-addon direct consumers were found. QA regression must inspect a relative-time or remaining-days example and verify it is English, not broken or mixed-script. The new addon owns the locale/numbering override only; it does not alter Odoo's translation catalog.
- Do not set a user's Odoo language to English or alter company settings. Do not modify Odoo core source. A module not using Odoo's shared date components needs separate review.

## G3 — Direct route and safety

- Add one small `web`-dependent addon to the official Git branch. Replace the localization service registry entry with a wrapper around the original `start`; after the original initialization, set Luxon to `en-GB` and `latn` only for Arabic user locales. Change the one installed Baseer month selector that bypasses Luxon to use `en-GB`. No external package or parallel date state.
- Test the central formatter/parser and picker on QA, then verify the Arabic UI in at least two modules. Back out by uninstalling the addon or reverting its source and upgrading QA. Production is out of scope.

## Gate ledger

| Gate | State | Evidence |
| --- | --- | --- |
| G0 | GO | User screenshot, QA `ar_001` locale inspection, and explicit interactive-web/report boundary |
| G1 | GO | Odoo 19 localization service source; one initialization per session |
| G2 | GO | Odoo 19 `dates.js`, date-picker, and temporal-duration consumer audit |
| G3 | GO | Odoo 19 registry `{force: true}` support; independent gatekeeper review before code |

Independent review and build/test outcome are recorded after their respective checks.

## QA evidence and open acceptance

- Candidate source `76b29f397b5251ecdde580da364cf07c92c469d5` is in PR #28; Source integrity CI passed. `node --check` passed for both changed JavaScript files; an `Intl.DateTimeFormat` spot check returned `September 2026`.
- On QA database `baseer_live_qa_clean_20260928`, `baseer_english_dates` installed at `19.0.1.0.0`. The active files for it and the cash selector match the staged candidate. QA service restarted and `/web/login` returned HTTP 303. Backups before changes are `db-backup-english-dates-fad621bc.dump`, `db-backup-english-dates-76b29f39.dump`, and `.backup-cash-categories-76b29f39` under the QA checkout.
- The `baseer_cash_categories` upgrade command returned nonzero while loading an unrelated `baseer_pos_summary` onboarding view: missing `setup_tobacco_fee` on `baseer.company.onboarding`. The DB reports the cash module installed at `19.0.1.3.3`, but successful end-to-end upgrade cannot be claimed. Do not alter the unrelated onboarding model under this date change.
- The user's QA acceptance on 2026-09-29 confirms that the date display issue resolved and that entering a date, saving, and reopening retained the same day. This is user-reported evidence, not an agent screenshot; the agent's QA-tab security permission check still fails before reading the page. Cross-module visual display, the cash selector, and relative-time strings remain agent-unverified. Independent delivery review must reconsider the merge verdict with this new evidence. PDF/QWeb dates remain outside this candidate.
