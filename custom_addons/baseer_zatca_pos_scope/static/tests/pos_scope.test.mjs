import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
    new URL("../src/overrides/models/pos_order.js", import.meta.url),
    "utf8"
);

assert.match(source, /super\.isInvoiceMandatoryForSA\(\.\.\.arguments\)/);
assert.match(source, /this\.config\.baseer_zatca_phase2_enabled/);
