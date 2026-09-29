import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_selection.xlsx";
const outputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_odoo_category_names.xlsx";
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const tags = workbook.worksheets.getItem("فئات الموردين");
const rows = tags.getRange("A2:F51").values;

const exact = new Map([
  ["اتصالات", "مقدمو الاتصالات والإنترنت"],
  ["كهرباء", "مقدمو الكهرباء"],
  ["مياه", "مقدمو المياه"],
  ["رسوم منصات حكومية", "المنصات الحكومية"],
  ["منصة قوى", "المنصات الحكومية"],
  ["رواتب وأجور", "خدمات الرواتب والأجور"],
  ["التأمينات الاجتماعية (GOSI)", "خدمات التأمينات الاجتماعية"],
  ["إقامات وجوازات", "خدمات الإقامات والجوازات"],
  ["ضرائب ورسوم أخرى", "رسوم حكومية وضريبية"],
  ["رخصة بلدية", "رسوم تراخيص بلدية"],
  ["رخصة تجارية", "رسوم تراخيص تجارية"],
  ["رسوم إدارة حساب", "رسوم خدمات مالية"],
  ["رسوم تطبيقات", "رسوم منصات وتطبيقات"],
  ["فواتير نقدية صغيرة", "فواتير نقدية صغيرة"],
]);
const proposal = (name, sourceType, existing) => {
  if (existing) return existing;
  if (exact.has(name)) return exact.get(name);
  if (name.startsWith("رسوم")) return name;
  return sourceType === "purchase" ? `موردو ${name}` : `خدمات ${name}`;
};

tags.getRange("G1").values = [["فئة أودو المقترحة"]];
tags.getRange("G1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
tags.getRange("G2:G51").values = rows.map((row) => [proposal(String(row[2] ?? ""), String(row[4] ?? ""), String(row[5] ?? ""))]);
tags.getRange("G2:G51").format.fill = "#E2F0D9";
tags.getRange("G2:G51").format.font = { name: "Arial", size: 10, color: "#1F2937" };
tags.getRange("G2:G51").format.wrapText = true;
tags.getRange("G:G").format.columnWidth = 34;

const check = await workbook.inspect({ kind: "table", range: "فئات الموردين!A1:G16", include: "values,formulas", tableMaxRows: 16, tableMaxCols: 7 });
console.log(check.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 300 }, summary: "formula error scan after Odoo category proposal" });
console.log(errors.ndjson);
const preview = await workbook.render({ sheetName: "فئات الموردين", range: "A1:G16", scale: 1.5, format: "png" });
await fs.writeFile("outputs/noorix_supplier_review_20260912/noorix_supplier_review_odoo_category_names.categories.png", new Uint8Array(await preview.arrayBuffer()));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath }));
