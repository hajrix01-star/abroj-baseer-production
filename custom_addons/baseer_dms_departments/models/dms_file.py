from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain


class DmsFile(models.Model):
    _inherit = "dms.file"

    # Keep the existing physical UNIQUE/FK reference and preview contract.
    bill_attachment_id = fields.Many2one(string="Original Linked Attachment")
    source_purchase_order_id = fields.Many2one("purchase.order", readonly=True, index=True, copy=False, ondelete="cascade")
    source_employee_id = fields.Many2one("hr.employee", readonly=True, index=True, copy=False, ondelete="cascade")
    source_version_id = fields.Many2one("hr.version", readonly=True, index=True, copy=False, ondelete="cascade")

    @api.model
    def _dms_reference_relation_fields(self):
        return super()._dms_reference_relation_fields() | {
            "source_purchase_order_id", "source_employee_id", "source_version_id",
        }

    @api.model
    def _dms_reference_relation_vals(self, record):
        vals = super()._dms_reference_relation_vals(record)
        vals.update({"source_purchase_order_id": False, "source_employee_id": False, "source_version_id": False})
        if record._name == "purchase.order":
            vals["source_purchase_order_id"] = record.id
        elif record._name == "hr.employee":
            vals["source_employee_id"] = record.id
        elif record._name == "hr.version":
            vals.update(source_version_id=record.id, source_employee_id=record.employee_id.id)
        return vals

    def _check_bill_source_read(self):
        super()._check_bill_source_read()
        actor = self.sudo(False)
        self.sudo().mapped("directory_id").filtered("managed_hr_private").with_env(actor.env).check_access("read")
        for item in self.sudo().filtered("source_employee_id"):
            if not actor.env.user.has_group("hr.group_hr_user"):
                raise AccessError(self.env._("HR document access requires an HR officer or manager."))
            employee = item.source_employee_id.with_env(actor.env)
            employee.check_access("read")
            if employee.company_id != item.company_id:
                raise AccessError(self.env._("The document and employee companies must match."))

    def _read_format(self, fnames, load="classic_read"):
        self.sudo().mapped("directory_id").filtered("managed_hr_private").sudo(False).check_access("read")
        return super()._read_format(fnames, load=load)

    @api.model
    def _dms_linked_source_domain(self):
        actor = self.sudo(False)
        result = super()._dms_linked_source_domain()
        attachments = actor.env["ir.attachment"]
        if not attachments.has_access("read"):
            return result
        for model_name, field in (
            ("purchase.order", "source_purchase_order_id"),
            ("hr.employee", "source_employee_id"),
            ("hr.version", "source_version_id"),
        ):
            model = actor.env[model_name]
            if not model.has_access("read"):
                continue
            source_domain = [("company_id", "in", actor.env.companies.ids)]
            if model_name.startswith("hr."):
                employees = actor.env["hr.employee"]
                if not actor.env.user.has_group("hr.group_hr_user") or not employees.has_access("read"):
                    continue
                employee_query = employees._search([("company_id", "in", actor.env.companies.ids)])
                if model_name == "hr.version":
                    source_domain.append(("employee_id", "in", employee_query))
            source_query = model._search(source_domain)
            attachment_query = attachments._search([
                ("res_model", "=", model_name), ("type", "=", "binary"), ("res_field", "=", False),
            ])
            domain = Domain(field, "in", source_query) & Domain("bill_attachment_id", "in", attachment_query)
            if model_name == "hr.version":
                domain &= Domain("source_employee_id", "in", employee_query)
            result |= domain
        return result

    @api.constrains("source_purchase_order_id", "source_employee_id", "source_version_id")
    def _check_department_reference(self):
        self._check_bill_reference()
