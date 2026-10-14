{
    "name": "Baseer Aged Receivables",
    "summary": "Posted customer receivables at a historical cutoff",
    "version": "19.0.1.0.0",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account", "baseer_reports_menu"],
    "data": ["report/aged_receivable_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_aged_receivable_report/static/src/aged_receivable.js",
            "baseer_aged_receivable_report/static/src/aged_receivable.xml",
            "baseer_aged_receivable_report/static/src/aged_receivable.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_aged_receivable_report/static/tests/aged_receivable.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
