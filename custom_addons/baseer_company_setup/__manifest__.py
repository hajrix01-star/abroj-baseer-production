{
    'name': 'Baseer Company Accounting Setup',
    'summary': 'Ready native charts, journals and payroll defaults for independent companies',
    'version': '19.0.3.0.0',
    'license': 'LGPL-3',
    'depends': ['baseer_payroll', 'l10n_sa'],
    'data': [
        'security/ir.model.access.csv',
        'views/company_views.xml',
        'views/company_onboarding_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_company_setup/static/src/scss/company_onboarding.scss',
        ],
    },
    'installable': True,
}
