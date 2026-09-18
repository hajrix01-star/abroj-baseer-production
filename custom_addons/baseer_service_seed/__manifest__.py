{
    'name': 'Baseer Common Services Seed',
    'summary': 'Shared suppliers, company service products and native expense mappings',
    'version': '19.0.1.5.0',
    'license': 'LGPL-3',
    'depends': ['baseer_company_setup', 'baseer_purchase_batch', 'baseer_native_spend'],
    'data': [
        'data/categories.xml',
        'security/ir.model.access.csv',
        'views/res_partner_views.xml',
        'views/hr_service_analytic_readiness_views.xml',
        'views/company_onboarding_views.xml',
    ],
    'installable': True,
}
