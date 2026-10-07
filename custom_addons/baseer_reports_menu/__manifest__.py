{
    "name": "Baseer Reports Menu",
    "summary": "Unified Invoicing report page for Baseer-owned financial reports",
    "version": "19.0.1.0.5",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account"],
    "data": ["views/reports_menu.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_reports_menu/static/src/report_selector.js",
            "baseer_reports_menu/static/src/report_selector.xml",
            "baseer_reports_menu/static/src/report_hub.js",
            "baseer_reports_menu/static/src/report_hub.xml",
            "baseer_reports_menu/static/src/report_shell.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_reports_menu/static/tests/report_hub.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
