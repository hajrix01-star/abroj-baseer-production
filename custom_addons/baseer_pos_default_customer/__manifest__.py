{
    'name': 'Baseer POS Default Customer',
    'version': '19.0.1.0.0',
    'summary': 'Select a configured visible customer on new POS orders',
    'category': 'Point of Sale',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'data': ['views/pos_config_views.xml'],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_default_customer/static/src/app/default_customer.js',
        ],
    },
    'installable': True,
}
