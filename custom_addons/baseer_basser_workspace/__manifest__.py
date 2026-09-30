{
    'name': 'Baseer Workspace',
    'summary': 'Role-curated navigation to approved Baseer operations',
    'version': '19.0.1.0.11',
    'category': 'Productivity',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': [
        'baseer_access_roles',
        'baseer_procurement_requests',
        'baseer_sales_heat_calendar',
        'baseer_purchase_expense_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/pos_cashier_menu.xml',
        'data/workspace_data.xml',
        'data/pos_cashier_dashboard_data.xml',
        'views/workspace_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'baseer_basser_workspace/static/src/workspace.js',
            'baseer_basser_workspace/static/src/workspace.xml',
            'baseer_basser_workspace/static/src/workspace.scss',
        ],
        'web.assets_unit_tests': [
            'baseer_basser_workspace/static/tests/workspace.test.js',
        ],
    },
    'application': True,
    'installable': True,
}
