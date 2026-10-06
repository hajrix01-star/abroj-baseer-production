{
    "name": "Baseer Report Design Preview",
    "summary": "Isolated sample interface for reviewing financial report design",
    "version": "19.0.1.0.0",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["web", "account"],
    "data": ["views/preview_views.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_report_ui_preview/static/src/report_preview.js",
            "baseer_report_ui_preview/static/src/report_preview.xml",
            "baseer_report_ui_preview/static/src/report_preview.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_report_ui_preview/static/tests/report_preview.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
