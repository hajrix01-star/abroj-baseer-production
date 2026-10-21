{
    'name': 'BWork Procurement Bridge',
    'version': '19.0.1.0.6',
    'category': 'Inventory/Purchase',
    'summary': 'Narrow BWork order menu and internal procurement submission',
    'license': 'LGPL-3',
    'depends': ['baseer_bwork', 'baseer_procurement_requests'],
    'data': ['security/security.xml', 'views/res_users_bwork_views.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
