{
    'name': 'Baseer POS ZATCA B2C',
    'summary': 'Optional anonymous-consumer path for Saudi POS simplified invoices',
    'version': '19.0.1.0.0',
    'category': 'Point of Sale',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['l10n_sa_edi_pos'],
    'data': [
        'views/pos_config_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_zatca_b2c/static/src/app/anonymous_b2c.js',
        ],
    },
    'installable': True,
}
