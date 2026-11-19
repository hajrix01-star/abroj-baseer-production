{
    'name': 'Baseer POS Cache Resilience',
    'version': '19.0.1.0.2',
    'summary': 'Bound POS resource caching without touching unsynchronized orders',
    'category': 'Point of Sale',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_cache_resilience/static/src/cache_status.js',
            'baseer_pos_cache_resilience/static/src/receipt_number_reservation.js',
            'baseer_pos_cache_resilience/static/src/receipt_storage.js',
            ('replace',
             'point_of_sale/static/src/app/components/loader/critical_pos_error/reset_local_data.js',
             'baseer_pos_cache_resilience/static/src/reset_local_data.js'),
        ],
    },
    'installable': True,
}
