{
    'name': 'Baseer Tobacco Service Fee Report',
    'version': '19.0.1.0.0',
    'author': 'Baseer',
    'license': 'LGPL-3',
    'depends': ['baseer_report_engine', 'point_of_sale'],
    'data': ['data/report.xml', 'views/menu.xml', 'report/tobacco_pdf.xml'],
    'assets': {'web.assets_backend': [
        'baseer_report_engine_tobacco/static/src/tobacco.js',
        'baseer_report_engine_tobacco/static/src/tobacco.xml',
        'baseer_report_engine_tobacco/static/src/tobacco.scss',
    ]},
    'auto_install': False,
    'installable': True,
}
