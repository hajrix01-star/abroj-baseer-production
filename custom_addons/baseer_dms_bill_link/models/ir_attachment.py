from odoo import api, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _dms_operations(self):
        # Never route accounting attachments through native unscoped indexing.
        others = self.filtered(lambda source: source.res_model != "account.move")
        result = super(IrAttachment, others)._dms_operations()
        return result

    def _sync_dms_bill_links(self):
        for source in self.sorted("id"):
            # Lock the authoritative source: simultaneous retries cannot create
            # two references; a UNIQUE constraint is the final database guard.
            self.env.cr.execute("SELECT id FROM ir_attachment WHERE id = %s FOR UPDATE", [source.id])
            source.invalidate_recordset()
            links = self.env["dms.file"].sudo().with_context(active_test=False).search([
                ("bill_attachment_id", "=", source.id)
            ])
            move = self.env["account.move"].browse()
            if source.res_model == "account.move" and source.res_id:
                move = self.env["account.move"].sudo().browse(source.res_id).exists()
            root = move.company_id.dms_bill_root_id if move else self.env["dms.directory"]
            eligible = bool(
                move and root and move.move_type in ("in_invoice", "in_refund")
                and source.type == "binary" and not source.res_field
            )
            if links and (not eligible or links.bill_move_id != move or links.directory_id != root):
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
        sources.filtered(lambda source: source.res_model == "account.move")._sync_dms_bill_links()
        return sources

    def write(self, vals):
        result = super().write(vals)
        if set(vals) & {
            "res_model", "res_id", "res_field", "type", "datas", "raw", "db_datas",
            "store_fname", "mimetype", "name", "checksum", "file_size",
        }:
            self._sync_dms_bill_links()
        return result
