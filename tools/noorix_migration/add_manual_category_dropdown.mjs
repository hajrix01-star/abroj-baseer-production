import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_plan.xlsx";
const outputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_selection.xlsx";
const input = await FileBlob.load(inputPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const suppliers = workbook.worksheets.getItem("الموردون");

const before = await workbook.inspect({
  kind: "table",
  range: "الموردون!A1:J12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 10,
});
console.log(before.ndjson);

const beforePreview = await workbook.render({ sheetName: "الموردون", range: "A1:I16", scale: 1.5, format: "png" });
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_selection.before.png",
  new Uint8Array(await beforePreview.arrayBuffer()),
);

const header = suppliers.getRange("J1");
header.values = [["وسم أودو إضافي — اختيار يدوي"]];
header.format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
};
const inputCells = suppliers.getRange("J2:J287");
inputCells.clear({ applyTo: "contents" });
inputCells.format.fill = "#FFF2CC";
inputCells.format.font = { name: "Arial", size: 10, color: "#1F2937" };
inputCells.format.wrapText = true;
inputCells.dataValidation = {
  rule: {
    type: "list",
    values: [
      "مقدمو الخدمات",
      "مقدمو الكهرباء",
      "مقدمو المياه",
      "مقدمو الاتصالات والإنترنت",
      "الجهات الحكومية",
      "المنصات الحكومية",
    ],
  },
};
suppliers.getRange("J:J").format.columnWidth = 30;

const check = await workbook.inspect({
  kind: "table",
  range: "الموردون!A1:J12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 10,
});
console.log(check.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "formula error scan after manual category dropdown",
});
console.log(errors.ndjson);

const preview = await workbook.render({ sheetName: "الموردون", range: "A1:J16", scale: 1.5, format: "png" });
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_selection.suppliers.png",
  new Uint8Array(await preview.arrayBuffer()),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
console.log(JSON.stringify({ outputPath, validationRange: "الموردون!J2:J287" }));
