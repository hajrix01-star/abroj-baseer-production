{
    'name': 'Baseer Accounting Dashboard Plus', 'version': '19.0.1.0.2',
    'author': 'Baseer', 'license': 'LGPL-3',
    'depends': ['account', 'baseer_report_engine'],
    'data': ['views/journal_dashboard.xml', 'views/account_move_line_search.xml'],
    'assets': {'web.assets_backend': [
        'baseer_account_dashboard_plus/static/src/summary.js',
        'baseer_account_dashboard_plus/static/src/summary.xml',
        'baseer_account_dashboard_plus/static/src/summary.scss',
    ]}, 'installable': True,
}
