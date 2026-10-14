from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def _dms_managed_models(self):
        return {"account.move"}

    def _dms_source_record(self):
        self.ensure_one()
        if self.res_model != "account.move" or not self.res_id or self.res_field or self.type != "binary":
            return False
        move = self.env["account.move"].sudo().browse(self.res_id).exists()
        return move if move and move.move_type in ("in_invoice", "in_refund") else False

    def _dms_reference_destination(self, record, create=False):
        return record.company_id.dms_bill_root_id

    def _dms_reference_matches(self, link, record):
        return link.bill_move_id == record

    def _dms_operations(self):
        # Never route accounting attachments through native unscoped indexing.
        others = self.filtered(lambda source: source.res_model not in self._dms_managed_models())
        result = super(IrAttachment, others)._dms_operations()
        return result

    def _sync_dms_bill_links(self):
        # Acquire every source lock in order before any destination/company lock.
        # This avoids lock inversion when overlapping batches create HR folders.
        if self:
            self.env.cr.execute(
                "SELECT id FROM ir_attachment WHERE id = ANY(%s) ORDER BY id FOR UPDATE", [self.ids]
            )
        for source in self.sorted("id"):
            # Lock the authoritative source: simultaneous retries cannot create
            # two references; a UNIQUE constraint is the final database guard.
            source.invalidate_recordset()
            links = self.env["dms.file"].sudo().with_context(active_test=False).search([
                ("bill_attachment_id", "=", source.id)
            ])
            record = source._dms_source_record()
            root = source._dms_reference_destination(record, create=True) if record else self.env["dms.directory"]
            eligible = bool(record and root)
            if links and (not eligible or not source._dms_reference_matches(links, record) or links.directory_id != root):
                links.unlink()
                links = self.env["dms.file"]
            if eligible:
                if links:
                    links._refresh_bill_metadata()
                else:
                    self.env["dms.file"]._create_bill_reference(source, root)

    @api.model_create_multi
    def create(self, vals_list):
        sources = super().create(vals_list)
        sources.filtered(lambda source: source.res_model in self._dms_managed_models())._sync_dms_bill_links()
        return sources

    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {
            "res_model", "res_id", "res_field", "type", "datas", "raw", "db_datas",
            "store_fname", "mimetype", "name", "checksum", "file_size",
        }:
            self._sync_dms_bill_links()
        return result
