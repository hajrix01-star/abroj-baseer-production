from odoo import fields, models


class BaseerCompanyOnboarding(models.TransientModel):
    _inherit = 'baseer.company.onboarding'

    setup_employee_services = fields.Boolean(
        string='خدمات الموظفين والتوزيع التحليلي', default=True,
        help='جزء أساسي من تهيئة الحسابات السعودية؛ يبقى الحقل للتوافق مع السجلات المؤقتة فقط.',
    )
    employee_services_state = fields.Selection([
        ('missing', 'ناقص'),
        ('ready', 'جاهز'),
        ('blocked', 'متوقف'),
    ], string='حالة خدمات الموظفين', readonly=True)
    employee_services_message = fields.Char(readonly=True)
