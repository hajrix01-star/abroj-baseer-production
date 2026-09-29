/** Build a read-only Noorix product-price review workbook. */
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const sourceDb = "noorix_price_workbook_20260912";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = "outputs/noorix_product_price_review_20260912";
const outputPath = path.join(outputDir, "noorix_product_prices_readonly_20260912.xlsx");
const sourceArchive = "noorix-system-archive-159-cmtydr0xk0004uate1jz9kh6z.tar.gz";
const sourceArchiveSha = "024606ADD82DCD78DC1835828A12D7B22C56E34924FF998ABF752134160E79E2";
const avocadoPrimary = "v4m_5e72f130d19098f85987";
const avocadoAlias = "v4m_aa29dd6c8907b8135acf";

function query(sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", sourceDb, "-At", "-F", "\t", "-c", sql], { encoding: "utf8" }).trim();
  return output ? output.split("\n").map((line) => line.split("\t")) : [];
}

const sql = `
WITH latest AS (
  SELECT ph.item_id, ph.inventory_unit_price, ph.effective_at, ph.created_at, ph.id,
         row_number() OVER (PARTITION BY ph.item_id ORDER BY ph.effective_at DESC, ph.created_at DESC, ph.id DESC) AS rn
  FROM orders_v4_price_history ph
  JOIN orders_v4_documents d ON d.id = ph.document_id
  WHERE d.document_type = 'purchase' AND d.status = 'received'
), history AS (
  SELECT ph.item_id, count(*) AS received_history_rows
  FROM orders_v4_price_history ph
  JOIN orders_v4_documents d ON d.id = ph.document_id
  WHERE d.document_type = 'purchase' AND d.status = 'received'
  GROUP BY ph.item_id
)
SELECT i.id, i.company_id, c.name_ar, i.name_ar, COALESCE(i.name_en, ''), i.item_type,
       COALESCE(l.inventory_unit_price::text, ''), COALESCE(l.effective_at::text, ''),
       COALESCE(h.received_history_rows::text, '0')
FROM orders_v4_items i
JOIN companies c ON c.id = i.company_id
LEFT JOIN latest l ON l.item_id = i.id AND l.rn = 1
LEFT JOIN history h ON h.item_id = i.id
WHERE i.tenant_id = 'default-tenant-noorix-2024'
  AND i.is_active
  AND i.company_id IN ('cmnf604ka009ay8lm556wgd9c', 'cmnaivif80001wavxxfgriptm')
ORDER BY c.name_ar, i.name_ar, i.id;
`;

const rawRows = query(sql).map(([id, companyId, company, nameAr, nameEn, itemType, cost, effectiveAt, historyRows]) => ({
  id, companyId, company, nameAr, nameEn, itemType, cost: cost === "" ? null : Number(cost),
  effectiveAt: effectiveAt ? new Date(`${effectiveAt.slice(0, 10)}T00:00:00Z`) : null,
  historyRows: Number(historyRows),
}));

if (rawRows.length !== 468) throw new Error(`Expected 468 active scoped source rows, found ${rawRows.length}`);

const grouped = new Map();
for (const row of rawRows) {
  const key = row.id === avocadoAlias ? avocadoPrimary : row.id;
  const group = grouped.get(key) || [];
  group.push(row);
  grouped.set(key, group);
}
if (grouped.size !== 467) throw new Error(`Expected 467 target rows after avocado unification, found ${grouped.size}`);

