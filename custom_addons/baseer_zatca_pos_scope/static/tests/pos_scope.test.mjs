import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(
    new URL("../src/overrides/models/pos_order.js", import.meta.url),
    "utf8"
);

assert.match(source, /super\.isInvoiceMandatoryForSA\(\.\.\.arguments\)/);
assert.match(source, /this\.config_id\.baseer_zatca_phase2_enabled/);

const statusSource = readFileSync(new URL("../src/overrides/pos_store.js", import.meta.url), "utf8");
assert.match(statusSource, /baseer_zatca_phase2_status/);
assert.match(statusSource, /status\.pending \|\| status\.error/);
assert.match(statusSource, /super\.closeSession\(\.\.\.arguments\)/);
