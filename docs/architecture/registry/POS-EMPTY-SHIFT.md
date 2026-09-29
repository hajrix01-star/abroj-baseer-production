# POS empty shift selection — 2026-09-09

Controlled local entry-flow change; deployment follows the existing frozen-candidate boundary. Parent accepted commit: 2b555de2dc26349098dd1ab741d26e0eb260c334. Owner: build lead; independent acceptance: schedule_edit_review.

The transient sales entry starts without a shift. Its canonical day_schedule may be empty while entering data; saving sales explicitly requires a selection. DAY OFF continues without a sales shift. Persisted summaries, payment methods, amounts, approvals, posting and company isolation retain their existing authority and validation. Cards and totals appear after selection. Remove the two requested explanatory text nodes from the view/widget.

Checks: fresh default and flags, first selection for all options, saving without selection blocked, DAY OFF unaffected, existing selected entries preserved, Arabic browser entry and hidden text; protected MAIN business rows unchanged across upgrade. No core edits or new dependency. Rollback uses the coherent pre-upgrade database/filestore/source snapshot.

Verified candidate d7c1d675f2176c1e125ca50c5522f917ad51d153, MAIN deployed.58 QA checks passed; native Arabic UI verified QA and MAIN;250 protected tables unchanged. Evidence: docs/releases/2026-09-09-pos-empty-shift.
