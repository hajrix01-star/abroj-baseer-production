{
    'name': 'Baseer Employee Follow-up',
    'version': '19.0.1.0.2',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['web', 'hr', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/security_upgrade.xml',
        'data/default_task_templates.xml',
        'data/default_evaluation_templates.xml',
        'views/followup_views.xml',
        'views/evaluation_views.xml',
        'views/employee_followup_views.xml',
        'views/res_users_views.xml',
        'views/employee_app_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_employee_followup/static/src/backend_dashboard.js',
            'baseer_employee_followup/static/src/backend_dashboard.xml',
            'baseer_employee_followup/static/src/backend_dashboard.scss',
        ],
    },
    'application': True,
}
