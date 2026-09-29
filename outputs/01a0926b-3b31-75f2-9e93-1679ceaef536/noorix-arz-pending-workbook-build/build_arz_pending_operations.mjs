import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "D:/Codex/Baseer-odoo/outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/noorix-arz-pending";
const outputPath = `${outputDir}/arz_pending_operations_for_owner.xlsx`;
const previewPath = `${outputDir}/arz_pending_operations_preview.png`;
const company = "ARZ";
const date = (iso) => {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
};

const pending = [
  ["2026-04-30", "EXP-20260430-003", "مؤسسة اللمسات الاخيرة", "سرير", "أثاث", 550.00, "أثاث بلا دليل أصل"],
  ["2026-04-30", "EXP-20260430-004", "مؤسسة احمد الزهراني", "سلم", "أصول ومعدات", 370.00, "أصل أو معدات بلا دليل"],
  ["2026-04-30", "EXP-20260430-005", "NO TAX", "كنب مستخدم", "أثاث", 500.00, "أثاث بلا دليل أصل"],
  ["2026-06-15", "EXP-20260615-001", "NO TAX", "مكيفات دولاب Carrier عدد 2", "أجهزة وإلكترونيات", 11215.00, "أجهزة بلا دليل أصل"],
  ["2026-06-18", "PUR-20260618-001", "مؤسسة الألماسية للأزياء", "بنكي", "غير مصنفة", 250.70, "غير مصنف"],
  ["2026-06-20", "EXP-20260620-002", "شركة عالم ساكو", "اسامه", "أجهزة وإلكترونيات", 210.05, "أجهزة بلا دليل أصل"],
  ["2026-06-20", "EXP-20260620-003", "لولو هايبر", "نقدا + نقدا", "أجهزة وإلكترونيات", 103.00, "أجهزة بلا دليل أصل"],
  ["2026-06-21", "EXP-20260621-003", "شركة عالم ساكو", "ستاند شاشة متنقل", "أجهزة وإلكترونيات", 899.00, "أجهزة بلا دليل أصل"],
  ["2026-06-21", "PUR-20260621-001", "مؤسسة دروع الكواكب التجارية", "نقدا + نقدا", "غير مصنفة", 250.00, "غير مصنف"],
  ["2026-06-23", "EXP-20260623-001", "شركة عالم ساكو", "مصروفات", "أجهزة وإلكترونيات", 140.00, "أجهزة بلا دليل أصل"],
  ["2026-06-28", "EXP-20260628-001", "مؤسسة احمد الزهراني", "مصروفات", "أصول ومعدات", 40.02, "أصل أو معدات بلا دليل"],
  ["2026-07-04", "EXP-20260704-001", "مؤسسة احمد الزهراني", "مصروفات", "أصول ومعدات", 54.00, "أصل أو معدات بلا دليل"],
  ["2026-07-09", "PUR-20260709-006", "صالح وعبدالعزيز", "", "غير مصنفة", 70.01, "غير مصنف"],
  ["2026-07-13", "PUR-20260713-005", "مؤسسة دروع الكواكب التجارية", "", "غير مصنفة", 200.00, "غير مصنف"],
  ["2026-07-13", "PUR-20260713-006", "مؤسسة دروع الكواكب التجارية", "", "غير مصنفة", 250.00, "غير مصنف"],
  ["2026-07-15", "PUR-20260715-001", "دوحة المستهلك", "", "غير مصنفة", 20.00, "غير مصنف — مورد داخلي محتمل"],
  ["2026-07-17", "PUR-20260717-003", "صالح وعبدالعزيز", "", "غير مصنفة", 71.30, "غير مصنف"],
  ["2026-07-21", "PUR-20260721-004", "مؤسسة أمل بن عبدالله الأحمري التجارية", "", "غير مصنفة", 550.00, "غير مصنف"],
  ["2026-07-22", "PUR-20260722-001", "شركة عذوبة الشروق التجارية", "", "غير مصنفة", 57.50, "غير مصنف"],
  ["2026-07-29", "PUR-20260729-006", "صالح وعبدالعزيز", "", "غير مصنفة", 70.00, "غير مصنف"],
  ["2026-08-05", "PUR-20260805-010", "أطياف سيناء", "", "غير مصنفة", 65.00, "غير مصنف"],
  ["2026-08-07", "PUR-20260807-001", "جرمان شيب صقر", "", "غير مصنفة", 60.00, "غير مصنف"],
  ["2026-08-08", "PUR-20260808-001", "شركة محمد المنهالي للتجارة", "", "غير مصنفة", 164.50, "غير مصنف"],
  ["2026-08-10", "EXP-20260810-001", "مؤسسة احمد الزهراني", "مصروفات", "أصول ومعدات", 30.02, "أصل أو معدات بلا دليل"],
  ["2026-08-14", "PUR-20260814-002", "مستشفى", "", "غير مصنفة", 50.00, "غير مصنف"],
  ["2026-08-14", "PUR-20260814-011", "ياسر مطلق العتيبي", "", "غير مصنفة", 35.01, "غير مصنف"],
  ["2026-08-14", "PUR-20260814-014", "هنجر ستيشن", "", "غير مصنفة", 33.95, "غير مصنف"],
  ["2026-08-21", "EXP-20260821-001", "مؤسسة احمد الزهراني", "مصروفات", "أصول ومعدات", 108.00, "أصل أو معدات بلا دليل"],
  ["2026-08-21", "PUR-20260821-001", "صالح وعبدالعزيز", "", "غير مصنفة", 4.00, "غير مصنف"],
  ["2026-08-24", "PUR-20260824-002", "مؤسسة عايض بن مناحي", "", "غير مصنفة", 86.00, "غير مصنف"],
  ["2026-08-27", "PUR-20260827-006", "صح للديكور", "", "غير مصنفة", 29.19, "غير مصنف"],
  ["2026-08-29", "PUR-20260829-008", "آل شبلان", "", "غير مصنفة", 212.75, "غير مصنف"],
  ["2026-09-06", "PUR-20260906-001", "مؤسسة عايض بن مناحي", "", "غير مصنفة", 62.00, "غير مصنف"],
  ["2026-09-08", "EXP-20260908-001", "مؤسسة احمد الزهراني", "مصروفات", "أصول ومعدات", 108.00, "أصل أو معدات بلا دليل"],
  ["2026-09-08", "PUR-20260908-003", "آل شبلان", "", "غير مصنفة", 53.00, "غير مصنف"],
  ["2026-09-10", "PUR-20260910-001", "تخفيضات العائلة", "", "غير مصنفة", 60.25, "غير مصنف"],
];

