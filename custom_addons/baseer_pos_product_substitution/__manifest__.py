{
    'name': 'Baseer POS Product Substitution',
    'summary': 'Controlled product edits and cancellation records',
    'version': '19.0.2.0.1',
    'category': 'Baseer/POS',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'baseer_pos_print_bridge'],
    'data': [
        'security/substitution_security.xml',
        'security/ir.model.access.csv',
        'views/product_views.xml',
        'views/pos_config_views.xml',
        'views/substitution_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_product_substitution/static/src/app/substitution.js',
            'baseer_pos_product_substitution/static/src/app/substitution.xml',
            'baseer_pos_product_substitution/static/src/app/substitution.scss',
        ],
    },
    'installable': True,
}
