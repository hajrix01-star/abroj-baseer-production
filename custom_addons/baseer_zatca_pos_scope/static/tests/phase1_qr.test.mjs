import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../src/overrides/models/pos_order.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "");
const calls = [];
class PosOrder {
    generateQrcode() { calls.push("native"); return "signed-qr"; }
    isInvoiceMandatoryForSA() { return true; }
}
const patch = (target, extension) => {
    Object.setPrototypeOf(extension, Object.create(Object.getPrototypeOf(target), Object.getOwnPropertyDescriptors(target)));
    Object.defineProperties(target, Object.getOwnPropertyDescriptors(extension));
};
runInNewContext(source, {
    PosOrder, patch,
    renderQRCodeDataURL: (value, width) => { calls.push([value, width]); return "phase1-qr"; },
});
const order = new PosOrder();
Object.assign(order, {
    config_id: { baseer_zatca_phase2_enabled: false },
    raw: { account_move: false }, to_invoice: false, l10n_sa_invoice_edi_state: false,
    company: { name: "QA", vat: "123" }, date_order: "2026-11-10", priceIncl: 11.5, amountTaxes: 1.5,
    isSACompany: () => true, isSettlement: () => false,
    compute_sa_qr_code: (...values) => { calls.push(values); return "encoded"; },
});
assert.equal(order.generateQrcode(), "phase1-qr");
assert.deepEqual(calls, [["QA", "123", "2026-11-10", 11.5, 1.5], ["encoded", 200]]);
calls.length = 0;
order.config_id.baseer_zatca_phase2_enabled = true;
assert.equal(order.generateQrcode(), "signed-qr");
assert.deepEqual(calls, ["native"]);
calls.length = 0;
order.config_id.baseer_zatca_phase2_enabled = false;
calls.length = 0;
order.l10n_sa_invoice_qr_code_str = "signed";
assert.equal(order.generateQrcode(), "signed-qr");
assert.deepEqual(calls, ["native"]);
delete order.l10n_sa_invoice_qr_code_str;
calls.length = 0;
// Odoo's relation getter returns undefined both for false and for an
// unloaded related record. The raw ID distinguishes these cases.
Object.defineProperty(order, "account_move", { get: () => undefined });
order.raw.account_move = 1;
assert.equal(order.generateQrcode(), false);
order.raw.account_move = false;
order.to_invoice = true;
assert.equal(order.generateQrcode(), false);
order.to_invoice = false;
order.l10n_sa_invoice_edi_state = "to_send";
assert.equal(order.generateQrcode(), false);
order.l10n_sa_invoice_edi_state = false;
delete order.raw.account_move;
assert.equal(order.generateQrcode(), false);
order.raw.account_move = false;
order.isSettlement = () => true;
assert.equal(order.generateQrcode(), false);
assert.deepEqual(calls, []);
order.isSettlement = () => false;
order.company.vat = "";
assert.equal(order.generateQrcode(), false);
assert.deepEqual(calls, []);
order.isSACompany = () => false;
assert.equal(order.generateQrcode(), "signed-qr");
