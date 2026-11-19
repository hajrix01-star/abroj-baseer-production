{
    'name': 'Baseer POS Global Discount',
    'summary': 'Server-authorized invoice discounts with tax and refund lineage',
    'version': '19.0.1.0.1',
    'category': 'Baseer/POS',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['pos_discount', 'baseer_pos_product_substitution'],
    'data': ['security/ir.model.access.csv', 'security/discount_security.xml', 'views/pos_config_views.xml'],
    'assets': {'point_of_sale._assets_pos': [
        'baseer_pos_global_discount/static/src/app/discount_flow.js',
        'baseer_pos_global_discount/static/src/app/global_discount.js',
        'baseer_pos_global_discount/static/src/app/global_discount.xml',
        'baseer_pos_global_discount/static/src/app/global_discount.scss',
    ]},
    'installable': True,
}
