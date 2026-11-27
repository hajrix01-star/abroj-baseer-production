{
    'name': 'Baseer Daily Purchase Report',
    'summary': 'Company-scoped daily vendor bill reporting',
    'version': '19.0.1.2.0',
    'category': 'Accounting/Reporting',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['account', 'baseer_access_roles', 'baseer_procurement_requests'],
    'data': ['views/report_action.xml'],
    'assets': {
        'web.assets_backend': [
            'baseer_purchase_daily_report/static/src/date_range.js',
            'baseer_purchase_daily_report/static/src/purchase_daily_report.js',
            'baseer_purchase_daily_report/static/src/purchase_daily_report.xml',
            'baseer_purchase_daily_report/static/src/purchase_daily_report.scss',
        ],
    },
    'installable': True,
}
