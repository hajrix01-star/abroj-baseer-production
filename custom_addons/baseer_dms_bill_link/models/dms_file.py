from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

from odoo.addons.dms.tools import file


class DmsFile(models.Model):
    _inherit = "dms.file"

    bill_attachment_id = fields.Many2one(
        "ir.attachment", string="Original Vendor Bill Attachment",
        ondelete="cascade", index=True, copy=False, readonly=True,
    )
    # ir.attachment.res_id is an integer, not a relational field. Store the
    # authoritative bill separately to allow a source-rule SQL subquery.
    bill_move_id = fields.Many2one("account.move", readonly=True, index=True, copy=False)
    bill_source_permission = fields.Boolean(
        compute="_compute_bill_source_permission", search="_search_bill_source_permission"
    )
    _bill_attachment_unique = models.Constraint(
        "UNIQUE(bill_attachment_id)", "An original attachment can have only one document reference."
    )

    def _check_bill_source_read(self):
        actor = self.sudo(False)
        for item in self.sudo().filtered("bill_attachment_id"):
            source = item.bill_attachment_id.with_env(actor.env)
            move = actor.env["account.move"].browse(source.sudo().res_id)
            source.check_access("read")
            move.check_access("read")
            if move.company_id.id not in actor.env.companies.ids:
                raise AccessError(self.env._("The original bill belongs to another company."))

    @api.model
    def _search_bill_source_permission(self, operator, value):
        actor = self.sudo(False)
        accessible = Domain("bill_attachment_id", "=", False)
        moves = actor.env["account.move"]
        attachments = actor.env["ir.attachment"]
        if moves.has_access("read") and attachments.has_access("read"):
            move_query = moves._search([
                ("move_type", "in", ["in_invoice", "in_refund"]),
                ("company_id", "in", actor.env.companies.ids),
            ])
            attachment_query = attachments._search([
                ("res_model", "=", "account.move"), ("type", "=", "binary"),
                ("res_field", "=", False),
            ])
            accessible |= Domain.AND([
                Domain("bill_move_id", "in", move_query),
                Domain("bill_attachment_id", "in", attachment_query),
            ])
        # Odoo 19 normalizes Boolean search operators to in/not in.
        return accessible if operator in ("in", "=") else ~accessible

    def _compute_bill_source_permission(self):
        for item in self:
            try:
                item._check_bill_source_read()
                item.bill_source_permission = True
            except AccessError:
                item.bill_source_permission = False

    def check_access(self, operation):
        result = super().check_access(operation)
        self._check_bill_source_read()
        return result

    def _read_format(self, fnames, load="classic_read"):
        self._check_bill_source_read()
        return super()._read_format(fnames, load=load)

    @api.constrains("bill_attachment_id", "bill_move_id", "directory_id", "attachment_id")
    def _check_bill_reference(self):
        if any(item.attachment_id.res_model == "account.move" for item in self.sudo()):
            raise ValidationError(self.env._("Accounting originals cannot use native attachment links."))
        for item in self.sudo().filtered("bill_attachment_id"):
            source = item.bill_attachment_id
            move = self.env["account.move"].sudo().browse(source.res_id).exists()
            if (
                source.res_model != "account.move" or source.res_field
                or source.type != "binary" or not move
                or move.move_type not in ("in_invoice", "in_refund")
                or item.bill_move_id != move or item.attachment_id
                or item.directory_id != move.company_id.dms_bill_root_id
                or item.company_id != move.company_id
                or item.content_binary or item.content_file or item.image_1920
                or item.access_token
            ):
                raise ValidationError(self.env._("Invalid vendor bill document reference."))

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("bill_attachment_id") or vals.get("bill_move_id") for vals in vals_list):
            raise UserError(self.env._("Bill document references are created automatically from originals."))
        # Explicit False values prevent forged context default_* provenance.
        vals_list = [dict(vals, bill_attachment_id=False, bill_move_id=False) for vals in vals_list]
        return super().create(vals_list)

    @api.model
    def _create_bill_reference(self, source, root):
        # Private server method; RPC/context values never authorize provenance.
        source.ensure_one()
        source.check_access("read")
        move = self.env["account.move"].browse(source.res_id)
        move.check_access("read")
        safe_name = (source.name or "attachment").replace("/", "_").replace("\\", "_")
        vals = {
            "name": f"{source.id} - {safe_name}", "directory_id": root.id,
            "attachment_id": False, "bill_attachment_id": source.id,
            "bill_move_id": move.id, "size": source.file_size,
            "checksum": source.checksum,
        }
        return super(DmsFile, self.sudo()).create([vals])

    def write(self, vals):
        protected = {
            "bill_attachment_id", "bill_move_id", "attachment_id", "directory_id",
            "storage_id", "res_model", "res_id", "name", "content", "content_binary",
            "content_file", "image_1920", "image_1024", "image_512", "image_256",
            "image_128", "access_token", "checksum", "size", "mimetype", "extension",
        }
        if (set(vals) & protected) and self.sudo().filtered("bill_attachment_id"):
            raise UserError(self.env._("Original bill document content and association are protected."))
        if set(vals) & {"bill_attachment_id", "bill_move_id"}:
            raise UserError(self.env._("Bill document references cannot be reassigned."))
        return super().write(vals)

    def _refresh_bill_metadata(self):
        for item in self.sudo().filtered("bill_attachment_id"):
            source = item.bill_attachment_id
            super(DmsFile, item).write({"size": source.file_size, "checksum": source.checksum})
            item.invalidate_recordset(["content", "mimetype", "extension"])
            item.modified(["bill_attachment_id"])

    def copy_data(self, default=None):
        if self.sudo().filtered("bill_attachment_id"):
            raise UserError(self.env._("Original bill document references cannot be copied."))
        return super().copy_data(default)

    @api.depends("content_binary", "content_file", "attachment_id", "bill_attachment_id", "bill_attachment_id.datas")
    def _compute_content(self):
        linked = self.filtered("bill_attachment_id")
        super(DmsFile, self - linked)._compute_content()
        for item in linked:
            item._check_bill_source_read()
            item.content = item.bill_attachment_id.with_env(self.sudo(False).env).datas

    @api.depends("content", "bill_attachment_id", "bill_attachment_id.mimetype")
    def _compute_mimetype(self):
        linked = self.filtered("bill_attachment_id")
        super(DmsFile, self - linked)._compute_mimetype()
        for item in linked:
            item.mimetype = item.bill_attachment_id.mimetype

    @api.depends("name", "mimetype", "content", "bill_attachment_id")
    def _compute_extension(self):
        linked = self.filtered("bill_attachment_id")
        super(DmsFile, self - linked)._compute_extension()
        for item in linked:
            item.extension = file.guess_extension(item.name, item.mimetype, False)

    @api.depends("mimetype", "content", "bill_attachment_id")
    def _compute_image_1920(self):
        linked = self.filtered("bill_attachment_id")
        super(DmsFile, self - linked)._compute_image_1920()
        for item in linked:
            item.image_1920 = False

    def _inverse_content(self):
        if self.sudo().filtered("bill_attachment_id"):
            raise UserError(self.env._("Original bill documents are read only in Documents."))
        return super()._inverse_content()

    @api.constrains("size")
    def _check_size(self):
        # An index is not a new upload: preserve the original accounting policy.
        return super(DmsFile, self.filtered(lambda item: not item.bill_attachment_id))._check_size()

    @api.constrains("extension")
    def _check_extension(self):
        return super(DmsFile, self.filtered(lambda item: not item.bill_attachment_id))._check_extension()

    def action_migrate(self, should_logging=True):
        if self.sudo().filtered("bill_attachment_id"):
            raise UserError(self.env._("Original bill document references cannot be migrated."))
        return super().action_migrate(should_logging=should_logging)

    @api.depends("storage_id", "storage_id.save_type", "bill_attachment_id")
    def _compute_migration(self):
        linked = self.filtered("bill_attachment_id")
        super(DmsFile, self - linked)._compute_migration()
        for item in linked:
            item.migration = self.env._("Original attachment reference")
            item.require_migration = False

    def check_access_token(self, access_token=False):
        if self.sudo().filtered("bill_attachment_id"):
            return False
        return super().check_access_token(access_token)

    def _portal_ensure_token(self):
        if self.sudo().filtered("bill_attachment_id"):
            raise UserError(self.env._("Vendor bill documents cannot be shared with public tokens."))
        return super()._portal_ensure_token()

    def _can_return_content(self, field_name=None, access_token=None):
        if self.sudo().filtered("bill_attachment_id"):
            if access_token:
                return False
            self.sudo(False).check_access("read")
        return super()._can_return_content(field_name=field_name, access_token=access_token)
