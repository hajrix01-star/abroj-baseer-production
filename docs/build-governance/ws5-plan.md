# WS5 unified work-time picker

G0–G3 review input, 2026-09-09. Owner root; independent gate/release reviewer schedule_edit_review. Parent MAIN d7c1d675f2176c1e125ca50c5522f917ad51d153. User explicitly retains the existing modal after narrowing the earlier full-page request.

G0: replace two inline selects with one HH:MM clock trigger and a single combined hour/minute popover. Keep all three entry journeys (new template, edit template, employee setup) modal. Responsive period days wrap without overlapping From/To. Acceptance: 24-hour Western digits, every minute supported, 24:00 endpoint preserved, overnight duration unchanged, confirm once/cancel without writes, keyboard and touch, Arabic/English, narrow desktop and390px mobile.

G1: bounded local picker (24hours/60minutes) with one existing record.update on confirmation. No extra server query/worker/data growth. Existing WS4 candidate200/fanout50 and native server guards remain. No new load claim or repeat concurrency suite for unchanged backend.

G2: char HH:MM raw input stays existing contract. Integer-minute compiler, overlap and overnight validation, native calendars/hr.version, payroll calculations and dated edit atomicity untouched. UI selection is only raw input, never computes payroll/durations. No schema migration or core edits.

G3: use existing Odoo19 Owl + usePopover and Bootstrap styling; native source popover_hook.js inspected. No new library. Browser time input rejected as sole control because locale can choose12h and HTMLtime excludes24:00. One feature-owned reusable widget across all schedule views, no third-party calendar. Existing global date/report components unchanged.

G4 draft: one compact trigger HH:MM + clock, popover hour/minute selection and Apply/Cancel; native overlay anchoring outside list avoids clipping. Day tags wrap; explicit widths for From/To and flexible days. Mobile existing kanban period form retained. No animation needed. New strings bilingual from source. Review follows emil-design-eng.

Checks planned: real native UI at desktop/narrow/modal/mobile, arbitrary-minute and midnight choices, cancellation/no accidental save, existing duration regression, isolated frozen release with backup and protected rows. All business writes restricted to QA fixtures/rollback; no real schedule modification during MAIN verification.

Live log: inspected module widget/views/styles and native popover hook. No application edits yet. Await independent G0–G3 before implementation. Release evidence docs/releases/2026-09-09-unified-time-picker.

## Independent G0–G3 decision — 2026-09-09

Reviewer `schedule_edit_review`, independent of the implementation owner, read this plan and the existing `time_field.js`, `time_field.xml` and `schedule.scss`. **G0, G1, G2 and G3 approved** before application edits.

- G0: the latest user instruction retaining the modal is explicit; unified picker and nonoverlapping wrapped day tags are bounded acceptance criteria across the three existing journeys.
- G1: local 24-hour/60-minute selection is bounded, with one existing record update on confirmation and no new server query, data growth or concurrency contract. Existing backend capacity evidence remains applicable; no new capacity certification is implied.
- G2: HH:MM remains raw input and the backend remains the sole duration/overlap/overnight/payroll authority. No new schema, numeric authority, calendar mutation or employee-history behavior is introduced.
- G3: native Odoo19/Owl/usePopover and existing styling are the direct reuse path; no dependency, global component change or browser-localized time format is required. One feature-owned widget serves all schedule forms.

G4 implementation verification must demonstrate locally staged selection, Apply exactly once while update is pending, Cancel/Escape/outside-close without record mutation, focus returning to the trigger, explicit `type="button"` on popup controls, arbitrary minutes, and 24:00 exclusively for permitted endpoints. Overlay anchoring must stay within the viewport above the modal/editable list in RTL and on mobile. Tag wrapping must not trade overlap for clipped times or horizontal scrolling. These are acceptance checks within the approved design, not new scope or a request for further user permission.

Review operation: read-only inspection and this append only; reviewer changed no application file. Later UI/code/artifact evidence is required for G4–G8 and release approval. Reopen the relevant gate if backend, dependency, modal choice or persistence semantics change.

Implementation started after independent G0–G3 approval. Backend worker owns only the feature widget JS/XML/SCSS; root owns version/translation/runtime/UI proof; test worker owns isolated component checks. Existing action target remains new. Prepared ws5_checks.py for native HH:MM/overnight/end-of-day/modal regression and ws5_release.py on accepted POS parent. No MAIN runtime or business data changed.

Final implementation log: replaced widget; native Escape in nested modal did not close reliably during actual UI test, fixed explicit panel cancellation and confirmed no-write/focus on390px. User requested smaller picker during QA; reduced272x372 to240x276, retaining44px targets.23 component and8 native checks passed; actual Arabic/English UI, customday wrapping, QA template save+cleanup documented. Frozen96dd7960 accepted by independent PREDEPLOY; deployed with coherent649attachment backup and250protected-table equality. MAIN1280px native modal/picker/cancel verified without saving business records; dailybackuphelper/pointer and registry updated. Final independent closure pending.
