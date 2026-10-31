import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/default_customer.js", import.meta.url), "utf8");

assert.match(source, /getDefaultPartnerId\(\)/);
assert.match(source, /this\.config\.baseer_default_customer_id/);
assert.match(source, /super\.getDefaultPartnerId\(\.\.\.arguments\)/);
assert.match(source, /getEmptyOrder\(\)/);
assert.match(source, /super\.getEmptyOrder\(\.\.\.arguments\)/);
assert.match(source, /order\?\.isEmpty\(\)/);
assert.match(source, /!order\.partner_id/);
assert.match(source, /!order\.finalized/);
assert.match(source, /!order\.isSynced/);
assert.match(source, /order\.payment_ids\.length === 0/);
assert.match(source, /order\.setPartner\(partner\)/);
assert.doesNotMatch(source, /canBeValidated|validateOrder/);
