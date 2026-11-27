/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { renderQRCodeDataURL } from "@l10n_sa_pos/app/utils/qr";

const { DateTime } = luxon;

function tlvField(tag, value) {
    const bytes = Array.from(new TextEncoder().encode(value));
    return [tag, bytes.length, ...bytes];
}

/**
 * ZATCA Phase 1 TLV payload, kept identical to Odoo's own invoice QR
 * (l10n_sa account.move._compute_qr_code_str): Riyadh time in ISO 8601
 * (yyyy-MM-ddTHH:mm:ss) with Latin digits, and absolute amounts with two
 * decimals. Odoo's POS helper formats the date in the cashier's language,
 * which gives Arabic-Indic digits and MM/dd/yyyy on an Arabic POS.
 */
export function baseerPhase1QrPayload(name, vat, dateOrder, total, tax) {
    const date = DateTime.isDateTime(dateOrder) ? dateOrder : DateTime.fromISO(String(dateOrder), { zone: "utc" });
    const timestamp = date
        .setZone("Asia/Riyadh")
        .reconfigure({ locale: "en-US", numberingSystem: "latn", outputCalendar: "gregory" })
        .toFormat("yyyy-MM-dd'T'HH:mm:ss");
    const bytes = [
        ...tlvField(1, name),
        ...tlvField(2, vat),
        ...tlvField(3, timestamp),
        ...tlvField(4, Math.abs(total).toFixed(2)),
        ...tlvField(5, Math.abs(tax).toFixed(2)),
    ];
    let binary = "";
    for (const byte of bytes) {
        binary += String.fromCharCode(byte);
    }
    return btoa(binary);
}

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
        // Phase 2 is off here, so the server refuses to invoice this POS and
        // an order without an invoice request never receives an e-invoice QR.
        // That also holds before the first sync (offline print), where the
        // invoice fields are still unset. Never replace a requested or
        // existing invoice QR, and never put a tax QR on a draft/pro-forma.
        if (!this.finalized || this.raw?.account_move || this.to_invoice
                || this.l10n_sa_invoice_edi_state || this.isSettlement()
                || !this.company?.name || !this.company?.vat || !this.date_order) {
            return false;
        }
        const qrValues = baseerPhase1QrPayload(
            this.company.name, this.company.vat, this.date_order, this.priceIncl, this.amountTaxes
        );
        return renderQRCodeDataURL(qrValues, 200);
    },
});
