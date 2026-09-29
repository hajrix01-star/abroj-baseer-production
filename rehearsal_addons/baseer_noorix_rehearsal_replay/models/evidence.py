"""Append-only runtime evidence for the isolated 18084 Noorix rehearsal.

The module deliberately has no menu or access-control entry.  Its records are
created only by a sudo writer using the explicit context key below.  It is not
part of the production candidate.
"""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


WRITER_CONTEXT = "baseer_noorix_rehearsal_writer"


class NoorixRehearsalEvidence(models.AbstractModel):
    _name = "baseer.noorix.rehearsal.evidence"
    _description = "Noorix rehearsal replay evidence guard"
    _abstract = True

    def _writer_allowed(self):
        return self.env.su and self.env.context.get(WRITER_CONTEXT) is True

    @api.model_create_multi
    def create(self, vals_list):
        if not self._writer_allowed():
            raise AccessError(_("Noorix rehearsal evidence is writer-only."))
        return super().create(vals_list)

    def write(self, vals):
        if not self._writer_allowed():
            raise AccessError(_("Noorix rehearsal evidence is writer-only."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_("Noorix rehearsal evidence is append-only."))


class NoorixRehearsalRun(NoorixRehearsalEvidence):
    _name = "baseer.noorix.rehearsal.run"
    _description = "Noorix rehearsal replay run"
    _order = "id desc"
    _abstract = False
    _auto = True
    _log_access = True

    run_key = fields.Char(required=True, readonly=True, index=True)
    scope = fields.Selection([
        ("suppliers_global", "Suppliers and tags"),
        ("supplier_consolidation", "Supplier consolidation"),
        ("master_company", "Company master"),
        ("product_company", "Product master"),
        ("vault_company", "Liquidity master"),
        ("purchase_month", "Purchase month"),
        ("sales_month", "Sales month"),
        ("payroll_month", "Payroll month"),
    ], required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True, index=True)
    manifest_sha256 = fields.Char(required=True, readonly=True, index=True)
    state = fields.Selection([
        ("planned", "Planned"), ("committed", "Committed"),
        ("reconciled", "Reconciled"), ("failed", "Failed"),
    ], required=True, readonly=True, default="planned")
    result_json = fields.Text(readonly=True)

    _run_key_unique = models.Constraint(
        "UNIQUE(run_key)", "A Noorix rehearsal run key may be used only once."
    )

    def write(self, vals):
        immutable = {"run_key", "scope", "source_archive_sha256", "manifest_sha256"}
        if immutable.intersection(vals):
            raise UserError(_("Noorix rehearsal run identity is write-once."))
        return super().write(vals)


class NoorixRehearsalSourceMap(NoorixRehearsalEvidence):
    _name = "baseer.noorix.rehearsal.source.map"
    _description = "Noorix rehearsal source-to-target mapping"
    _order = "id"
    _abstract = False
    _auto = True
    _log_access = True

    scope = fields.Char(required=True, readonly=True, index=True)
    source_identity = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    target_model = fields.Char(required=True, readonly=True)
    target_res_id = fields.Integer(required=True, readonly=True, index=True)
    run_id = fields.Many2one(
        "baseer.noorix.rehearsal.run", required=True, readonly=True, ondelete="restrict", index=True
    )

    _source_scope_unique = models.Constraint(
        "UNIQUE(scope, source_identity)", "Each Noorix source identity may map only once per scope."
    )

    def write(self, vals):
        raise UserError(_("Noorix rehearsal source mappings are write-once."))
