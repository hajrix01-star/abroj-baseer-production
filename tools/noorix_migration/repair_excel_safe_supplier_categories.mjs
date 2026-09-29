import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

// Start from the review workbook before any validation was added.
const inputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_plan.xlsx";
const outputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_supplier_categories_excel_compatible.xlsx";
const currentOdooTags = [
  "مقدمو الخدمات",
  "مقدمو الكهرباء",
  "مقدمو المياه",
  "مقدمو الاتصالات والإنترنت",
  "الجهات الحكومية",
  "المنصات الحكومية",
];
const categoryNames = new Map([
  ["فواتير نقدية صغيرة", "موردون نقديون غير مسمين"], ["اتصالات", "مقدمو الاتصالات والإنترنت"], ["أثاث", "موردو أثاث"],
  ["أجهزة وإلكترونيات", "موردو أجهزة وإلكترونيات"], ["أصول ومعدات", "موردو أصول ومعدات"], ["إقامات وجوازات", "الجهات الحكومية"],
  ["أكياس", "موردو أكياس"], ["التأمينات الاجتماعية (GOSI)", "الجهات الحكومية"], ["إيجارات", "مؤجرو عقارات"],
  ["بضاعة تموينية", "موردو بضاعة تموينية"], ["بلاستيكات", "موردو بلاستيكات"], ["تأمين طبي", "مقدمو تأمين طبي"],
  ["تذاكر سفر الموظفين", "مقدمو خدمات سفر"], ["تسويق وهدايا", "مقدمو خدمات تسويق وهدايا"], ["تعبئة وتغليف", "موردو تعبئة وتغليف"],
  ["خامات", "موردو خامات"], ["خضار وفواكه", "موردو خضار وفواكه"], ["دجاج", "موردو دواجن"],
  ["رخصة بلدية", "الجهات الحكومية"], ["رخصة تجارية", "الجهات الحكومية"], ["رسوم إدارة حساب", "مقدمو خدمات مالية"],
  ["رسوم تطبيقات", "مزودو تطبيقات"], ["رسوم منصات حكومية", "المنصات الحكومية"], ["رواتب وأجور", "مقدمو خدمات عمالة ورواتب"],
  ["شحم", "موردو شحوم"], ["شيشة", "موردو شيشة"], ["صيانة آلات", "مقدمو صيانة آلات"], ["صيانة سيارات", "مقدمو صيانة سيارات"],
  ["صيانة وترميم", "مقدمو صيانة وترميم"], ["صيانة وتشغيل", "مقدمو صيانة وتشغيل"], ["ضرائب ورسوم أخرى", "الجهات الحكومية"],
  ["علب وأكواب", "موردو علب وأكواب"], ["غاز طبخ", "موردو غاز طبخ"], ["غازيات", "موردو مشروبات غازية"],
  ["غرامات", "الجهات الحكومية"], ["فحم", "موردو فحم"], ["قروض", "جهات تمويل"], ["قطع غيار", "موردو قطع غيار"],
  ["قهوة بن", "موردو قهوة وبن"], ["كهرباء", "مقدمو الكهرباء"], ["لحوم", "موردو لحوم"],
  ["مستلزمات تشغيل مطبخ", "موردو مستلزمات تشغيل مطبخ"], ["مشروبات", "موردو مشروبات"], ["معدات مكتبية", "موردو معدات مكتبية"],
  ["معسل", "موردو معسل"], ["منصة قوى", "المنصات الحكومية"], ["مواد غذائية", "موردو مواد غذائية"],
  ["مواد غذائية أخرى", "موردو مواد غذائية"], ["مياه", "مقدمو المياه"], ["وقود ومواصلات", "موردو وقود وخدمات نقل"],
]);

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const suppliers = workbook.worksheets.getItem("الموردون");
const tags = workbook.worksheets.getItem("فئات الموردين");

// Excel's repair log identifies the exported table object as invalid. Keep the same
// data, headers, column layout, formatting, and validations—but remove
// all native table parts so there is no /xl/tables/table*.xml left to repair.
for (const sheetName of ["ملخص", "الموردون", "فئات الموردين", "خرائط المصدر"]) {
  const sheet = workbook.worksheets.getItem(sheetName);
  for (const table of sheet.tables.items) table.delete();
}

const tagRows = tags.getRange("A2:G51").values;
tags.getRange("G1").values = [["فئة المورد المعتمدة في أودو"]];
tags.getRange("G2:G51").values = tagRows.map((row) => [categoryNames.get(String(row[2] ?? "")) ?? String(row[6] ?? row[2] ?? "")]);
tags.getRange("G2:G51").format.fill = "#E2F0D9";

const supplierRows = suppliers.getRange("A2:J287").values;
suppliers.getRange("H1").values = [["فئات المورد المعتمدة في أودو"]];
suppliers.getRange("J1").values = [["فئة المورد — اختيار عند عدم وجود فئة"]];
const manualRows = [];
for (let index = 0; index < supplierRows.length; index += 1) {
  const sourceCategory = String(supplierRows[index][7] ?? "").trim();
  const rowNumber = index + 2;
  suppliers.getRange(`J${rowNumber}`).clear({ applyTo: "contents" });
  if (sourceCategory) {
    suppliers.getRange(`H${rowNumber}`).values = [[sourceCategory.split("، ").map((value) => categoryNames.get(value) ?? value).join("، ")]];
    suppliers.getRange(`J${rowNumber}`).format.fill = "#F3F4F6";
  } else {
    manualRows.push(rowNumber);
    suppliers.getRange(`J${rowNumber}`).format.fill = "#FFF2CC";
  }
}

// Excel permits an inline list; it does not permit a direct reference to another worksheet.
// Apply it only to the yellow cells that need an owner selection.
for (const rowNumber of manualRows) {
  suppliers.getRange(`J${rowNumber}`).dataValidation = {
    rule: { type: "list", values: currentOdooTags },
  };
}

const categoryCheck = await workbook.inspect({ kind: "table", range: "فئات الموردين!A1:G16", include: "values,formulas", tableMaxRows: 16, tableMaxCols: 7 });
console.log(categoryCheck.ndjson);
const supplierCheck = await workbook.inspect({ kind: "table", range: "الموردون!A1:J16", include: "values,formulas", tableMaxRows: 16, tableMaxCols: 10 });
console.log(supplierCheck.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "formula error scan after Excel-safe supplier-category repair" });
console.log(errors.ndjson);
for (const [sheetName, range, suffix] of [["فئات الموردين", "A1:G16", "categories"], ["الموردون", "A1:J16", "suppliers"]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.5, format: "png" });
  await fs.writeFile(`outputs/noorix_supplier_review_20260912/noorix_supplier_review_supplier_categories_excel_compatible.${suffix}.png`, new Uint8Array(await preview.arrayBuffer()));
}
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, manualSelectionRows: manualRows.length, validationValues: currentOdooTags }));
