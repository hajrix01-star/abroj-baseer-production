/** @odoo-module */

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";
import { renderQRCodeDataURL } from "@l10n_sa_pos/app/utils/qr";

const { DateTime } = luxon;

const QR_STATES = ["paid", "done", "invoiced"];

function tlvField(tag, value) {
    const bytes = Array.from(new TextEncoder().encode(value));
    // TLV lengths are one byte, as in Odoo's own invoice QR.
    if (bytes.length > 255) {
        return null;
    }
    return [tag, bytes.length, ...bytes];
}

/**
 * ZATCA Phase 1 TLV payload, kept identical to Odoo's own invoice QR
 * (l10n_sa account.move._compute_qr_code_str): Riyadh time in ISO 8601
 * (yyyy-MM-ddTHH:mm:ss) with Latin digits, and absolute amounts rounded to
 * the currency with two decimals (float_repr(abs(amount), 2)). Odoo's POS
 * helper formats the date in the cashier's language, which gives
 * Arabic-Indic digits and MM/dd/yyyy on an Arabic POS.
 * Returns false when a field cannot be encoded: never print a broken QR.
 */
export function baseerPhase1QrPayload(name, vat, dateOrder, total, tax, round = (value) => value) {
    if (!DateTime.isDateTime(dateOrder) || !dateOrder.isValid) {
        return false;
    }
    const timestamp = dateOrder
        .setZone("Asia/Riyadh")
        .reconfigure({ locale: "en-US", numberingSystem: "latn", outputCalendar: "gregory" })
        .toFormat("yyyy-MM-dd'T'HH:mm:ss");
    const amount = (value) => Math.abs(round(value)).toFixed(2);
    if (![total, tax].every(Number.isFinite) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(timestamp)) {
        return false;
    }
    const fields = [
        tlvField(1, name),
        tlvField(2, vat),
        tlvField(3, timestamp),
        tlvField(4, amount(total)),
        tlvField(5, amount(tax)),
    ];
    if (fields.some((field) => !field)) {
        return false;
    }
    let binary = "";
    for (const byte of fields.flat()) {
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
        // existing invoice QR, and never put a tax QR on a draft/pro-forma
        // or a cancelled order.
        if (!QR_STATES.includes(this.state) || this.raw?.account_move || this.to_invoice
                || this.l10n_sa_invoice_edi_state || this.isSettlement()
                || !this.company?.name || !this.company?.vat || !this.date_order) {
            return false;
        }
        const currency = this.currency;
        const qrValues = baseerPhase1QrPayload(
            this.company.name, this.company.vat, this.date_order, this.priceIncl, this.amountTaxes,
            currency?.round ? (value) => currency.round(value) : undefined
        );
        return qrValues ? renderQRCodeDataURL(qrValues, 200) : false;
    },
});
