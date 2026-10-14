{
    'name': 'Baseer Saudi VAT Report',
    'summary': 'Monthly and quarterly Saudi VAT grid from posted accounting entries',
    'version': '19.0.1.0.9',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting/Reporting',
    'depends': ['account', 'l10n_sa', 'baseer_reports_menu'],
    'data': [
        'security/ir.model.access.csv',
        'security/vat_xlsx_export_rule.xml',
        'views/tax_report_views.xml',
        'report/tax_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_tax_report/static/src/js/report_registration.js',
            'baseer_tax_report/static/src/js/saudi_vat_report.js',
            'baseer_tax_report/static/src/js/tax_preview_field.js',
            'baseer_tax_report/static/src/xml/tax_preview_field.xml',
            'baseer_tax_report/static/src/xml/saudi_vat_report.xml',
            'baseer_tax_report/static/src/scss/tax_report.scss',
            'baseer_tax_report/static/src/scss/saudi_vat_report.scss',
        ],
        'web.assets_unit_tests': [
            'baseer_tax_report/static/tests/saudi_vat_report.test.js',
        ],
    },
    'installable': True,
}
