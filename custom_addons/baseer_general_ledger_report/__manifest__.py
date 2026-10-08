{
    "name": "Baseer General Ledger",
    "summary": "Posted all-account general ledger inside Baseer Reports",
    "version": "19.0.1.0.1",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account", "baseer_reports_menu"],
    "data": ["report/general_ledger_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_general_ledger_report/static/src/general_ledger.js",
            "baseer_general_ledger_report/static/src/general_ledger.xml",
            "baseer_general_ledger_report/static/src/general_ledger.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_general_ledger_report/static/tests/general_ledger.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
