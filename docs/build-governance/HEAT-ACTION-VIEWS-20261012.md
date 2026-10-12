# Heat detail action contract correction

Owner reported action_service _preprocessAction undefined.map after calendar QA repair. Native Odoo19 action_service.js line442 requires action.views.map on inline act_window. Heat money/detail JSON tests did not exercise this browser preprocessing contract; both POS and zero-summary actions lack views.
Narrow repair: explicit list/form views for both action paths, version1.1.2; no domain, amounts, dates, access, source data changes. Existing _action_records tests assert mandatory views; existing heat CI covers both paths. Independent scoped review before release; QA only. Authenticated click not claimed unless executed.