const rows = [...grouped.entries()].map(([targetKey, sourceRows]) => {
  const primary = sourceRows.find((row) => row.id === targetKey) || sourceRows[0];
  const candidates = sourceRows.filter((row) => row.cost !== null).sort((a, b) => {
    const timeA = a.effectiveAt?.getTime() ?? -Infinity;
    const timeB = b.effectiveAt?.getTime() ?? -Infinity;
    return timeB - timeA || b.id.localeCompare(a.id);
  });
  const latest = candidates[0] || null;
  let status;
  let action;
  if (primary.itemType === "sale") {
    status = "لا يوجد سعر بيع في نوركس";
    action = "لا يُستورد — يحتاج مصدر أسعار بيع";
  } else if (!latest) {
    status = "لا توجد تكلفة شراء";
    action = "لا يُستورد — يحتاج قرار يدوي";
  } else if (latest.cost === 0) {
    status = "تكلفة صفرية — موقوفة";
    action = "لا يُستورد — راجع السعر الصفري";
  } else {
    status = "مرشح تكلفة شراء";
    action = "للمراجعة قبل اعتماد تكلفة أودو";
  }
  return {
    company: primary.company,
    nameAr: primary.nameAr,
    nameEn: primary.nameEn,
    usage: primary.itemType === "purchased" ? "مشتريات" : "مبيعات",
    sourceIds: sourceRows.map((row) => row.id).join("، "),
    sourceCount: sourceRows.length,
    latestCost: latest?.cost ?? null,
    latestDate: latest?.effectiveAt ?? null,
    historyRows: sourceRows.reduce((sum, row) => sum + row.historyRows, 0),
    status,
    action,
  };
}).sort((a, b) => a.company.localeCompare(b.company, "ar") || a.nameAr.localeCompare(b.nameAr, "ar"));

const counts = Object.fromEntries([...new Set(rows.map((row) => row.status))].map((status) => [status, rows.filter((row) => row.status === status).length]));
if (counts["مرشح تكلفة شراء"] !== 277 || counts["لا توجد تكلفة شراء"] !== 86 || counts["تكلفة صفرية — موقوفة"] !== 1 || counts["لا يوجد سعر بيع في نوركس"] !== 103) {
  throw new Error(`Unexpected status partition: ${JSON.stringify(counts)}`);
}

const workbook = Workbook.create();
const summary = workbook.worksheets.add("الملخص");
const prices = workbook.worksheets.add("الأسعار");

for (const sheet of [summary, prices]) {
  sheet.showGridLines = false;
  sheet.tabColor = "#1F4E78";
}

summary.getRange("A1:G1").merge();
summary.getRange("A1").values = [["أسعار أصناف نوركس"]];
summary.getRange("A2:G2").merge();
summary.getRange("A2").values = [["عرض مراجعة فقط — أحدث تكلفة من مستندات شراء مستلمة، ولا توجد أي كتابة على أودو"]];
summary.getRange("A4:B9").values = [
  ["البند", "العدد"],
  ["إجمالي أصناف QA", 467],
  ["مرشح تكلفة شراء", 277],
  ["بلا تكلفة شراء", 86],
  ["تكلفة صفرية موقوفة", 1],
  ["بلا سعر بيع في نوركس", 103],
];
summary.getRange("D4:G9").values = [
  ["ملاحظة", "التفاصيل", "", ""],
  ["مصدر التكلفة", "أحدث صف من سعر الشراء لمستند مستلم فقط", "", ""],
  ["المبيعات", "لا توجد أسعار بيع مصدرية للأصناف المبيعة", "", ""],
  ["أفوكادو", "يوجد سجلان مصدران؛ تعرض الورقة الأحدث فقط للمراجعة", "", ""],
  ["استيراد أودو", "لا يُستورد أي سعر من هذا الملف", "", ""],
  ["المصدر", `${sourceArchive} — SHA-256: ${sourceArchiveSha}`, "", ""],
];

const headers = [["الشركة", "اسم الصنف", "الاسم الإنجليزي", "الاستخدام", "معرفات المصدر", "عدد سجلات السعر", "أحدث تكلفة شراء", "تاريخ التكلفة", "حالة السعر", "الإجراء المقترح"]];
prices.getRange("A1:J1").merge();
prices.getRange("A1").values = [["جدول أسعار أصناف نوركس"]];
prices.getRange("A2:J2").merge();
prices.getRange("A2").values = [["مرجع مراجعة قبل أي قرار استيراد. تكلفة الشراء ليست سعر بيع."]];
prices.getRange("A4:J4").values = headers;
prices.getRangeByIndexes(4, 0, rows.length, 10).values = rows.map((row) => [
  row.company, row.nameAr, row.nameEn, row.usage, row.sourceIds, row.historyRows,
  row.latestCost, row.latestDate, row.status, row.action,
]);
prices.tables.add(`A4:J${rows.length + 4}`, true, "NoorixProductPrices");

