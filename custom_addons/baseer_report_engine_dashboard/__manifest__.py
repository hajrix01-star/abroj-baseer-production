{
    'name': 'Baseer Accounting Dashboard',
    'version': '19.0.1.0.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['baseer_report_engine', 'account'],
    'data': ['views/dashboard.xml'],
    'assets': {'web.assets_backend': [
        'baseer_report_engine_dashboard/static/src/dashboard.js',
        'baseer_report_engine_dashboard/static/src/dashboard.xml',
        'baseer_report_engine_dashboard/static/src/dashboard.scss',
    ]},
    'installable': True,
}
