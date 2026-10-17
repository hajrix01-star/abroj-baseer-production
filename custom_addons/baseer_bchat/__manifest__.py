{
    'name': 'BChat',
    'version': '19.0.0.4.15',
    'category': 'Productivity/Discuss',
    'summary': 'Private BChat messaging and company-scoped group administration',
    'license': 'LGPL-3',
    'depends': ['mail', 'project'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/media_cleanup_cron.xml',
        'data/push_cron.xml',
        'views/bchat_admin_views.xml',
        'views/res_users_bchat_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
