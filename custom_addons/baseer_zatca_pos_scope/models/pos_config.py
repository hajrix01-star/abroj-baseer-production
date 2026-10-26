from odoo import _, fields, models
from odoo.addons.l10n_sa_edi_pos.models.pos_config import PosConfig as L10nSaEdiPosConfig
from odoo.exceptions import UserError


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_zatca_phase2_enabled = fields.Boolean(
        string='Enable ZATCA Phase 2 POS invoicing',
        help='Require invoices and ZATCA reporting for this POS only.',
        default=False,
    )

    def _load_pos_data_fields(self, config):
        return [*super()._load_pos_data_fields(config), 'baseer_zatca_phase2_enabled']

    def open_ui(self):
        """Keep Odoo's ZATCA onboarding gate scoped to opted-in POS only.

        ``l10n_sa_edi_pos`` checks an invoice journal's EDI formats whenever a
        Saudi POS is opened. A journal can be shared by several POS
        configurations, so changing its EDI formats here would silently alter
        accounting behavior for another cashier. Instead, an opted-out POS
        skips only that localization gate; every other POS opening check keeps
        running through the regular MRO.
        """
        enabled_configs = self.filtered('baseer_zatca_phase2_enabled')
        disabled_configs = self - enabled_configs

        result = False
        if enabled_configs:
            # Preserve Odoo's native certificate/journal readiness guard.
            result = super(PosConfig, enabled_configs).open_ui()
        if disabled_configs:
            # Deliberately skip only l10n_sa_edi_pos.open_ui(). Its direct
            # parent retains the normal Saudi-company and POS session checks.
            result = super(L10nSaEdiPosConfig, disabled_configs).open_ui()
        return result


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        if any(not order.config_id.baseer_zatca_phase2_enabled for order in self):
            raise UserError(_("ZATCA POS invoicing is not enabled for this point of sale."))
        return super()._generate_pos_order_invoice()