const titleFormat = { font: { name: "Arial", size: 16, bold: true, color: "#1F2937" }, horizontalAlignment: "left", verticalAlignment: "center" };
const subtitleFormat = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" }, horizontalAlignment: "left" };
for (const [sheet, endColumn] of [[summary, "G"], [prices, "J"]]) {
  sheet.getRange(`A1:${endColumn}1`).format = titleFormat;
  sheet.getRange(`A2:${endColumn}2`).format = subtitleFormat;
  sheet.getRange(`A1:${endColumn}1`).format.rowHeight = 26;
  sheet.getRange(`A2:${endColumn}2`).format.rowHeight = 22;
}

summary.getRange("A4:B4").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
summary.getRange("D4:G4").format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center" };
summary.getRange("A5:B9").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("D5:G9").format.borders = { preset: "outside", style: "thin", color: "#CBD5E1" };
summary.getRange("B5:B9").format.numberFormat = "#,##0";
summary.getRange("A4:G9").format.font = { name: "Arial", size: 11, color: "#1F2937" };
summary.getRange("A4:B4").format.font = { name: "Arial", size: 11, bold: true, color: "#FFFFFF" };
summary.getRange("D4:G4").format.font = { name: "Arial", size: 11, bold: true, color: "#FFFFFF" };
summary.getRange("A1:G9").format.wrapText = true;
summary.getRange("A:A").format.columnWidth = 28;
summary.getRange("B:B").format.columnWidth = 14;
summary.getRange("D:D").format.columnWidth = 18;
summary.getRange("E:E").format.columnWidth = 42;
summary.getRange("F:G").format.columnWidth = 4;

prices.getRange("A4:J4").format = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
prices.getRange(`A5:J${rows.length + 4}`).format.font = { name: "Arial", size: 10, color: "#1F2937" };
prices.getRange(`F5:F${rows.length + 4}`).format.numberFormat = "#,##0";
prices.getRange(`G5:G${rows.length + 4}`).format.numberFormat = "#,##0.00";
prices.getRange(`H5:H${rows.length + 4}`).format.numberFormat = "yyyy-mm-dd";
prices.getRange(`A4:J${rows.length + 4}`).format.wrapText = true;
prices.freezePanes.freezeRows(4);
prices.getRange("A:A").format.columnWidth = 18;
prices.getRange("B:B").format.columnWidth = 26;
prices.getRange("C:C").format.columnWidth = 22;
prices.getRange("D:D").format.columnWidth = 12;
prices.getRange("E:E").format.columnWidth = 44;
prices.getRange("F:F").format.columnWidth = 15;
prices.getRange("G:G").format.columnWidth = 16;
prices.getRange("H:H").format.columnWidth = 15;
prices.getRange("I:I").format.columnWidth = 23;
prices.getRange("J:J").format.columnWidth = 34;
prices.getRange(`I5:I${rows.length + 4}`).conditionalFormats.add("containsText", { text: "مرشح", format: { fill: "#DCFCE7", font: { color: "#166534" } } });
prices.getRange(`I5:I${rows.length + 4}`).conditionalFormats.add("containsText", { text: "صفرية", format: { fill: "#FEE2E2", font: { color: "#991B1B" } } });
prices.getRange(`I5:I${rows.length + 4}`).conditionalFormats.add("containsText", { text: "لا توجد", format: { fill: "#FEF3C7", font: { color: "#92400E" } } });

await fs.mkdir(outputDir, { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

const verify = await workbook.inspect({ kind: "table", range: "الأسعار!A1:J14", include: "values,formulas", tableMaxRows: 14, tableMaxCols: 10 });
console.log(verify.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
const summaryPreview = await workbook.render({ sheetName: "الملخص", range: "A1:G9", scale: 1.5, format: "png" });
await fs.writeFile(path.join(outputDir, "summary-preview.png"), new Uint8Array(await summaryPreview.arrayBuffer()));
const pricesPreview = await workbook.render({ sheetName: "الأسعار", range: "A1:J18", scale: 1.2, format: "png" });
await fs.writeFile(path.join(outputDir, "prices-preview.png"), new Uint8Array(await pricesPreview.arrayBuffer()));
console.log(JSON.stringify({ outputPath, targetRows: rows.length, counts }, null, 2));
