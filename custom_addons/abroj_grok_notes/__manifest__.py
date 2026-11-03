{
    'name': 'Grok Notes',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail', 'project', 'account'],
    'data': ['security/groups.xml', 'security/ir.model.access.csv', 'security/rules.xml',
             'views/grok_note_views.xml', 'views/linked_views.xml'],
    'assets': {'web.assets_backend': ['abroj_grok_notes/static/src/notes.scss']},
    'application': True,
    'installable': True,
}
