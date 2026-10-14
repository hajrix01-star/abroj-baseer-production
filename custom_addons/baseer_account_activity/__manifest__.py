{
    "name": "Baseer Account Activity",
    "summary": "Posted journal activity for one account with opening and running balances",
    "version": "19.0.1.0.3",
    "author": "Baseer",
    "license": "LGPL-3",
    "category": "Accounting/Reporting",
    "depends": ["account", "baseer_reports_menu"],
    "data": ["views/account_activity_views.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_account_activity/static/src/account_activity.js",
            "baseer_account_activity/static/src/account_activity.xml",
            "baseer_account_activity/static/src/account_activity.scss",
        ],
        "web.assets_unit_tests": [
            "baseer_account_activity/static/tests/account_activity.test.js",
        ],
    },
    "application": False,
    "installable": True,
}
