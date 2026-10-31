import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/default_customer.js", import.meta.url), "utf8");

assert.match(source, /getDefaultPartnerId\(\)/);
assert.match(source, /this\.config\.baseer_default_customer_id/);
assert.match(source, /super\.getDefaultPartnerId\(\.\.\.arguments\)/);
assert.doesNotMatch(source, /canBeValidated|validateOrder|setPartner\(/);
