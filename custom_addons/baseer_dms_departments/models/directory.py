from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from odoo.addons.baseer_dms_bill_link.models.configuration import Directory as BillDirectory


class Directory(models.Model):
    _inherit = "dms.directory"

    managed_key = fields.Char(readonly=True, index=True, copy=False)
    managed_hr_private = fields.Boolean(readonly=True, copy=False, index=True)
    managed_employee_id = fields.Many2one("hr.employee", readonly=True, copy=False, index=True, ondelete="restrict")
    managed_hr_permission = fields.Boolean(compute="_compute_managed_hr_permission", search="_search_managed_hr_permission")
    _managed_key_unique = models.Constraint("UNIQUE(managed_key)", "A managed folder can exist only once.")

    @api.model
    def _search_managed_hr_permission(self, operator, value):
        actor = self.sudo(False)
        domain = Domain("managed_hr_private", "=", False)
        employees = actor.env["hr.employee"]
        if actor.env.user.has_group("hr.group_hr_user") and employees.has_access("read"):
            employee_query = employees._search([("company_id", "in", actor.env.companies.ids)])
            domain |= Domain("company_id", "in", actor.env.companies.ids) & (
                Domain("managed_employee_id", "=", False) | Domain("managed_employee_id", "in", employee_query)
            )
        return domain if operator in ("in", "=") else ~domain

    def _check_managed_hr_read(self):
        actor = self.sudo(False)
        for folder in self.sudo().filtered("managed_hr_private"):
            if not actor.env.user.has_group("hr.group_hr_user") or folder.company_id.id not in actor.env.companies.ids:
                raise AccessError(self.env._("HR document access requires an HR officer or manager."))
            if folder.managed_employee_id:
                folder.managed_employee_id.with_env(actor.env).check_access("read")

    def _compute_managed_hr_permission(self):
        for folder in self:
            try:
                folder._check_managed_hr_read()
                folder.managed_hr_permission = True
            except AccessError:
                folder.managed_hr_permission = False

    def check_access(self, operation):
        result = super().check_access(operation)
        self._check_managed_hr_read()
        return result

    def _read_format(self, fnames, load="classic_read"):
        self._check_managed_hr_read()
        return super()._read_format(fnames, load=load)

    def _contains_bill_documents(self):
        return super()._contains_bill_documents() or bool(self.sudo().search_count([
            ("id", "child_of", self.ids), "|", ("managed_key", "!=", False), ("managed_hr_private", "=", True)
        ], limit=1))

    @api.model_create_multi
    def create(self, vals_list):
        fields_to_guard = {"managed_key", "managed_hr_private", "managed_employee_id"}
        if any(any(vals.get(field) for field in fields_to_guard) for vals in vals_list):
            raise UserError(self.env._("Managed document folders are configured by the private setup method."))
        vals_list = [dict(vals, **dict.fromkeys(fields_to_guard, False)) for vals in vals_list]
        # User-created children inherit private metadata, never caller defaults.
        for vals in vals_list:
            parent = self.sudo().browse(vals.get("parent_id") or self.env.context.get("default_parent_id"))
            if parent and parent.managed_hr_private:
                vals.update(managed_hr_private=True, managed_employee_id=parent.managed_employee_id.id)
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & {"managed_key", "managed_hr_private", "managed_employee_id"}:
            raise UserError(self.env._("Managed document folder identity is protected."))
        if set(vals) & {"parent_id", "storage_id", "res_model", "res_id", "model_id", "access_token"}:
            target = self.sudo().browse(vals.get("parent_id")) if vals.get("parent_id") else self.browse()
            if self.sudo().filtered("managed_hr_private") or (target and target.managed_hr_private):
                raise UserError(self.env._("HR document folder associations are protected."))
        return super().write(vals)

    def copy_data(self, default=None):
        if self.sudo().filtered(lambda folder: folder.managed_key or folder.managed_hr_private):
            raise UserError(self.env._("Managed document folders cannot be copied."))
        return super().copy_data(default)

    def unlink(self):
        if self.sudo().filtered("managed_key"):
            raise UserError(self.env._("Managed document folders cannot be deleted."))
        return super().unlink()

    @api.model
    def _ensure_managed_directory(self, company, key, name, parent, storage, groups, hr_private=False, employee=False):
        company.ensure_one()
        self.env.cr.execute("SELECT id FROM res_company WHERE id = %s FOR UPDATE", [company.id])
        if storage.company_id != company or (parent and parent.storage_id != storage):
            raise ValidationError(self.env._("Department document folders must remain in their company hierarchy."))
        found = self.sudo().with_context(active_test=False).search([("managed_key", "=", key)], limit=1)
        if found:
            if (
                found.storage_id != storage or found.parent_id.id != (parent.id if parent else False)
                or found.managed_hr_private != hr_private
                or found.managed_employee_id.id != (employee.id if employee else False)
            ):
                raise ValidationError(self.env._("Managed document folder identity is protected."))
            return found
        vals = {
            "name": name, "parent_id": parent.id if parent else False, "storage_id": storage.id,
            "is_root_directory": not bool(parent), "group_ids": [(6, 0, groups.ids)],
            "managed_key": key, "managed_hr_private": hr_private,
            "managed_employee_id": employee.id if employee else False,
        }
        # Private Python method only: no public RPC or context authentication.
        return super(Directory, self.sudo()).create([vals])

    @api.model
    def _adopt_vendor_bill_leaf(self, company, leaf, parent):
        company.ensure_one()
        leaf.ensure_one()
        parent.ensure_one()
        key = f"{company.id}:bills"
        if (
            leaf.company_id != company or parent.company_id != company or leaf.storage_id != parent.storage_id
            or leaf.res_model or leaf.res_id or leaf.access_token
            or (leaf.parent_id and leaf.parent_id != parent)
            or (leaf.managed_key and leaf.managed_key != key)
        ):
            raise ValidationError(self.env._("Existing vendor bill folders can only be adopted within the same company."))
        links = self.env["dms.file"].sudo().with_context(active_test=False).search([
            ("directory_id", "=", leaf.id), ("bill_attachment_id", "!=", False)
        ])
        if any(link.company_id != company or link.bill_move_id.company_id != company for link in links):
            raise ValidationError(self.env._("Existing vendor bill folders can only be adopted within the same company."))
        if leaf.managed_key == key and leaf.parent_id == parent:
            return leaf
        # Narrow, invariant-checked server adoption bypasses only our freeze guards;
        # native DMS still validates the same-storage parent and recomputes paths.
        super(BillDirectory, leaf.sudo()).write({
            "parent_id": parent.id, "is_root_directory": False,
            "managed_key": key, "name": self.env._("Vendor Bills"),
        })
        return leaf
