{
    'name': 'Baseer Gross Operations Source (Limited)',
    'summary': 'Read-only, explicitly incomplete VAT-inclusive operations source',
    'version': '19.0.1.0.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting/Reporting',
    'depends': ['baseer_profit_loss_report', 'baseer_pos_summary',
                'baseer_purchase_batch'],
    'data': ['report/operations_report.xml'],
    'assets': {
        'web.assets_backend': [
            'baseer_operations_report/static/src/operations.js',
            'baseer_operations_report/static/src/operations.xml',
            'baseer_operations_report/static/src/operations.scss',
        ],
        'web.assets_unit_tests': [
            'baseer_operations_report/static/tests/operations.test.js',
        ],
    },
    'application': False,
    'installable': True,
}
