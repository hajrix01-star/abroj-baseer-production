{
    'name': 'Baseer Saudi VAT Report',
    'summary': 'Monthly and quarterly Saudi VAT grid from posted accounting entries',
    'version': '19.0.1.0.3',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting/Reporting',
    'depends': ['account', 'l10n_sa'],
    'data': [
        'security/ir.model.access.csv',
        'views/tax_report_views.xml',
        'report/tax_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_tax_report/static/src/js/tax_preview_field.js',
            'baseer_tax_report/static/src/xml/tax_preview_field.xml',
            'baseer_tax_report/static/src/scss/tax_report.scss',
        ],
    },
    'installable': True,
}
