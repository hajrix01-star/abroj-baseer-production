{
    "name": "Baseer Reports Menu",
    "summary": "Top-level navigation for Baseer-owned financial reports",
    "version": "19.0.1.0.2",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account"],
    "data": ["views/reports_menu.xml"],
    "assets": {
        "web.assets_backend": ["baseer_reports_menu/static/src/report_shell.scss"],
    },
    "application": False,
    "installable": True,
}
