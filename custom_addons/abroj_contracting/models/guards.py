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


def _expense_guard(method):
    """Wrap a registry method without importing the optional expense addon."""
    from functools import wraps

    @wraps(method)
    def guarded(records, *args, **kwargs):
        check_agent(records.env)
        return method(records, *args, **kwargs)

    guarded._abroj_expense_guard = True
    return guarded


class ExpenseGuards(models.AbstractModel):
    _name = 'abroj.contracting.expense.guards'
    _description = 'حماية اعتماد المصروفات الاختيارية'

    def _register_hook(self):
        result = super()._register_hook()
        # Odoo 19 uses hr.expense; older/optional addons may provide sheets.
        # Registry hooks run again when modules are installed or upgraded.
        methods = {
            'hr.expense': ('action_approve', 'action_approve_duplicates', 'action_post', '_do_approve', '_post_without_wizard'),
            'hr.expense.sheet': ('action_approve_expense_sheets', 'approve_expense_sheets',
                                 'action_sheet_move_create', 'action_post', 'action_approve'),
        }
        for model_name, names in methods.items():
            if model_name not in self.env.registry:
                continue
            model = self.env.registry[model_name]
            for name in names:
                method = getattr(model, name, None)
                if method and not getattr(method, '_abroj_expense_guard', False):
                    setattr(model, name, _expense_guard(method))
        return result
