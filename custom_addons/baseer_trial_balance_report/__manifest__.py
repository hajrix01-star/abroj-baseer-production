{
    "name": "Baseer Trial Balance",
    "summary": "Posted trial balance by account, with secured journal drill-down",
    "version": "19.0.1.0.0",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["baseer_general_ledger_report", "baseer_reports_menu"],
    "data": ["report/trial_balance_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_trial_balance_report/static/src/trial_balance.js",
            "baseer_trial_balance_report/static/src/trial_balance.xml",
            "baseer_trial_balance_report/static/src/trial_balance.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_trial_balance_report/static/tests/trial_balance.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
