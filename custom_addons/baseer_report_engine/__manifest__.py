{
    'name': 'Baseer Report Engine',
    'summary': 'Declarative financial reports on journal items',
    'version': '19.0.1.1.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting/Reporting',
    'depends': ['account', 'analytic', 'web'],
    'external_dependencies': {'python': ['xlsxwriter']},
    'data': [
        'security/ir.model.access.csv',
        'data/balance_sheet.xml',
        'data/profit_and_loss.xml',
        'views/report_menus.xml',
        'report/report_pdf.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_report_engine/static/src/report_engine.scss',
            'baseer_report_engine/static/src/report_engine.xml',
            'baseer_report_engine/static/src/report_engine.js',
        ],
    },
    'application': False,
    'installable': True,
}
