{
    "name": "Baseer Aged Payables",
    "summary": "Posted supplier payables at a historical cutoff",
    "version": "19.0.1.0.0",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account", "baseer_reports_menu"],
    "data": ["report/aged_payable_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_aged_payable_report/static/src/aged_payable.js",
            "baseer_aged_payable_report/static/src/aged_payable.xml",
            "baseer_aged_payable_report/static/src/aged_payable.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_aged_payable_report/static/tests/aged_payable.test.js",
        ],
    },
    "application": False,
    "installable": True,
}

