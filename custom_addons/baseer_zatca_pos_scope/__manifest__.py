{
    'name': 'Baseer ZATCA POS Scope',
    'version': '19.0.1.0.0',
    'summary': 'Limit Saudi ZATCA POS invoicing to explicitly enabled POS configurations',
    'category': 'Accounting/Localizations/EDI',
    'license': 'LGPL-3',
    'depends': ['l10n_sa_edi_pos'],
    'data': ['views/pos_config_views.xml'],
    'assets': {
        'point_of_sale._assets_pos': [
            'baseer_zatca_pos_scope/static/src/overrides/models/pos_order.js',
        ],
    },
    'installable': True,
}
