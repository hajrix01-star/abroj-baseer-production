from odoo import api, models
from odoo.exceptions import UserError


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def _dms_managed_models(self):
        return super()._dms_managed_models() | {"purchase.order", "hr.employee", "hr.version"}

    def _dms_source_record(self):
        self.ensure_one()
        if self.res_model == "account.move":
            return super()._dms_source_record()
        if self.res_model not in self._dms_managed_models() or not self.res_id or self.res_field or self.type != "binary":
            return False
        record = self.env[self.res_model].sudo().browse(self.res_id).exists()
        if not record or not record.company_id:
            return False
        if self.res_model == "hr.version" and (
            not record.employee_id or record.employee_id.company_id != record.company_id
        ):
            return False
        return record

    def _dms_reference_destination(self, record, create=False):
        if record._name == "account.move":
            return super()._dms_reference_destination(record, create=create)
        company = record.company_id
        if not company.dms_company_root_id:
            return self.env["dms.directory"]
        if record._name == "purchase.order":
            return company.dms_purchase_order_root_id
        employee = record if record._name == "hr.employee" else record.employee_id
        if create:
            folders = company._ensure_dms_employee_directories(employee)
            return folders["documents" if record._name == "hr.employee" else "contracts"]
        suffix = "documents" if record._name == "hr.employee" else "contracts"
        return self.env["dms.directory"].sudo().search([
            ("managed_key", "=", f"{company.id}:employee:{employee.id}:{suffix}")
        ], limit=1)

    def _dms_reference_matches(self, link, record):
        expected = self.env["dms.file"]._dms_reference_relation_vals(record)
        return all(link[field].id == (value or False) for field, value in expected.items())

    def write(self, vals):
        if set(vals) & {"res_model", "res_id", "res_field", "type", "company_id"}:
            links = self.env["dms.file"].sudo().with_context(active_test=False).search([
                ("bill_attachment_id", "in", self.ids), ("bill_move_id", "=", False)
            ])
            for source in links.mapped("bill_attachment_id"):
                for field in ("res_model", "res_id", "res_field", "type", "company_id"):
                    current = source[field].id if field == "company_id" else source[field]
                    if field in vals and vals[field] != current:
                        raise UserError(self.env._("Remove document references before changing the original association."))
        return super().write(vals)
