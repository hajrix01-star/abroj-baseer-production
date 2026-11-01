{
    'name': 'Baseer POS Cache Resilience',
    'version': '19.0.1.0.0',
    'summary': 'Bound POS resource caching without touching unsynchronized orders',
    'category': 'Point of Sale',
    'license': 'LGPL-3',
    'depends': ['point_of_sale'],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_pos_cache_resilience/static/src/cache_status.js',
        ],
    },
    'installable': True,
}
