{
    "name": "Baseer Balance Sheet",
    "summary": "Posted balance sheet with secured source drill-down",
    "version": "19.0.1.0.0",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["baseer_general_ledger_report", "baseer_reports_menu"],
    "data": ["report/balance_sheet_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_balance_sheet_report/static/src/balance_sheet.js",
            "baseer_balance_sheet_report/static/src/balance_sheet.xml",
            "baseer_balance_sheet_report/static/src/balance_sheet.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_balance_sheet_report/static/tests/balance_sheet.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
