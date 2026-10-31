{
    'name': 'Abroj Project Dashboard',
    'version': '19.0.1.8.5',
    'license': 'LGPL-3',
    'depends': ['project', 'analytic', 'account', 'purchase', 'sale_management', 'abroj_contracting'],
    'data': ['security/engineer_group.xml', 'security/ir.model.access.csv', 'security/rules.xml', 'views/dashboard.xml', 'views/notification_settings.xml', 'views/daily_report.xml', 'data/daily_report.xml', 'data/promissory.xml', 'data/notifications.xml', 'views/login.xml', 'data/login_session.xml', 'report/promissory.xml'],
    'assets': {'web.assets_backend': [
        'abroj_project_dashboard/static/src/dashboard.js',
        'abroj_project_dashboard/static/src/dashboard.xml',
        'abroj_project_dashboard/static/src/dashboard.scss',
        'abroj_project_dashboard/static/src/gallery.js',
        'abroj_project_dashboard/static/src/gallery.xml',
        'abroj_project_dashboard/static/src/gallery.scss',
        'abroj_project_dashboard/static/src/app_switch.js',
    ],
    'web.assets_frontend': [
        'abroj_project_dashboard/static/src/login/login.scss',
        'abroj_project_dashboard/static/src/login/login.js',
    ]},
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
