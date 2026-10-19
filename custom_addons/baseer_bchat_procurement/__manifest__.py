{
    'name': 'BChat Procurement Bridge',
    'version': '19.0.1.0.4',
    'category': 'Inventory/Purchase',
    'summary': 'Narrow BChat order menu and internal procurement submission',
    'license': 'LGPL-3',
    'depends': ['baseer_bchat', 'baseer_procurement_requests'],
    'data': ['security/security.xml', 'views/res_users_bchat_views.xml'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
