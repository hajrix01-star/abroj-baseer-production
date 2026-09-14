{
    'name': 'Baseer Sales Heat Calendar',
    'version': '19.0.1.0.4',
    'author': 'Baseer',
    'category': 'Sales/Point of Sale',
    'license': 'LGPL-3',
    'depends': ['baseer_sales_dashboard'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/dashboard.xml',
        'data/occasion_views.xml',
    ],
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'baseer_sales_heat_calendar/static/src/**/*.js',
            'baseer_sales_heat_calendar/static/src/**/*.xml',
        ],
        'web.assets_backend': [
            'baseer_sales_heat_calendar/static/src/**/*.scss',
        ],
    },
    'installable': True,
}
