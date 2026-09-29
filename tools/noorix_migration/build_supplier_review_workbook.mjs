import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const payloadPath = process.argv[2];
const outputPath = process.argv[3];
if (!payloadPath || !outputPath) throw new Error("Usage: node build_supplier_review_workbook.mjs <payload.json> <output.xlsx>");

const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
const target = JSON.parse(await fs.readFile(path.join(path.dirname(payloadPath), "target.json"), "utf8"));
const categoriesByKey = new Map(payload.canonical_categories.map((row) => [row.canonical_key, row]));
const targetPartnersById = new Map(target.partners.map((row) => [row.id, row]));
const targetTagsById = new Map(target.tags.map((row) => [row.id, row]));
const targetTagName = (row) => {
  const value = row?.name;
  if (value && typeof value === "object") return value.ar_001 ?? value.ar ?? value.en_US ?? "";
  return value ?? "";
};
const membershipsByPartner = new Map();
for (const membership of payload.memberships) {
  const existing = membershipsByPartner.get(membership.canonical_partner_key) ?? [];
  existing.push(categoriesByKey.get(membership.canonical_category_key)?.name ?? "");
  membershipsByPartner.set(membership.canonical_partner_key, existing);
}

const actionLabel = (decision) => ({
  existing_global_vat: "ربط بجهة موجودة",
  automatic_valid_vat: "إنشاء في QA",
  kept_separate: "إنشاء في QA",
  cash_anonymous: "إنشاء مورد نقدي غير مسمى في QA",
  blocked_conflict: "موقوف",
}[decision] ?? decision);
const tagActionLabel = (decision) => ({
  existing_exact_name: "استخدام وسم موجود",
  existing_approved_semantic: "استخدام وسم أودو مناسب",
  create_new: "إنشاء في QA",
  ambiguous_existing_name: "إنشاء منفصل مع ملاحظة",
}[decision] ?? decision);
const font = { name: "Arial", size: 10, color: "#1F2937" };
const headerFormat = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
const titleFormat = { font: { name: "Arial", size: 16, bold: true, color: "#1F2937" } };
const noteFormat = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };

const workbook = Workbook.create();
const overview = workbook.worksheets.add("ملخص");
const suppliers = workbook.worksheets.add("الموردون");
const tags = workbook.worksheets.add("فئات الموردين");
const mappings = workbook.worksheets.add("خرائط المصدر");

for (const sheet of [overview, suppliers, tags, mappings]) {
  sheet.showGridLines = false;
  sheet.getRange("A:Z").format.font = font;
}

overview.getRange("A1:G1").merge();
overview.getRange("A1").values = [["نوركس إلى بصير — جدول مراجعة الموردين"]];
overview.getRange("A1").format = titleFormat;
overview.getRange("A2:G2").merge();
overview.getRange("A2").values = [[`نطاق الموردين والفئات حتى ${payload.cutoff} — الأرشيف المرفق هو مصدر البيانات`]];
overview.getRange("A2").format = noteFormat;
overview.getRange("A4:B4").values = [["البند", "العدد"]];
overview.getRange("A4:B4").format = headerFormat;
const summaryRows = [
  ["سجلات الموردين من نوركس", payload.report.source_supplier_rows],
  ["الموردون الموحدون", payload.report.canonical_supplier_groups],
  ["ربط بجهات أودو موجودة", payload.report.existing_global_vat_groups],
  ["موردون جدد في QA", payload.report.new_supplier_groups],
  ["حالات محجوبة", payload.report.blocked_supplier_groups],
  ["معرفات فئات المصدر", payload.report.source_category_ids],
  ["فئات مورد موحدة", payload.report.canonical_category_tags],
  ["فئات أودو معاد استخدامها", payload.report.reused_category_tags],
  ["فئات جديدة في QA", payload.report.new_category_tags],
  ["روابط مورد/فئة", payload.report.canonical_supplier_tag_memberships],
];
overview.getRange(`A5:B${4 + summaryRows.length}`).values = summaryRows;
overview.getRange(`B5:B${4 + summaryRows.length}`).format.numberFormat = "#,##0";
overview.getRange(`A4:B${4 + summaryRows.length}`).format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
overview.getRange("A15:G15").merge();
overview.getRange("A15").values = [["قاعدة المطابقة: يُعاد استخدام المورد فقط عند تطابق رقم ضريبي سعودي صحيح مع جهة عالمية واحدة في أودو. تشابه الاسم أو الهاتف لا يدمج ولا يغيّر أي جهة."]];
overview.getRange("A15").format = noteFormat;
overview.getRange("A1:G15").format.wrapText = true;
overview.getRange("A:A").format.columnWidth = 34;
overview.getRange("B:B").format.columnWidth = 14;
overview.getRange("A1:G1").format.rowHeight = 28;

