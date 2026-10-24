{
    "name": "Baseer Legion Theme Compatibility",
    "summary": "Baseer purple identity, readable navigation and installable app icons",
    "version": "19.0.1.1.1",
    "author": "Baseer",
    "license": "AGPL-3",
    "depends": ["legion_enterprise_theme"],
    "data": ["views/webclient_templates.xml"],
    "assets": {
        "web.assets_backend": [
            ("after", "/legion_enterprise_theme/static/src/scss/primary_variables_custom.scss",
             "baseer_legion_compat/static/src/brand_variables.scss"),
            "baseer_legion_compat/static/src/navbar.scss",
            "baseer_legion_compat/static/src/brand.scss",
        ],
    },
    "installable": True,
    "application": False,
}
