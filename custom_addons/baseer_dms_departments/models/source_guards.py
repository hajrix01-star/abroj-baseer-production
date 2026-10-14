from odoo import models
from odoo.exceptions import UserError


def guard_source(records, vals, fields, link_field):
    for record in records:
        changed = any(
            key in vals and vals[key] != record[key].id for key in fields
        )
        if changed and records.env["dms.file"].sudo().with_context(active_test=False).search_count([
            (link_field, "=", record.id)
        ], limit=1):
            raise UserError(records.env._("Remove document references before changing the source company or employee."))


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    def write(self, vals):
        guard_source(self, vals, ("company_id",), "source_purchase_order_id")
        return super().write(vals)


class Employee(models.Model):
    _inherit = "hr.employee"

    def write(self, vals):
        guard_source(self, vals, ("company_id",), "source_employee_id")
        if "company_id" in vals:
            for employee in self:
                if vals["company_id"] != employee.company_id.id and self.env["dms.directory"].sudo().search_count([
                    ("managed_employee_id", "=", employee.id)
                ], limit=1):
                    raise UserError(self.env._("The employee has protected document folders in this company."))
        return super().write(vals)


class Version(models.Model):
    _inherit = "hr.version"

    def write(self, vals):
        guard_source(self, vals, ("company_id", "employee_id"), "source_version_id")
        return super().write(vals)
