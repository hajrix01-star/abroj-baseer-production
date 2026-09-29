import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = "outputs/noorix_product_review_20260912";
const input = await FileBlob.load(`${outputDir}/noorix_products_odoo_qa_import_plan.xlsx`);
const workbook = await SpreadsheetFile.importXlsx(input);
for (const [sheetName, range, filename] of [
  ["ملخص", "A1:F17", "verify-summary.png"],
  ["أصناف نوركس", "A1:S14", "verify-noorix-items.png"],
  ["أصناف أودو", "A1:I14", "verify-odoo-items.png"],
  ["الفئات", "A1:L14", "verify-categories.png"],
  ["وحدات القياس", "A1:M14", "verify-units.png"],
]) {
  const image = await workbook.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(`${outputDir}/${filename}`, new Uint8Array(await image.arrayBuffer()));
}
const summary = await workbook.inspect({ kind: "workbook,sheet", maxChars: 2000 });
console.log(summary.ndjson);
