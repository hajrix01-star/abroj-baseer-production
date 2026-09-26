{
    'name': 'Baseer POS Customer Identity',
    'version': '19.0.1.0.12',
    'summary': 'Saudi mobile identity, customer filters and duplicate prevention in Point of Sale',
    'category': 'Point of Sale',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'phone_validation', 'hr', 'baseer_access_roles'],
    'data': ['views/res_partner_views.xml'],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_customer_identity/static/src/app/partner_identity.js',
            'baseer_pos_customer_identity/static/src/app/partner_identity.xml',
            'baseer_pos_customer_identity/static/src/app/partner_identity_line.xml',
            'baseer_pos_customer_identity/static/src/app/partner_identity.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
