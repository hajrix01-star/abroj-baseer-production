{
    'name': 'بصير SMS',
    'summary': 'Central bank-SMS evidence inbox and routing rules',
    'version': '19.0.1.8.9',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Tools',
    'depends': ['account', 'hr', 'baseer_procurement_requests'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/bank_sms_sender_data.xml',
        'views/webclient_lang_fix.xml',
        'views/bank_sms_views.xml',
        'views/bank_sms_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_bank_sms/static/src/js/bank_sms_dashboard.js',
            'baseer_bank_sms/static/src/xml/bank_sms_dashboard.xml',
            'baseer_bank_sms/static/src/scss/bank_sms.scss',
        ],
    },
    'application': True,
    'installable': True,
}
