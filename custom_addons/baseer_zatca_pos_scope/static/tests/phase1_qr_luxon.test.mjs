// Runs the Phase 1 payload against Odoo's own vendored luxon (CI copies it to
// tmp/odoo_luxon.js from the tested Odoo image), so the timezone conversion
// and Latin digits are proven with the real library, not a stand-in.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const luxonPath = new URL("../../../../tmp/odoo_luxon.js", import.meta.url);
if (!existsSync(luxonPath)) {
    if (process.env.CI) {
        throw new Error("tmp/odoo_luxon.js is missing: extract it from the Odoo image first");
    }
    console.log("SKIP: tmp/odoo_luxon.js not found (CI extracts it)");
    process.exit(0);
}
const context = { TextEncoder, btoa, Intl, Date, Math, Number, Array, String, RegExp, Object, Symbol, Error, console };
runInNewContext(readFileSync(luxonPath, "utf8"), context);
const source = readFileSync(new URL("../src/overrides/models/pos_order.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "")
    .replace(/^export /gm, "")
    .replace(/^patch\(PosOrder\.prototype, \{[\s\S]*$/m, "this.baseerPhase1QrPayload = baseerPhase1QrPayload;");
runInNewContext(source, context);
const { DateTime, Settings } = context.luxon;

function decodeTlv(base64) {
    const bytes = Buffer.from(base64, "base64");
    const out = {};
    for (let i = 0; i < bytes.length;) {
        out[bytes[i]] = bytes.subarray(i + 2, i + 2 + bytes[i + 1]).toString("utf8");
        i += 2 + bytes[i + 1];
    }
    return out;
}

// An Arabic POS session: default locale ar with Arabic-Indic digits.
Settings.defaultLocale = "ar-SA";
Settings.defaultNumberingSystem = "arab";
const date = DateTime.fromISO("2026-11-27T11:04:22Z");
assert.match(date.toFormat("HH"), /[٠-٩]/, "the session really formats Arabic digits by default");

const payload = context.baseerPhase1QrPayload("شركة مطعم أرز لتقديم الوجبات | ARZ", "312765667200003", date, -25, -3.26);
assert.deepEqual(decodeTlv(payload), {
    1: "شركة مطعم أرز لتقديم الوجبات | ARZ",
    2: "312765667200003",
    3: "2026-11-27T14:04:22",
    4: "25.00",
    5: "3.26",
});
// Midnight crossing in Riyadh (UTC+3).
assert.equal(decodeTlv(context.baseerPhase1QrPayload("A", "3", DateTime.fromISO("2026-11-27T22:30:00Z"), 1, 0))[3],
    "2026-11-28T01:30:00");
assert.equal(context.baseerPhase1QrPayload("A", "3", DateTime.invalid("test"), 1, 0), false);
console.log("phase1_qr_luxon tests passed");