const supplierHeaders = [["المفتاح الموحد", "الإجراء", "اسم المورد", "الرقم الضريبي", "الهاتف", "نشط", "سجلات نوركس", "فئات المورد", "الجهة الحالية في أودو"]];
const supplierRows = payload.canonical_partners.map((row) => [
  row.canonical_key,
  actionLabel(row.decision),
  row.name,
  row.vat ?? "",
  row.phone ?? "",
  row.active ? "نعم" : "لا",
  row.source_ids.length,
  (membershipsByPartner.get(row.canonical_key) ?? []).sort().join("، "),
  row.target_partner_id ? (targetPartnersById.get(row.target_partner_id)?.name ?? String(row.target_partner_id)) : "",
]);
suppliers.getRange(`A1:I${supplierRows.length + 1}`).values = [...supplierHeaders, ...supplierRows];
suppliers.getRange("A1:I1").format = headerFormat;
suppliers.getRange(`A2:I${supplierRows.length + 1}`).format.wrapText = true;
suppliers.getRange(`D2:E${supplierRows.length + 1}`).format.numberFormat = "@";
suppliers.getRange(`G2:G${supplierRows.length + 1}`).format.numberFormat = "#,##0";
suppliers.tables.add(`A1:I${supplierRows.length + 1}`, true, "SupplierReviewTable").style = "TableStyleMedium2";
suppliers.freezePanes.freezeRows(1);
for (const [column, width] of [["A:A", 34], ["B:B", 20], ["C:C", 32], ["D:D", 20], ["E:E", 18], ["F:F", 10], ["G:G", 13], ["H:H", 40], ["I:I", 30]]) suppliers.getRange(column).format.columnWidth = width;

const tagHeaders = [["المفتاح الموحد", "الإجراء", "اسم الفئة", "معرفات المصدر", "أنواع المصدر", "الوسم الحالي في أودو"]];
const tagRows = payload.canonical_categories.map((row) => [
  row.canonical_key,
  tagActionLabel(row.decision),
  row.name,
  row.source_category_ids.length,
  row.source_types.join("، "),
  row.target_tag_id ? (targetTagName(targetTagsById.get(row.target_tag_id)) || String(row.target_tag_id)) : "",
]);
tags.getRange(`A1:F${tagRows.length + 1}`).values = [...tagHeaders, ...tagRows];
tags.getRange("A1:F1").format = headerFormat;
tags.getRange(`A2:F${tagRows.length + 1}`).format.wrapText = true;
tags.getRange(`D2:D${tagRows.length + 1}`).format.numberFormat = "#,##0";
tags.tables.add(`A1:F${tagRows.length + 1}`, true, "SupplierTagReviewTable").style = "TableStyleMedium2";
tags.freezePanes.freezeRows(1);
for (const [column, width] of [["A:A", 34], ["B:B", 26], ["C:C", 32], ["D:D", 16], ["E:E", 20], ["F:F", 18]]) tags.getRange(column).format.columnWidth = width;

const mappingHeaders = [["نظام المصدر", "المستأجر", "شركة نوركس", "معرف المورد", "المفتاح الموحد", "القرار", "جهة أودو الحالية"]];
const mappingRows = payload.supplier_maps.map((row) => [
  row.source_system,
  row.source_tenant_id,
  row.source_company_id,
  row.source_supplier_id,
  row.canonical_key,
  actionLabel(row.decision),
  row.target_partner_id ? (targetPartnersById.get(row.target_partner_id)?.name ?? String(row.target_partner_id)) : "",
]);
mappings.getRange(`A1:G${mappingRows.length + 1}`).values = [...mappingHeaders, ...mappingRows];
mappings.getRange("A1:G1").format = headerFormat;
mappings.getRange(`A2:G${mappingRows.length + 1}`).format.wrapText = false;
mappings.tables.add(`A1:G${mappingRows.length + 1}`, true, "SupplierSourceMapTable").style = "TableStyleMedium2";
mappings.freezePanes.freezeRows(1);
for (const [column, width] of [["A:A", 16], ["B:B", 30], ["C:C", 28], ["D:D", 28], ["E:E", 34], ["F:F", 22], ["G:G", 30]]) mappings.getRange(column).format.columnWidth = width;

const outputDir = path.dirname(outputPath);
await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

for (const range of ["ملخص!A1:B12", "الموردون!A1:I12", "فئات الموردين!A1:F12", "خرائط المصدر!A1:G12"]) {
  const inspection = await workbook.inspect({ kind: "table", range, include: "values,formulas", tableMaxRows: 12, tableMaxCols: 9 });
  console.log(inspection.ndjson);
}
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 50 }, summary: "formula error scan" });
console.log(errors.ndjson);
for (const [sheetName, range, suffix] of [
  ["ملخص", "A1:G16", "summary"],
  ["الموردون", "A1:I16", "suppliers"],
  ["فئات الموردين", "A1:F16", "categories"],
  ["خرائط المصدر", "A1:G16", "mappings"],
]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.5, format: "png" });
  await fs.writeFile(outputPath.replace(/\.xlsx$/i, `.${suffix}.png`), new Uint8Array(await preview.arrayBuffer()));
}
