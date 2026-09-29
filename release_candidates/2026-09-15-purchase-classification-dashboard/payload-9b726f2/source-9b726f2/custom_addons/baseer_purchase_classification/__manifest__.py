{
    'name': 'Baseer Purchase Classification',
    'version': '19.0.2.1.0',
    'summary': 'Company-scoped immutable analytical classifications for supplier-bill lines',
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': ['account', 'baseer_purchase_batch'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'views/purchase_classification_views.xml',
    ],
    'installable': True,
}

