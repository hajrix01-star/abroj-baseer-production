{
    'name': 'Baseer Dashboard 2',
    'version': '19.0.2.2.1',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting',
    'depends': ['web', 'account', 'point_of_sale', 'baseer_reports_menu', 'baseer_profit_loss_report'],
    'data': [
        'security/ir.model.access.csv', 'security/rules.xml',
        'data/config_data.xml', 'data/category_data.xml', 'data/channel_data.xml', 'data/event_data.xml',
        'views/dashboard_views.xml',
    ],
    'assets': {'web.assets_backend': [
        'baseer_dashboard2/static/src/js/tooltip.js',
        'baseer_dashboard2/static/src/js/main.js',
        'baseer_dashboard2/static/src/xml/main.xml',
        'baseer_dashboard2/static/src/scss/theme.scss',
        'baseer_dashboard2/static/src/scss/main.scss',
    ], 'web.assets_unit_tests': ['baseer_dashboard2/static/tests/**/*']},
    'post_init_hook': 'post_init_hook',
    'application': True,
}
