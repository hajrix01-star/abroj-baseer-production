import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../src/overrides/models/pos_order.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "")
    .replace(/^export /gm, "");

// Minimal luxon stand-in: records the zone/locale/format the module asks for.
const dateCalls = [];
class FakeDateTime {
    constructor(iso) { this.iso = iso; }
    static isDateTime(value) { return value instanceof FakeDateTime; }
    static fromISO(iso) { return new FakeDateTime(iso); }
    setZone(zone) { dateCalls.push(["zone", zone]); return this; }
    reconfigure(options) { dateCalls.push(["reconfigure", options]); return this; }
    toFormat(format) { dateCalls.push(["format", format]); return "2026-11-27T14:04:22"; }
}

const calls = [];
class PosOrder {
    generateQrcode() { calls.push("native"); return "signed-qr"; }
    isInvoiceMandatoryForSA() { return true; }
}
const patch = (target, extension) => {
    Object.setPrototypeOf(extension, Object.create(Object.getPrototypeOf(target), Object.getOwnPropertyDescriptors(target)));
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
};
const context = {
    PosOrder, patch, TextEncoder, btoa, luxon: { DateTime: FakeDateTime },
    renderQRCodeDataURL: (value, width) => { calls.push([value, width]); return "phase1-qr"; },
};
runInNewContext(source, context);

function decodeTlv(base64) {
    const bytes = Buffer.from(base64, "base64");
    const out = {};
    for (let i = 0; i < bytes.length;) {
        const tag = bytes[i], length = bytes[i + 1];
        out[tag] = bytes.subarray(i + 2, i + 2 + length).toString("utf8");
        i += 2 + length;
    }
    return out;
}

const order = new PosOrder();
Object.assign(order, {
    config_id: { baseer_zatca_phase2_enabled: false },
    raw: { account_move: false }, to_invoice: false, l10n_sa_invoice_edi_state: false, finalized: true,
    company: { name: "شركة أرز | ARZ", vat: "312765667200003" },
    date_order: new FakeDateTime("2026-11-27T11:04:22Z"), priceIncl: 25, amountTaxes: 3.2609,
    isSACompany: () => true, isSettlement: () => false,
});

// Phase 2 off, finalized, no invoice: Phase 1 TLV matching Odoo's invoice QR.
assert.equal(order.generateQrcode(), "phase1-qr");
assert.equal(calls.length, 1);
assert.equal(calls[0][1], 200);
assert.deepEqual(decodeTlv(calls[0][0]), {
    1: "شركة أرز | ARZ", 2: "312765667200003", 3: "2026-11-27T14:04:22", 4: "25.00", 5: "3.26",
});
assert.deepEqual(JSON.parse(JSON.stringify(dateCalls)), [
    ["zone", "Asia/Riyadh"],
    ["reconfigure", { locale: "en-US", numberingSystem: "latn", outputCalendar: "gregory" }],
    ["format", "yyyy-MM-dd'T'HH:mm:ss"],
]);

// Refund: absolute amounts, as Odoo's invoice QR does for credit notes.
calls.length = 0;
order.priceIncl = -25; order.amountTaxes = -3.26;
order.generateQrcode();
assert.deepEqual(decodeTlv(calls[0][0])[4], "25.00");
assert.deepEqual(decodeTlv(calls[0][0])[5], "3.26");
order.priceIncl = 25; order.amountTaxes = 3.26;

// Offline / not yet synced: invoice fields are still unset, QR still printed.
calls.length = 0;
order.raw = {}; order.l10n_sa_invoice_edi_state = undefined;
assert.equal(order.generateQrcode(), "phase1-qr");
order.raw = { account_move: false }; order.l10n_sa_invoice_edi_state = false;

// Draft / pro-forma bill: no tax QR.
calls.length = 0;
order.finalized = false;
assert.equal(order.generateQrcode(), false);
order.finalized = true;

// Phase 2 enabled: native e-invoice QR only.
calls.length = 0;
order.config_id.baseer_zatca_phase2_enabled = true;
assert.equal(order.generateQrcode(), "signed-qr");
assert.deepEqual(JSON.parse(JSON.stringify(calls)), ["native"]);
order.config_id.baseer_zatca_phase2_enabled = false;

// An existing e-invoice QR always wins.
calls.length = 0;
order.l10n_sa_invoice_qr_code_str = "signed";
assert.equal(order.generateQrcode(), "signed-qr");
assert.deepEqual(JSON.parse(JSON.stringify(calls)), ["native"]);
delete order.l10n_sa_invoice_qr_code_str;

// Never replace a requested, linked or pending invoice with Phase 1 data.
calls.length = 0;
order.raw.account_move = 1;
assert.equal(order.generateQrcode(), false);
order.raw.account_move = false;
order.to_invoice = true;
assert.equal(order.generateQrcode(), false);
order.to_invoice = false;
order.l10n_sa_invoice_edi_state = "to_send";
assert.equal(order.generateQrcode(), false);
order.l10n_sa_invoice_edi_state = false;
order.isSettlement = () => true;
assert.equal(order.generateQrcode(), false);
order.isSettlement = () => false;
order.company.vat = "";
assert.equal(order.generateQrcode(), false);
assert.deepEqual(calls, []);
order.company.vat = "312765667200003";
order.isSACompany = () => false;
assert.equal(order.generateQrcode(), "signed-qr");
console.log("phase1_qr tests passed");
