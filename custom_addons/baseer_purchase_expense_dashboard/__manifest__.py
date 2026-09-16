{
    'name': 'Baseer Purchase and Expense Dashboard',
    'summary': 'Read-only supplier bill and expense reporting for Baseer',
    'version': '19.0.3.0.0',
    'category': 'Accounting',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'spreadsheet_dashboard',
        'baseer_sales_dashboard',
        'baseer_access_roles',
        'baseer_native_spend',
    ],
    'data': ['data/dashboard.xml'],
    'post_init_hook': 'post_init_hook',
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'baseer_purchase_expense_dashboard/static/src/**/*.js',
            'baseer_purchase_expense_dashboard/static/src/**/*.xml',
        ],
        'web.assets_backend': [
            'baseer_purchase_expense_dashboard/static/src/**/*.scss',
        ],
    },
    'installable': True,
}
