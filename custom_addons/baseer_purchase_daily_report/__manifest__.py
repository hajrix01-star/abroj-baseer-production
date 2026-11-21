{
    'name': 'Baseer Daily Purchase Report',
    'summary': 'Company-scoped daily vendor bill reporting',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Reporting',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['account', 'baseer_access_roles'],
    'data': ['views/report_action.xml'],
    'assets': {
        'web.assets_backend': [
            'baseer_purchase_daily_report/static/src/*.js',
            'baseer_purchase_daily_report/static/src/*.xml',
            'baseer_purchase_daily_report/static/src/*.scss',
        ],
    },
    'installable': True,
}
