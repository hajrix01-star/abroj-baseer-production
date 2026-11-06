{
    'name': 'Baseer Financial Dashboard',
    'summary': 'Read-only financial dashboard with profit and loss and sales payments tabs',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': [
        'spreadsheet_dashboard',
        'baseer_sales_dashboard',
        'baseer_profit_loss_report',
        'baseer_operations_report',
    ],
    'data': ['data/dashboard.xml'],
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'baseer_financial_dashboard/static/src/**/*.js',
            'baseer_financial_dashboard/static/src/**/*.xml',
        ],
        'web.assets_backend': [
            'baseer_financial_dashboard/static/src/**/*.scss',
        ],
        'web.assets_unit_tests': [
            'baseer_financial_dashboard/static/tests/financial_dashboard.test.js',
        ],
    },
    'installable': True,
}
