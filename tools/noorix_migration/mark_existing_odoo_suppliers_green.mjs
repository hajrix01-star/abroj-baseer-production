import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_plan.xlsx";
const outputPath = "outputs/noorix_supplier_review_20260912/noorix_supplier_review_category_plan.xlsx";
const payloadPath = ".local-backups/noorix-migration/runs/20260912-supplier-anonymous-cash-1/supplier-payload.json";
const targetPath = ".local-backups/noorix-migration/runs/20260912-supplier-anonymous-cash-1/target.json";
const input = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(input);
const sheet = workbook.worksheets.getItem("الموردون");

const before = await workbook.inspect({
  kind: "table",
  range: "الموردون!A1:I20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 9,
});
console.log(before.ndjson);

const beforePreview = await workbook.render({
  sheetName: "الموردون",
  range: "A1:I16",
  scale: 1.5,
  format: "png",
});
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review.before-government-match.png",
  new Uint8Array(await beforePreview.arrayBuffer()),
);

const normalize = (value) => String(value ?? "")
  .normalize("NFKC")
  .toLowerCase()
  .trim()
  .replace(/[\u064B-\u065F\u0670]/g, "")
  .replace(/[أإآ]/g, "ا")
  .replace(/ى/g, "ي")
  .replace(/ة/g, "ه")
  .replace(/ـ/g, "")
  .replace(/[^\w\u0600-\u06FF]/g, "")
  .replaceAll("شركه", "")
  .replaceAll("مؤسسه", "")
  .replaceAll("company", "")
  .replaceAll("corporation", "")
  .replaceAll("establishment", "");

const [payload, target] = await Promise.all([
  fs.readFile(payloadPath, "utf8").then(JSON.parse),
  fs.readFile(targetPath, "utf8").then(JSON.parse),
]);
const canonicalByKey = new Map(payload.canonical_partners.map((item) => [item.canonical_key, item]));
const targetsByCoreName = new Map(
  target.partners
    .filter((partner) => partner.company_id === null && partner.parent_id === null && partner.active)
    .map((partner) => [normalize(partner.name.split("|")[0]), partner]),
);

const exactOfficialCoreNames = new Set([
  "وزارة البلديات والإسكان",
  "وزارة التجارة",
  "المركز السعودي للأعمال الاقتصادية",
  "وزارة الموارد البشرية والتنمية الاجتماعية",
  "وزارة العدل",
  "المديرية العامة للجوازات",
  "منصة بلدي",
  "منصة مدد",
  "منصة قوى",
].map(normalize));

const rows = sheet.getRange("A2:I289").values;
const greenRows = [];
const approvedAliasRows = [];
const gosiOrIqamatRows = [];
const electricityCrosswalkRows = [];

const setOdooReference = (rowNumber, action, targetPartner, fill, fontColor) => {
  sheet.getRange(`B${rowNumber}`).values = [[action]];
  const targetCell = sheet.getRange(`I${rowNumber}`);
  targetCell.values = [[targetPartner.name]];
  targetCell.format.fill = fill;
  targetCell.format.font = { name: "Arial", size: 10, bold: true, color: fontColor };
};

const digits = (value) => String(value ?? "").replace(/[^0-9]/g, "");
const electricityTarget = targetsByCoreName.get(normalize("الشركة السعودية للطاقة"));
const electricityBeforeRow = rows.findIndex(
  (row) => row[2] === "الشركة السعودية للكهرباء" && digits(row[3]) === "300002471100003",
) + 2;
if (electricityBeforeRow > 1) {
  const electricityBeforePreview = await workbook.render({
    sheetName: "الموردون",
    range: `A${Math.max(1, electricityBeforeRow - 2)}:I${electricityBeforeRow + 3}`,
    scale: 2,
    format: "png",
  });
  await fs.writeFile(
    "outputs/noorix_supplier_review_20260912/noorix_supplier_review.electricity-before-crosswalk.png",
    new Uint8Array(await electricityBeforePreview.arrayBuffer()),
  );
}

