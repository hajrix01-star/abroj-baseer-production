# Dashboard 2 accounting settings

Settings are per company and editable by accounting managers. Live identifiers are only applied when the record exists and belongs to the expected company; skipped records are logged. Existing mappings are preserved. Review settings in each database.

Sales use posted entries for each company and accounting date. In automatic mode, posted revenue summary entries (including summary POS configuration sessions) are added to payments of qualifying real POS orders in sessions with a posted closing move. Payments are attributed to the closing move date; orders in sessions without a posted closing never add money. Receipt-only entries are excluded. A day with both posted sources is flagged as informational: overlap cannot be detected. Customer counts, average ticket and hourly distribution use qualifying real POS orders on their order dates, independently of the money source or session closing. Orders with absolute totals at or below the configured minimum (1.5 SAR by default) are excluded from both POS payments and order metrics. Summary POS configurations can be selected in settings; names containing «ملخص المبيعات», «Sales summaries» or «ملخصات» are also detected, and their orders are excluded from customer metrics.

Settings allow non-overlapping date-range source overrides: auto merges both posted sources, summary includes only summary entries, and pos includes only posted real POS sessions. The cutover date is retained as a legacy reference only and does not select sales sources. Arz (company 1) retains the documented 2026-10-03 default when empty.

| Company | Documented liquidity accounts | Channel accounts | Cutover |
| --- | --- | --- | --- |
| Arz (1) | custody 3426; company accounts 101090, 105090 | company codes 105090, 101090, 102110–102112 | 2026-10-03 (if empty) |
| Shami (2) | custody 3427; Al-Ahli 3420, 3421, 3986; company accounts 101090, 105090 | 3420 Keeta, 3421 HungerStation, 3986 Jahez by ID; company codes 105090, 101090, 102110–102112 | unset |
| Doha (3) | company accounts 101090, 105090 | company codes 105090, 101090, 102110–102112 | unset |

All asset_cash accounts are liquidity automatically; additional accounts and their source kind/label are editable. Outflow is credit on liquidity accounts regardless of journal, excluding pure liquidity transfers and moves containing 999999. The older journal settings do not determine outflows. The documented POS payment method IDs remain seeded by company. The account codes 101007–101009 are never seeded as application channels. Unreceived applications are the lesser of mapped application account balances at period end and application gross sales; reset moves are excluded and a reset on the end date makes the value unavailable. Unpaid bills use posted bill payable balances less partial reconciliations through the period end.
