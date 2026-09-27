{
    "name": "Baseer Web Navigation",
    "summary": "Native application icons and a quick interface language selector",
    "version": "19.0.1.2.1",
    "author": "Baseer",
    "license": "LGPL-3",
    "depends": ["web"],
    "data": ["views/res_company_views.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_web_navigation/static/src/display_names.js",
            "baseer_web_navigation/static/src/display_names.xml",
            "baseer_web_navigation/static/src/apps_menu.xml",
            "baseer_web_navigation/static/src/apps_menu.scss",
            "baseer_web_navigation/static/src/language_menu.js",
            "baseer_web_navigation/static/src/language_menu.xml",
        ],
    },
    "installable": True,
    "application": False,
}
