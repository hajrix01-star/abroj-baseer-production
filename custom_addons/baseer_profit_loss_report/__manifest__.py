{
    "name": "Baseer Profit and Loss Report",
    "summary": "Posted profit and loss inside Baseer Reports",
    "version": "19.0.1.0.3",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account", "baseer_reports_menu"],
    "data": ["report/profit_loss_report.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_profit_loss_report/static/src/profit_loss.js",
            "baseer_profit_loss_report/static/src/profit_loss.xml",
            "baseer_profit_loss_report/static/src/profit_loss.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_profit_loss_report/static/tests/profit_loss.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
