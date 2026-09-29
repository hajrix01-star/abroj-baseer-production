# BASEER-CASH-2 — compact report presentation

2026-09-07. User asked to remove repeated items and apply the supplied clean mint/teal report reference. G0–G3 approved independently by gate_review. Target QA only; existing limits, Decimal authority, company ACLs and provenance unchanged. Existing architecture map in CASH-CATEGORIES.md remains valid. No library, schema or vendor edit.

| Before | After | Why |
| --- | --- | --- |
| Treasury journal then identical cash account | One journal row with native sources | Avoid duplicate descriptions and amounts |
| Receipt/payment totals repeated below sections | Section totals once | Keep hierarchy readable |
| Two equivalent net rows when inclusive | One highlighted net row | Make the result unambiguous |
| Opening/closing/check and long notes in main scan | Native collapsed reconciliation section, expanded in exports | Preserve evidence without crowding the report |
| Gray rules, wide layout and mixed typography | Centered white report, mint groups, teal/coral amounts, Plex Arabic | Apply visual hierarchy from reference |

G1: one local tester, monthly report, existing366day/10k/depth6 bounds. No new queries or capacity claims. G2: one canonical payload for viewer/PDF/XLSX; totals unchanged; presentation removal and grouping only, source maps remain secured. G3 direct path: reuse EH viewer fold/drilldown/exports and existing local fonts. No percent/month comparison calculations inferred from reference. G4: typography and scoped mint tokens, logical RTL/LTR indentation, native keyboard actions, preserve28px virtual row height; mobile text reveal and no horizontal scrolling. No decorative motion.

Ownership: parent UI/XML/SCSS and integration; cash_handler backend presentation; report_contract new compact QA tests; gate_review independent acceptance. Acceptance: all monetary totals unchanged in both tax modes, removed duplication, details accessible, native links and back state preserved, Arabic/English desktop/mobile, matching PDF/XLSX and original reports unaffected.
