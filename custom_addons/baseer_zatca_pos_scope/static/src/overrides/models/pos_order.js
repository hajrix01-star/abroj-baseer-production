/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { renderQRCodeDataURL } from "@l10n_sa_pos/app/utils/qr";

patch(PosOrder.prototype, {
    isInvoiceMandatoryForSA() {
        return super.isInvoiceMandatoryForSA(...arguments) && this.config_id.baseer_zatca_phase2_enabled;
    },
    generateQrcode() {
        // The EDI module replaces the Phase 1 generator globally, including
        // POS configurations where this module disables Phase 2 invoicing.
        if (this.config_id?.baseer_zatca_phase2_enabled !== false || !this.isSACompany()
                || this.l10n_sa_invoice_qr_code_str) {
            return super.generateQrcode(...arguments);
        }
        // Never replace a missing or unfinished invoice QR with Phase 1 data.
        if (this.raw?.account_move === undefined || this.to_invoice === undefined
                || this.l10n_sa_invoice_edi_state === undefined
                || this.raw.account_move || this.to_invoice || this.l10n_sa_invoice_edi_state || this.isSettlement()
                || !this.company?.name || !this.company?.vat || !this.date_order) {
            return false;
        }
        const qrValues = this.compute_sa_qr_code(
            this.company.name, this.company.vat, this.date_order, this.priceIncl, this.amountTaxes
        );
        return renderQRCodeDataURL(qrValues, 200);
    },
});
