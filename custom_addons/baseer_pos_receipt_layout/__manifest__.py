{
    'name': 'Baseer POS Receipt Layout',
    'summary': 'Optional 80 mm layout for the original POS receipt',
    'version': '19.0.1.0.2',
    'category': 'Baseer/POS',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['point_of_sale', 'baseer_pos_print_bridge'],
    'data': [
        'views/receipt_layout_views.xml',
    ],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_receipt_layout/static/src/app/order_receipt.xml',
            'baseer_pos_receipt_layout/static/src/app/order_receipt.scss',
        ],
    },
    'installable': True,
}
