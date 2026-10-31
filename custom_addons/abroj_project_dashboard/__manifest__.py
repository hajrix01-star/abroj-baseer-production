{
    'name': 'Abroj Project Dashboard',
    'version': '19.0.1.1.0',
    'license': 'LGPL-3',
    'depends': ['project', 'analytic', 'account', 'abroj_contracting'],
    'data': ['security/ir.model.access.csv', 'security/rules.xml', 'views/dashboard.xml', 'data/promissory.xml', 'report/promissory.xml'],
    'assets': {'web.assets_backend': [
        'abroj_project_dashboard/static/src/dashboard.js',
        'abroj_project_dashboard/static/src/dashboard.xml',
        'abroj_project_dashboard/static/src/dashboard.scss',
        'abroj_project_dashboard/static/src/gallery.js',
        'abroj_project_dashboard/static/src/gallery.xml',
        'abroj_project_dashboard/static/src/gallery.scss',
    ]},
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