for (let index = 0; index < rows.length; index += 1) {
  const rowNumber = index + 2;
  const [canonicalKey] = rows[index];
  const canonical = canonicalByKey.get(canonicalKey);
  if (!canonical) continue;

  if (canonical.name === "الشركة السعودية للكهرباء" && electricityTarget) {
    if (digits(canonical.vat) !== digits(electricityTarget.vat)) {
      setOdooReference(rowNumber, "ربط بجهة موجودة: تغيير اسم معتمد", electricityTarget, "#C6EFCE", "#006100");
      greenRows.push(rowNumber);
      electricityCrosswalkRows.push(rowNumber);
    }
    continue;
  }

  if (canonical.vat) continue;

  const exactTarget = targetsByCoreName.get(normalize(canonical.name));
  if (exactTarget && exactOfficialCoreNames.has(normalize(exactTarget.name.split("|")[0]))) {
    setOdooReference(rowNumber, "مرشح ربط: اسم رسمي مطابق", exactTarget, "#C6EFCE", "#006100");
    greenRows.push(rowNumber);
    continue;
  }

  if (canonical.name === "منصة مقيم") {
    const targetPartner = targetsByCoreName.get(normalize("مقيم"));
    if (targetPartner) {
      setOdooReference(rowNumber, "مرشح ربط: اسم رسمي مطابق", targetPartner, "#C6EFCE", "#006100");
      greenRows.push(rowNumber);
    }
    continue;
  }

  const approvedAliases = new Map([
    ["هيئة الزكاة والدخل", { target: "هيئة الزكاة والضريبة والجمارك", action: "ربط بجهة موجودة: اسم بديل معتمد" }],
    ["وزارة البلدية", { target: "وزارة البلديات والإسكان", action: "ربط بجهة موجودة: اسم بديل معتمد" }],
    ["GOSI", { target: "المؤسسة العامة للتأمينات الاجتماعية", action: "ربط بجهة موجودة: اختصار رسمي" }],
    ["اقامات", { target: "وزارة الموارد البشرية والتنمية الاجتماعية", action: "ربط بجهة موجودة: قرار المالك" }],
  ]);
  const alias = approvedAliases.get(canonical.name);
  if (alias) {
    const targetPartner = targetsByCoreName.get(normalize(alias.target));
    if (targetPartner) {
      setOdooReference(rowNumber, alias.action, targetPartner, "#C6EFCE", "#006100");
      greenRows.push(rowNumber);
      approvedAliasRows.push(rowNumber);
      if (canonical.name === "GOSI" || canonical.name === "اقامات") {
        gosiOrIqamatRows.push(rowNumber);
      }
    }
  }
}

const verification = await workbook.inspect({
  kind: "table",
  range: "الموردون!A1:I20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 9,
});
console.log(verification.ndjson);

const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "Formula error scan after Odoo-match highlighting",
});
console.log(formulaErrors.ndjson);

const previewRow = greenRows[0] ?? 2;
const preview = await workbook.render({
  sheetName: "الموردون",
  range: `A${Math.max(1, previewRow - 2)}:I${previewRow + 3}`,
  scale: 2,
  format: "png",
});
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review.government-exact-green.png",
  new Uint8Array(await preview.arrayBuffer()),
);

const gosiIqamatPreviewRow = gosiOrIqamatRows[0] ?? 2;
const gosiIqamatPreview = await workbook.render({
  sheetName: "الموردون",
  range: `A${Math.max(1, gosiIqamatPreviewRow - 2)}:I${gosiIqamatPreviewRow + 3}`,
  scale: 2,
  format: "png",
});
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review.gosi-iqamat-green.png",
  new Uint8Array(await gosiIqamatPreview.arrayBuffer()),
);

const electricityPreviewRow = electricityCrosswalkRows[0] ?? 2;
const electricityPreview = await workbook.render({
  sheetName: "الموردون",
  range: `A${Math.max(1, electricityPreviewRow - 2)}:I${electricityPreviewRow + 3}`,
  scale: 2,
  format: "png",
});
await fs.writeFile(
  "outputs/noorix_supplier_review_20260912/noorix_supplier_review.electricity-approved-green.png",
  new Uint8Array(await electricityPreview.arrayBuffer()),
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(JSON.stringify({ greenRows, approvedAliasRows, gosiOrIqamatRows, electricityCrosswalkRows, outputPath }));
