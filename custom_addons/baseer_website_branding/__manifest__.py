{
    'name': 'Baseer Website Branding',
    'version': '19.0.2.2.2',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['abroj_website', 'website_crm'],
    'data': ['views/abroj_contact_templates.xml'],
    'assets': {
        'web.assets_frontend': [
            'baseer_website_branding/static/src/scss/homepage-shell.scss',
        ],
    },
    'installable': True,
}
