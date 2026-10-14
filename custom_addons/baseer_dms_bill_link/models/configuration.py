from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class Company(models.Model):
    _inherit = "res.company"

    dms_bill_root_id = fields.Many2one(
        "dms.directory", string="Vendor Bill Document Root", ondelete="restrict",
        domain="[('parent_id', '=', False), ('company_id', '=', id)]",
        help="Automatically index new vendor bill attachments here without copying originals.",
    )

    @api.constrains("dms_bill_root_id")
    def _check_dms_bill_root(self):
        for company in self:
            root = company.dms_bill_root_id
            if root and (
                root.parent_id or root.company_id != company
                or root.storage_id.save_type not in ("database", "file")
                or root.storage_id.inherit_access_from_parent_record
                or root.res_model or root.res_id or root.access_token
            ):
                raise ValidationError(self.env._(
                    "Select a private, unlinked database or filestore root belonging to this company."
                ))

    def write(self, vals):
        if "dms_bill_root_id" in vals:
            for company in self:
                if company.dms_bill_root_id and company.dms_bill_root_id.id != vals["dms_bill_root_id"]:
                    if self.env["dms.file"].sudo().search_count([
                        ("bill_attachment_id", "!=", False), ("company_id", "=", company.id)
                    ], limit=1):
                        raise UserError(self.env._("Remove document references before changing their root."))
        return super().write(vals)


class Storage(models.Model):
    _inherit = "dms.storage"

    @api.constrains("model_ids")
    def _check_native_bill_link_disabled(self):
        if any("account.move" in storage.model_ids.mapped("model") for storage in self):
            raise ValidationError(self.env._("Native accounting attachment indexing must remain disabled."))

    def write(self, vals):
        if set(vals) & {"company_id", "save_type", "model_ids", "inherit_access_from_parent_record"}:
            if self.env["res.company"].sudo().search_count([
                ("dms_bill_root_id.storage_id", "in", self.ids)
            ], limit=1):
                raise UserError(self.env._("The configured vendor bill document storage is protected."))
        return super().write(vals)


class Directory(models.Model):
    _inherit = "dms.directory"

    def _contains_bill_documents(self):
        return bool(self.env["res.company"].sudo().search_count([
            ("dms_bill_root_id", "child_of", self.ids)
        ], limit=1) or self.env["dms.file"].sudo().search_count([
            ("bill_attachment_id", "!=", False), ("directory_id", "child_of", self.ids)
        ], limit=1))

    def write(self, vals):
        if set(vals) & {"parent_id", "storage_id", "res_model", "res_id", "model_id", "access_token"}:
            if self._contains_bill_documents():
                raise UserError(self.env._("The vendor bill document root and its association are protected."))
        return super().write(vals)

    def check_access_token(self, access_token=False):
        if self._contains_bill_documents():
            return False
        return super().check_access_token(access_token)

    def _portal_ensure_token(self):
        if self._contains_bill_documents():
            raise UserError(self.env._("Vendor bill documents cannot be shared with public tokens."))
        return super()._portal_ensure_token()
