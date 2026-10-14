from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.fields import Domain

from odoo.addons.dms.models.dms_file import DMSFile as NativeDMSFile


def _dms_search_panel_parent_id(value):
    """Odoo 19 returns an ID; older classic_read returns (ID, label)."""
    if isinstance(value, (tuple, list)):
        value = value[0] if value else False
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else False


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

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        if field_name != "directory_id":
            return super().search_panel_select_range(field_name, **kwargs)

        # Keep native DMS's empty-folder listing, but never read a hidden parent's
        # name to normalize a Many2one. Odoo 19 search_read returns bare IDs.
        records = self.env["dms.directory"].with_context(directory_short_name=True).search_read(
            [("is_hidden", "=", False)], ["display_name", "parent_id"]
        )
        visible_ids = {record["id"] for record in records}
        parents = {
            record["id"]: _dms_search_panel_parent_id(record["parent_id"]) for record in records
        }
        selected_ids = visible_ids
        if self.env.context.get("active_model") == "dms.directory":
            files = self.search([
                ("directory_id", "child_of", self.env.context.get("active_id"))
            ])
            selected_ids = set()
            for directory_id in files.mapped("directory_id").ids:
                seen = set()
                while directory_id in visible_ids and directory_id not in seen:
                    seen.add(directory_id)
                    selected_ids.add(directory_id)
                    directory_id = parents[directory_id]

        enable_counters = kwargs.get("enable_counters")
        values = {}
        for record in records:
            record_id = record["id"]
            if record_id not in selected_ids:
                continue
            parent_id = parents[record_id]
            values[record_id] = {
                "id": record_id, "display_name": record["display_name"],
                "parent_id": parent_id if parent_id in selected_ids else False,
            }
            if enable_counters:
                values[record_id]["__count"] = 0

        if enable_counters:
            # Skip only the incompatible native DMS override. Its abstract mixin
            # and Odoo core still compute counters under the acting user's rules.
            result = super(NativeDMSFile, self).search_panel_select_range(field_name, **kwargs)
            for item in result["values"]:
                if item["id"] in values:
                    values[item["id"]]["__count"] = item["__count"]
        return {"parent_field": "parent_id", "values": list(values.values())}

    def _search_panel_sanitized_parent_hierarchy(self, records, parent_name, ids):
        if not self.env.context.get("skip_sanitized_parent_hierarchy"):
            return super()._search_panel_sanitized_parent_hierarchy(records, parent_name, ids)
        if parent_name:
            visible_ids = {record["id"] for record in records}
            for record in records:
                parent_id = _dms_search_panel_parent_id(record.get(parent_name))
                # The installed core counter reader still indexes value[0].
                # Provide its legacy shape without reading any parent label;
                # the public directory range above continues to return IDs.
                record[parent_name] = (parent_id, "") if parent_id in visible_ids else False
        return records