const wages = [
  ["2026-04-03", "EXP-20260403-001", "صرف راتب مؤقت", "مصروفات", 150.00],
  ["2026-04-08", "EXP-20260408-001", "اوفر تايم", "مصروفات", 70.00],
  ["2026-04-09", "EXP-20260409-001", "اوفر تايم", "مصروفات", 75.00],
  ["2026-04-10", "EXP-20260410-001", "اوفر تايم", "مصروفات", 60.00],
  ["2026-04-11", "EXP-20260411-001", "اوفر تايم", "مصروفات", 40.00],
  ["2026-04-12", "EXP-20260412-001", "اوفر تايم", "مصروفات", 50.00],
  ["2026-04-13", "EXP-20260413-002", "اوفر تايم", "مصروفات", 30.00],
  ["2026-04-16", "EXP-20260416-001", "صرف راتب مؤقت", "راتب حمو باريستا", 100.00],
  ["2026-04-16", "EXP-20260416-002", "صرف راتب مؤقت", "راتب رجب شيشة", 200.00],
  ["2026-04-19", "EXP-20260419-001", "اوفر تايم", "عبدالمجيد", 100.00],
  ["2026-04-23", "EXP-20260423-001", "اوفر تايم", "عاشق", 50.00],
  ["2026-04-28", "EXP-20260502-002", "اوفر تايم", "كريم", 40.00],
  ["2026-04-29", "EXP-20260429-002", "اوفر تايم", "راتب أحمد سعدون", 1000.00],
  ["2026-04-30", "EXP-20260430-006", "صرف راتب مؤقت", "مصروفات", 1250.00],
  ["2026-04-30", "EXP-20260502-003", "اوفر تايم", "كريم", 50.00],
  ["2026-05-01", "EXP-20260501-001", "اوفر تايم", "Expenses", 50.00],
  ["2026-05-08", "EXP-20260508-001", "صرف راتب مؤقت", "راتب شريف نصف شهر", 2500.00],
  ["2026-05-12", "EXP-20260512-006", "اوفر تايم", "Expenses", 50.00],
  ["2026-05-12", "EXP-20260512-007", "اوفر تايم", "Expenses", 100.00],
  ["2026-05-18", "EXP-20260518-001", "اوفر تايم", "Expenses", 50.00],
  ["2026-05-21", "EXP-20260521-001", "اوفر تايم", "Expenses", 50.00],
  ["2026-06-21", "EXP-20260621-004", "اوفر تايم", "مصروفات", 50.00],
  ["2026-06-21", "EXP-20260621-005", "اوفر تايم", "مصروفات", 50.00],
];

