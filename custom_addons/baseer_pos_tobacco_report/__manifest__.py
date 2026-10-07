{
    'name': 'Baseer POS Tobacco Fee Register',
    'summary': 'Operational tobacco fee register from completed POS sales',
    'version': '19.0.1.4.4',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'category': 'Accounting/Reporting',
    'depends': ['account', 'point_of_sale', 'baseer_reports_menu'],
    'data': [
        'security/ir.model.access.csv',
        'views/tobacco_report_wizard_views.xml',
        'report/tobacco_report.xml',
    ],
    'application': False,
    'installable': True,
}
