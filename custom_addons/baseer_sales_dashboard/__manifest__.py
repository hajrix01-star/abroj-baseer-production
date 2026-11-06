{
    'name': 'Baseer Sales Summary Dashboard',
    'version': '19.0.1.8.1',
    'category': 'Sales/Point of Sale',
    'license': 'LGPL-3',
    'depends': ['baseer_pos_summary', 'spreadsheet_dashboard', 'pos_sale'],
    'data': ['security/noorix_evidence_security.xml', 'security/ir.model.access.csv',
             'data/dashboard.xml', 'data/dashboard_navigation.xml',
             'views/noorix_evidence_views.xml'],
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'baseer_sales_dashboard/static/src/**/*.js',
            'baseer_sales_dashboard/static/src/**/*.xml',
        ],
        'web.assets_backend': ['baseer_sales_dashboard/static/src/**/*.scss'],
    },
    'installable': True,
}
