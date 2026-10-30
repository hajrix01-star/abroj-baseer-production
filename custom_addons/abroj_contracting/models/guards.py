from odoo import models
from odoo.exceptions import AccessError


def check_agent(env):
    # Deliberate sudo is the only bypass; never special-case a user ID.
    if not env.su and env.user.has_group('abroj_contracting.group_extraction_agent'):
        raise AccessError('وكيل الاستخراج لا يملك صلاحية اعتماد العمليات المالية.')


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        check_agent(self.env)
        return super().action_post()


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_post(self):
        check_agent(self.env)
        return super().action_post()

    def action_validate(self):
        check_agent(self.env)
        return super().action_validate()


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def button_confirm(self):
        check_agent(self.env)
        return super().button_confirm()
