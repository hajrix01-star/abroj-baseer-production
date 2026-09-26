from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    baseer_manager_app_access = fields.Boolean(
        string='السماح بدخول تطبيق المدير',
        help='Allows this user to open the Baseer manager PWA.',
        default=False,
    )
