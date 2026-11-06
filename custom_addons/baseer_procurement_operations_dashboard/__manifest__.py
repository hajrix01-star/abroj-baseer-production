{
    'name': 'Baseer Procurement Operations Dashboard',
    'summary': 'Read-only procurement request workflow dashboard',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Purchase',
    'author': 'Baseer',
    'license': 'LGPL-3',
    # baseer_sales_dashboard owns the shared dashboard-kind/loader/date-filter
    # integration used by every custom native dashboard.
    'depends': [
        'baseer_procurement_requests',
        'spreadsheet_dashboard',
        'baseer_sales_dashboard',
    ],
    'data': ['data/dashboard.xml'],
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'baseer_procurement_operations_dashboard/static/src/**/*.js',
            'baseer_procurement_operations_dashboard/static/src/**/*.xml',
        ],
        'web.assets_backend': [
            'baseer_procurement_operations_dashboard/static/src/**/*.scss',
        ],
    },
    'installable': True,
}
