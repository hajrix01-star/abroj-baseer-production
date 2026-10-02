{
    'name': 'Baseer POS Cancellation Follow-up',
    'summary': 'Documented cancellations, substitutions and review indicators in one report',
    'version': '19.0.1.2.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Baseer/POS',
    'depends': ['baseer_pos_suite'],
    'data': [
        'security/ir.model.access.csv',
        'security/report_security.xml',
        'views/report_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_pos_cancellation_report/static/src/report.js',
            'baseer_pos_cancellation_report/static/src/report.xml',
            'baseer_pos_cancellation_report/static/src/report.scss',
        ],
    },
    'application': False,
    'installable': True,
}
