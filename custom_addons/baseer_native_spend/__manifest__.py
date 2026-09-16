{
    'name': 'Baseer Native Spend Foundation',
    'version': '19.0.1.3.0',
    'category': 'Accounting/Accounting',
    'summary': 'Native spend analytics setup and vendor bill enforcement',
    'license': 'LGPL-3',
    'depends': ['account'],
    # The root plan is reconciled in post_init_hook.  Loading a static XML
    # record here would create a second root beside a reviewed live plan.
    'data': [
        'security/ir.model.access.csv',
        'security/spend_map_rules.xml',
        'views/spend_map_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
