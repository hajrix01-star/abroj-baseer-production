{
    "name": "Baseer Vendor Bill Document References",
    "version": "19.0.1.0.1",
    "license": "LGPL-3",
    "depends": ["account", "dms"],
    "data": ["security/bill_rules.xml", "views/company.xml", "views/file_preview.xml"],
    "assets": {
        "web.assets_backend": [
            "baseer_dms_bill_link/static/src/bill_preview.js",
            "baseer_dms_bill_link/static/src/bill_preview.xml",
            "baseer_dms_bill_link/static/src/bill_preview.scss",
        ],
    },
    "installable": True,
}
