{
    "name": "Baseer Google Ads",
    "version": "19.0.4.0.1",
    "summary": "Read-only Google Ads reporting for Baseer",
    "category": "Baseer",
    "author": "Abroj",
    "license": "LGPL-3",
    "depends": ["base", "web", "baseer_core", "baseer_access_roles"],
    "data": [
        "security/groups.xml",
        "security/ir.model.access.csv",
        "security/rules.xml",
        "views/google_ads_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "baseer_google_ads/static/src/google_ads_dashboard.js",
            "baseer_google_ads/static/src/google_ads_dashboard.xml",
            "baseer_google_ads/static/src/google_ads_dashboard.scss",
        ],
    },
    "installable": True,
    "application": True,
}
