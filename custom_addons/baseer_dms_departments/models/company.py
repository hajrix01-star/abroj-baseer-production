from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class Company(models.Model):
    _inherit = "res.company"

    dms_bill_root_id = fields.Many2one(domain="[('company_id', '=', id)]")
    dms_company_root_id = fields.Many2one("dms.directory", string="Company Document Root", ondelete="restrict", copy=False)
    dms_purchase_root_id = fields.Many2one("dms.directory", string="Purchases Documents", ondelete="restrict", copy=False)
    dms_purchase_order_root_id = fields.Many2one("dms.directory", string="Purchase Order Documents", ondelete="restrict", copy=False)
    dms_hr_root_id = fields.Many2one("dms.directory", string="Human Resources Documents", ondelete="restrict", copy=False)
    dms_employee_root_id = fields.Many2one("dms.directory", string="Employee Documents", ondelete="restrict", copy=False)

    def _dms_bill_root_parent_valid(self, root):
        self.ensure_one()
        return super()._dms_bill_root_parent_valid(root) or bool(
            self.dms_company_root_id and root.parent_id == self.dms_purchase_root_id
            and root.root_directory_id == self.dms_company_root_id
            and root.storage_id == self.dms_company_root_id.storage_id
        )

    @api.model
    def _dms_department_config_fields(self):
        return {"dms_company_root_id", "dms_purchase_root_id", "dms_purchase_order_root_id", "dms_hr_root_id", "dms_employee_root_id"}

    @api.constrains("dms_company_root_id", "dms_purchase_root_id", "dms_purchase_order_root_id", "dms_hr_root_id", "dms_employee_root_id", "dms_bill_root_id")
    def _check_department_configuration(self):
        for company in self.sudo():
            root = company.dms_company_root_id
            if not root:
                if any(company[field] for field in company._dms_department_config_fields() - {"dms_company_root_id"}):
                    raise ValidationError(self.env._("Department folders require a company document root."))
                continue
            if root.parent_id or root.company_id != company or root.storage_id.save_type not in ("database", "file"):
                raise ValidationError(self.env._("The company document root must belong to this company."))
            expected = {
                "dms_purchase_root_id": root,
                "dms_purchase_order_root_id": company.dms_purchase_root_id,
                "dms_bill_root_id": company.dms_purchase_root_id,
                "dms_hr_root_id": root,
                "dms_employee_root_id": company.dms_hr_root_id,
            }
            for field, parent in expected.items():
                folder = company[field]
                if not folder or folder.parent_id != parent or folder.storage_id != root.storage_id:
                    raise ValidationError(self.env._("Department document folders must remain in their company hierarchy."))
            if any(folder.res_model or folder.res_id or folder.access_token for folder in root | company.dms_purchase_root_id | company.dms_purchase_order_root_id | company.dms_hr_root_id | company.dms_employee_root_id):
                raise ValidationError(self.env._("Managed document folders cannot have native associations or public tokens."))

    def write(self, vals):
        fields_to_protect = self._dms_department_config_fields() | {"dms_bill_root_id"}
        for company in self:
            if company.dms_company_root_id and any(
                field in vals and vals[field] != company[field].id for field in fields_to_protect
            ):
                raise UserError(self.env._("Managed company document configuration is protected."))
        return super().write(vals)

    def _setup_dms_departments(self, access_group=None):
        """Explicit owner-run metadata setup. Never iterate HR records or bytes."""
        actor = self.sudo(False)
        if not actor.env.user.has_group("base.group_system") or not actor.env.user.has_group("dms.group_dms_manager"):
            raise AccessError(self.env._("Only the owner administrator can configure department documents."))
        actor.check_access("write")
        result = {}
        for company in self.sorted("id"):
            if company.id not in actor.env.companies.ids:
                raise AccessError(self.env._("Select the company before configuring its documents."))
            self.env.cr.execute("SELECT id FROM res_company WHERE id = %s FOR UPDATE", [company.id])
            company.invalidate_recordset()
            company = company.sudo()
            existing = company.dms_bill_root_id
            groups = access_group.sudo() if access_group else existing.group_ids
            if not groups:
                groups = self.env["dms.access.group"].sudo().create({
                    "name": self.env._("Private company documents"),
                    "perm_create": True, "perm_write": True, "perm_unlink": True,
                    "explicit_user_ids": [(6, 0, [actor.env.uid])],
                })
            storage = existing.storage_id if existing else self.env["dms.storage"].sudo().create({
                "name": company.name, "company_id": company.id, "save_type": "file",
                "model_ids": [(5, 0, 0)], "inherit_access_from_parent_record": False,
            })
            if storage.company_id != company or storage.save_type not in ("file", "database") or storage.inherit_access_from_parent_record:
                raise ValidationError(self.env._("The company document root must belong to this company."))
            directory = self.env["dms.directory"]
            def folder(key, name, parent=False, private=False):
                return directory._ensure_managed_directory(
                    company, f"{company.id}:{key}", name, parent=parent,
                    storage=storage, groups=groups, hr_private=private,
                )
            root = folder("root", company.name)
            purchases = folder("purchases", self.env._("Purchases"), root)
            if existing:
                bills = directory._adopt_vendor_bill_leaf(company, existing, purchases)
            else:
                bills = folder("bills", self.env._("Vendor Bills"), purchases)
            orders = folder("purchase_orders", self.env._("Purchase Orders"), purchases)
            hr = folder("hr", self.env._("Human Resources"), root, True)
            employees = folder("employees", self.env._("Employees"), hr, True)
            sales = folder("sales", self.env._("Sales"), root)
            administration = folder("administration", self.env._("Administration"), root)
            company.write({
                "dms_company_root_id": root.id, "dms_purchase_root_id": purchases.id,
                "dms_bill_root_id": bills.id, "dms_purchase_order_root_id": orders.id,
                "dms_hr_root_id": hr.id, "dms_employee_root_id": employees.id,
            })
            result[company.id] = {key: value.id for key, value in {
                "root": root, "purchases": purchases, "bills": bills, "purchase_orders": orders,
                "hr": hr, "employees": employees, "sales": sales, "administration": administration,
            }.items()}
        return result

    def _ensure_dms_employee_directories(self, employee):
        """Lazy folder creation only for an eligible attached private HR source."""
        self.ensure_one()
        employee.ensure_one()
        if employee.company_id != self or not self.dms_employee_root_id:
            raise ValidationError(self.env._("The document and employee companies must match."))
        self.env.cr.execute("SELECT id FROM res_company WHERE id = %s FOR UPDATE", [self.id])
        root = self.sudo().dms_employee_root_id
        directory = self.env["dms.directory"]
        parent = directory._ensure_managed_directory(
            self.sudo(), f"{self.id}:employee:{employee.id}",
            f"{employee.id} - {employee.sudo().name}".replace("/", "_").replace("\\", "_"),
            parent=root, storage=root.storage_id, groups=root.group_ids,
            hr_private=True, employee=employee.sudo(),
        )
        result = {"employee": parent}
        for kind, name in (("documents", self.env._("Documents")), ("contracts", self.env._("Contracts"))):
            result[kind] = directory._ensure_managed_directory(
                self.sudo(), f"{self.id}:employee:{employee.id}:{kind}", name,
                parent=parent, storage=root.storage_id, groups=root.group_ids,
                hr_private=True, employee=employee.sudo(),
            )
        return result


class Storage(models.Model):
    _inherit = "dms.storage"

    def write(self, vals):
        if set(vals) & {"company_id", "save_type", "model_ids", "inherit_access_from_parent_record"}:
            if self.env["res.company"].sudo().search_count([("dms_company_root_id.storage_id", "in", self.ids)], limit=1):
                raise UserError(self.env._("Managed company document configuration is protected."))
        return super().write(vals)
