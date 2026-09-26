{
    'name': 'Baseer POS Suite',
    'summary': 'Install and configure Baseer POS printing and item controls',
    'version': '19.0.1.3.0',
    'category': 'Baseer/POS',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': [
        'baseer_pos_print_bridge',
        'baseer_pos_receipt_layout',
        'baseer_pos_product_substitution',
    ],
    'data': [
        'views/suite_views.xml',
    ],
    'application': True,
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
}
