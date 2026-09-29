# SD1 browser acceptance — 2026-09-09

Candidate: `2d2ff102d11a53fc2fca1b8c1707fc81c77537ab`.
QA: `baseer_reports_qa_20260907`, native Dashboards at localhost:18070.

Verified in the actual browser:

- Native Sales dashboard opens, and returning to Sales summaries works.
- Arabic and English labels work. Numeric values, signs, dates and percentages retain Western digits and LTR ordering within RTL layout.
- Last year selects 2025 versus 2024, displays monthly charts with 12 points. QA-only fixtures produce sales 58,650.00 (+25.00%), customers 318 (-43.01%), average daily sales 4,887.50 (+25.00%), average daily customers 26.50 (-43.01%), average bill 184.43 (+119.32%). Values match independent fixture evidence.
- Green upward and red downward arrows render beside the percentages; previous values are visible. No-data comparison is unavailable rather than infinity or a fabricated decline.
- This month uses daily points. Custom dates chosen in the native calendar, 2026-09-01 through 2026-09-30, apply as the same range and show daily granularity. The corrected date input remains 2026-09-30 after calendar selection.
- Switching active company from QA ARZ to QA المعلم الشامي reloads company-specific values and an empty state, without retaining the former company's figures.
- Native Arabic Sales board still shows its original Quotations/Orders/Revenue figures and spreadsheet sections.
- At 390px, two cards per row and a full-width final card render without horizontal overflow; measured number widths fit their boxes (98/37/86/55/68 px) and direction is LTR. Long dates wrap within the filter area.
- At 1280px, all five cards and both line charts are visible. Monthly partial coverage uses triangle points and the explanatory legend. Empty periods and absent customer counts are explained separately.

Images: `qa-mobile-ar.jpg`, `qa-desktop-en.jpg`; early Arabic screenshots also retained. The final source differs from the mobile screenshot only by the native date-input remount key, verified subsequently in the browser. Tests: backend 84/84; UI component 17/17. Native calendar selection was exercised directly; automation fill alone did not emit the native change event and is not counted as a typing test.

This verifies local functional behavior, not a concurrency certification. QA fixture records are isolated and must be removed before closing QA; none are deployed to MAIN.
