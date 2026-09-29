# WS4A native schedule-list follow-up

Parent WS4 a6401283d15b09abb74b6ebb4ed560097de5242d; current candidate2b555de2dc26349098dd1ab741d26e0eb260c334. G4/G7 reopened and independently approved default-search-filter approach. Only XML/PO/manifest changed; backend byte-identical to parent with61functional72concurrency107regression checks.

Native resource.action_resource_calendar_form (MAIN99/QA95) now defaults to Current schedules filter, separated from other filter groups. Original company/shared domain retained. One current revision visible by default; deliberate filter removal shows historical revisions, direct historical links remain functional. Filter inherited view removed with addon; native action retains only harmless default context key, no missing-field domain.

Actual Arabic native UI: one revised fixture row with11:00/55:00; removing filter shows two; previous directform retains10:30/52:30 with latestlink. Source hashes inws4a-ui.json; fixture cleanup independently query-verified. Scope of core employee date/history/payroll rules remains WS4 review.
