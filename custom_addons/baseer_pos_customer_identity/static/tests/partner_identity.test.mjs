import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/app/partner_identity.js", import.meta.url), "utf8");
const lineTemplate = readFileSync(new URL("../src/app/partner_identity_line.xml", import.meta.url), "utf8");

assert.match(source, /baseerCustomerCategory = "individual"/);
assert.match(source, /baseer_pos_phone_key/);
assert.match(source, /exactMobileMatches\.length \|\| partnerCategory/);
assert.match(source, /!partner\.employee/);
assert.match(source, /is_company/);
assert.match(source, /PosStore/);
assert.match(source, /baseer_pos_config_id: this\.config\.id/);
assert.match(lineTemplate, /props\.partner\.city/);
assert.match(lineTemplate, /partner-line-adress/);
assert.match(lineTemplate, /email-field/);
assert.doesNotMatch(lineTemplate, /<xpath expr="\/\/t\[/);
const filterTemplate = readFileSync(new URL("../src/app/partner_identity.xml", import.meta.url), "utf8");
assert.doesNotMatch(filterTemplate, />Employees</);
assert.match(filterTemplate, /this\.setBaseerCustomerCategory\('individual'\)/);
assert.match(filterTemplate, /this\.setBaseerCustomerCategory\('company'\)/);
