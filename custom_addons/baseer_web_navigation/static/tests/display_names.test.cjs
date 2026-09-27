// Run with node; exercises actual patch getters against small native-method stubs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "../src/display_names.js"), "utf8")
    .replace(/^import .*;\r?\n/gm, "").replace(/export /g, "");
const user = { lang: "ar-001" };
class CharField { get formattedValue() { return this.props.record.data[this.props.name]; } }
class Many2One { get displayName() { return this.props.value.display_name; } }
class ListRenderer {
    getFormattedValue(column, record) { return record.data[column.name]; }
    canUseFormatter(column) { return !column.widget; }
}
class SwitchCompanyMenu {}
class SwitchCompanyItem {}
function patch(proto, extension) {
    const original = Object.create(Object.getPrototypeOf(proto), Object.getOwnPropertyDescriptors(proto));
    Object.setPrototypeOf(extension, original);
    Object.defineProperties(proto, Object.getOwnPropertyDescriptors(extension));
}
const context = vm.createContext({ user, patch, CharField, Many2One, ListRenderer, SwitchCompanyMenu, SwitchCompanyItem });
vm.runInContext(source, context);
const { reportName, catalogName, fieldNameModel } = context;
const label = "نقدي | Cash";
assert.equal(reportName(label, "ar_001"), "نقدي");
assert.equal(reportName(label, "en-US"), "Cash");
assert.equal(reportName("Cash | نقدي", "ar"), "نقدي");
for (const value of [false, null, "", "Single", "Cash | Card", "عربي | نص", "عربي |", "عربي | English | Other"]) {
    assert.equal(reportName(value, "ar"), value);
}
assert.equal(catalogName("أصل | Parent / فرع | Child", "product.category", "en"), "Parent / Child");
assert.equal(catalogName("أصل | Parent / فرع | Child", "res.partner", "en"), "أصل | Parent / فرع | Child");
const record = { resModel: "res.company", fields: { name: { type: "char" } }, data: { name: label } };
const field = new CharField();
field.props = { name: "name", record, readonly: true };
assert.equal(field.formattedValue, "نقدي");
field.props.readonly = false;
assert.equal(field.formattedValue, label);
field.props.readonly = true;
record.resModel = "account.move";
assert.equal(field.formattedValue, label);
record.resModel = "res.company";
const m2o = new Many2One();
m2o.props = { relation: "pos.payment.method", value: { display_name: label }, readonly: true };
assert.equal(m2o.displayName, "نقدي");
m2o.props.readonly = false;
assert.equal(m2o.displayName, label);
m2o.props.readonly = true;
m2o.props.relation = "account.move";
assert.equal(m2o.displayName, label);
const list = new ListRenderer();
const column = { name: "name", options: {} };
assert.equal(list.getFormattedValue(column, record), "نقدي");
record.isInEdition = true;
assert.equal(list.getFormattedValue(column, record), label);
record.isInEdition = false;
column.widget = "char";
assert.equal(list.getFormattedValue(column, record), label);
delete column.widget;
column.options.enable_formatting = false;
assert.equal(list.getFormattedValue(column, record), label);
assert.equal(record.data.name, label);
assert.equal(fieldNameModel({ fields: { description: { type: "char" } }, resModel: "res.company" }, "description"), undefined);
assert.equal(new SwitchCompanyMenu().baseerCompanyName(label), "نقدي");
user.lang = "en-US";
assert.equal(new SwitchCompanyItem().baseerCompanyName(label), "Cash");
console.log("PASS display label parsing, catalog scope, readonly guards and source preservation");