if (pending.length !== 36 || Math.abs(pending.reduce((sum, row) => sum + row[5], 0) - 17032.25) > 0.001) throw new Error("Pending-operation control total differs");
if (wages.length !== 23 || Math.abs(wages.reduce((sum, row) => sum + row[4], 0) - 6165.00) > 0.001) throw new Error("Wage reference control total differs");

const wb = Workbook.create();
const main = wb.worksheets.add("العمليات المعلقة");
const wageSheet = wb.worksheets.add("الأجور المرحلة");
const guide = wb.worksheets.add("التعليمات");
const font = { name: "Arial", size: 10, color: "#1F2937" };
const header = { fill: "#1F4E78", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
const title = { font: { name: "Arial", size: 16, bold: true, color: "#17365D" } };
const note = { font: { name: "Arial", size: 10, italic: true, color: "#4B5563" } };

main.showGridLines = false;
main.getRange("A1").values = [["عمليات ARZ المعلقة للتصنيف"]];
main.getRange("A1").format = title;
main.getRange("A2").values = [["عدّل الخلايا الصفراء فقط. المبالغ شاملة الضريبة، والنسخة الأصلية لا تتأثر بهذا الملف."]];
main.getRange("A2").format = note;
main.getRange("A3:B3").values = [["عدد العمليات", pending.length]];
main.getRange("D3:E3").values = [["إجمالي المبلغ (ريال)", null]];
main.getRange("E3").formulas = [["=SUM(G6:G41)"]];
main.getRange("A3:E3").format.fill = "#EAF2F8";
main.getRange("A3:E3").format.font = { name: "Arial", size: 10, bold: true, color: "#17365D" };
main.getRange("E3").format.numberFormat = "#,##0.00";

const headers = [["الشركة", "التاريخ", "رقم المستند", "المورد", "وصف المصدر", "فئة نوركس", "المبلغ (ريال)", "سبب التعليق", "قرار المالك", "الفئة أو الحساب المعتمد", "ملاحظات المالك", "معرف المصدر"]];
main.getRange("A5:L5").values = headers;
main.getRange("A5:L5").format = header;
const pendingValues = pending.map((row, index) => [company, date(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], "", "", "", `ARZ-PENDING-${String(index + 1).padStart(2, "0")}`]);
main.getRange(`A6:L${5 + pendingValues.length}`).values = pendingValues;
main.getRange(`B6:B${5 + pendingValues.length}`).format.numberFormat = "yyyy-mm-dd";
main.getRange(`G6:G${5 + pendingValues.length}`).format.numberFormat = "#,##0.00";
main.getRange(`I6:K${5 + pendingValues.length}`).format.fill = "#FFF2CC";
main.getRange(`I6:K${5 + pendingValues.length}`).format.wrapText = true;
main.getRange(`A5:L${5 + pendingValues.length}`).format.font = font;
main.getRange(`A6:L${5 + pendingValues.length}`).format.verticalAlignment = "center";
main.getRange(`A5:L${5 + pendingValues.length}`).format.borders = { preset: "outside", style: "thin", color: "#AAB7C4" };
main.getRange(`I6:I${5 + pendingValues.length}`).dataValidation = { rule: { type: "list", values: ["رحّل", "استبعد", "احتاج توضيح"] } };
main.getRange(`J6:J${5 + pendingValues.length}`).dataValidation = { rule: { type: "list", values: ["400042 - صيانة وتشغيل", "106002 - أثاث", "106003 - أجهزة وإلكترونيات", "400001 - مشتريات/مواد", "400048 - وقود ومواصلات", "400034 - تسويق", "400046 - هدايا", "400093 - رسوم حكومية وإقامات", "أخرى"] } };
main.getRange(`I6:I${5 + pendingValues.length}`).conditionalFormats.add("containsText", { text: "رحّل", format: { fill: "#E2F0D9", font: { color: "#2F6B3B", bold: true } } });
main.getRange(`I6:I${5 + pendingValues.length}`).conditionalFormats.add("containsText", { text: "استبعد", format: { fill: "#FCE4D6", font: { color: "#9C5700", bold: true } } });
main.getRange(`I6:I${5 + pendingValues.length}`).conditionalFormats.add("containsText", { text: "احتاج توضيح", format: { fill: "#FDE9E7", font: { color: "#9C0006", bold: true } } });
main.freezePanes.freezeRows(5);
for (const [column, width] of [["A:A", 12], ["B:B", 13], ["C:C", 22], ["D:D", 28], ["E:E", 31], ["F:F", 19], ["G:G", 15], ["H:H", 28], ["I:I", 16], ["J:J", 28], ["K:K", 30], ["L:L", 16]]) main.getRange(column).format.columnWidth = width;
main.getRange(`A6:L${5 + pendingValues.length}`).format.autofitRows();

wageSheet.showGridLines = false;
wageSheet.getRange("A1").values = [["أجور تاريخية مرحّلة مسبقًا"]];
wageSheet.getRange("A1").format = title;
wageSheet.getRange("A2").values = [["هذه مرجعية فقط: تم إدخالها سابقًا ضمن الرواتب التاريخية، ولا تتطلب قرارًا جديدًا."]];
wageSheet.getRange("A2").format = note;
wageSheet.getRange("A3:B3").values = [["عدد العمليات", wages.length]];
wageSheet.getRange("D3:E3").values = [["الإجمالي (ريال)", null]];
wageSheet.getRange("E3").formulas = [["=SUM(E6:E28)"]];
wageSheet.getRange("A3:E3").format.fill = "#EAF2F8";
wageSheet.getRange("A3:E3").format.font = { name: "Arial", size: 10, bold: true, color: "#17365D" };
wageSheet.getRange("E3").format.numberFormat = "#,##0.00";
wageSheet.getRange("A5:E5").values = [["التاريخ", "رقم المستند", "النوع", "البيان", "المبلغ (ريال)"]];
wageSheet.getRange("A5:E5").format = header;
wageSheet.getRange("A6:E28").values = wages.map((row) => [date(row[0]), row[1], row[2], row[3], row[4]]);
wageSheet.getRange("A6:A28").format.numberFormat = "yyyy-mm-dd";
wageSheet.getRange("E6:E28").format.numberFormat = "#,##0.00";
wageSheet.getRange("A5:E28").format.font = font;
wageSheet.getRange("A5:E28").format.borders = { preset: "outside", style: "thin", color: "#AAB7C4" };
wageSheet.freezePanes.freezeRows(5);
for (const [column, width] of [["A:A", 13], ["B:B", 22], ["C:C", 20], ["D:D", 36], ["E:E", 15]]) wageSheet.getRange(column).format.columnWidth = width;
wageSheet.getRange("A6:E28").format.autofitRows();

guide.showGridLines = false;
guide.getRange("A1").values = [["طريقة تحديث الملف"]];
guide.getRange("A1").format = title;
guide.getRange("A3:A7").values = [
  ["1. افتح ورقة العمليات المعلقة."],
  ["2. اكتب قرارك في قرار المالك: رحّل أو استبعد أو احتاج توضيح."],
  ["3. عند اختيار رحّل، اختر الفئة أو الحساب المعتمد واكتب أي توضيح ضروري."],
  ["4. لا تعدّل رقم المستند أو المبلغ أو الشركة أو معرف المصدر."],
  ["5. أعد رفع الملف هنا، وسأطبّق القرارات في نسخة التجربة مع التسوية."],
];
guide.getRange("A3:A7").format = { font: { name: "Arial", size: 11, color: "#1F2937" }, wrapText: true, verticalAlignment: "center" };
guide.getRange("A9").values = [["المصدر: أرشيف نوركس، شركة ARZ، السجلات المتبقية بعد موجات الترحيل المنفذة في نسخة التجربة."]];
guide.getRange("A9").format = note;
guide.getRange("A:A").format.columnWidth = 105;
guide.getRange("A3:A9").format.autofitRows();

await fs.mkdir(outputDir, { recursive: true });
const preview = await wb.render({ sheetName: "العمليات المعلقة", range: "A1:L18", scale: 1.5, format: "png" });
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);

const summary = await wb.inspect({ kind: "table", range: "العمليات المعلقة!A1:L12", include: "values,formulas", tableMaxRows: 12, tableMaxCols: 12 });
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(JSON.stringify({ outputPath, previewPath, summary: summary.ndjson, errors: errors.ndjson }, null, 2));
