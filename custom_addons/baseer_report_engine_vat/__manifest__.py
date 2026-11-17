{
    'name': 'Baseer VAT Report',
    'version': '19.0.1.0.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['baseer_report_engine', 'l10n_sa'],
    'external_dependencies': {'python': ['openpyxl']},
    'data': ['data/report.xml', 'views/menu.xml'],
    'assets': {'web.assets_backend': ['baseer_report_engine_vat/static/src/vat.js', 'baseer_report_engine_vat/static/src/vat.xml']},
    'auto_install': False,
    'installable': True,
}
