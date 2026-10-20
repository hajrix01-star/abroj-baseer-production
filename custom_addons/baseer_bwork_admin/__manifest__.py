{
    'name': 'BWork Administration',
    'summary': 'Scoped, read-only BWork operations and logical storage metadata',
    'version': '19.0.1.0.2',
    'category': 'Productivity',
    'license': 'LGPL-3',
    'depends': ['baseer_bchat'],
    'data': ['security/ir.model.access.csv', 'security/rules.xml', 'views/admin_views.xml'],
    'assets': {'web.assets_backend': [
        'baseer_bchat/static/src/bwork_gallery/gallery_client.js',
        'baseer_bchat/static/src/bwork_gallery/media_gallery.js',
        'baseer_bwork_admin/static/src/media_gallery.xml',
        'baseer_bwork_admin/static/src/media_gallery.scss',
    ]},
    'installable': True,
    'application': False,
    'auto_install': False,
}
