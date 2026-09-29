import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";
import { fileURLToPath } from "node:url";

const path = fileURLToPath(new URL("./noorix_odoo_qa_reconciliation.xlsx", import.meta.url));
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(path));
const summary = await workbook.inspect({ kind: "table", range: "ملخص!A4:H10", include: "values,formulas", tableMaxRows: 10, tableMaxCols: 8 });
const detail = await workbook.inspect({ kind: "table", range: "تفصيل العمليات!A24:J32", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 10 });
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(summary.ndjson);
console.log(detail.ndjson);
console.log(errors.ndjson);
