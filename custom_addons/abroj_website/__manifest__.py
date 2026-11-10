{
    'name': 'Abroj Corporate Website',
    'version': '19.0.1.5.12',
    'license': 'LGPL-3',
    'depends': ['website_crm'],
    'data': ['views/abroj_templates.xml', 'data/website_data.xml', 'data/website_logo.xml'],
    'assets': {'web.assets_frontend': ['abroj_website/static/src/scss/abroj-v2.scss', 'abroj_website/static/src/js/mobile-menu.js']},
    'installable': True,
}
