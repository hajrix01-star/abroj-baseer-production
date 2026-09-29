import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const outputDir = fileURLToPath(new URL(".", import.meta.url));
const outputPath = `${outputDir}noorix_odoo_qa_reconciliation.xlsx`;

const sourceRows = [
  ["ARZ", "نشطة", "مبيعات", 240, 2154301.00, 239, 2154301.00, "مطابق", "دمج معتمد لسجلين في 2026-05-26 إلى ملخص واحد"],
  ["ARZ", "نشطة", "مشتريات", 757, 257647.6130, 0, 0, "لم يرحل", "يتطلب موجة مشتريات مستقلة"],
  ["ARZ", "نشطة", "مصروفات", 72, 83677.0500, 0, 0, "لم يرحل", "يتطلب موجة مستقلة"],
  ["ARZ", "نشطة", "مصروفات ثابتة", 32, 237273.3800, 0, 0, "لم يرحل", "الأصول والإهلاك خارج النطاق الحالي"],
  ["ARZ", "نشطة", "رواتب", 8, 184284.7300, 0, 0, "لم يرحل", "7 مسيرات رواتب في المصدر"],
  ["ARZ", "نشطة", "سلف موظفين", 38, 40016.0000, 0, 0, "لم يرحل", "38 سجلًا نشطًا"],
  ["ARZ", "نشطة", "مصروفات موظفين", 6, 7413.0000, 0, 0, "لم يرحل", "يتطلب عقد HR مستقل"],
  ["المعلم الشامي", "نشطة", "مبيعات", 164, 1518655.00, 164, 1518655.00, "مطابق", "مطابقة كاملة"],
  ["المعلم الشامي", "نشطة", "مشتريات", 1322, 642141.1000, 0, 0, "لم يرحل", "يتطلب موجة مشتريات مستقلة"],
  ["المعلم الشامي", "نشطة", "مصروفات", 193, 69594.5700, 0, 0, "لم يرحل", "يتطلب موجة مستقلة"],
  ["المعلم الشامي", "نشطة", "مصروفات ثابتة", 16, 115599.9200, 0, 0, "لم يرحل", "الأصول والإهلاك خارج النطاق الحالي"],
  ["المعلم الشامي", "نشطة", "رواتب", 8, 166690.0383, 0, 0, "لم يرحل", "8 مسيرات رواتب في المصدر"],
  ["المعلم الشامي", "نشطة", "سلف موظفين", 124, 99850.0000, 0, 0, "لم يرحل", "124 سجلًا نشطًا"],
  ["المعلم الشامي", "نشطة", "مصروفات موظفين", 10, 10806.0000, 0, 0, "لم يرحل", "يتطلب عقد HR مستقل"],
  ["دوحة المستهلك", "نشطة", "مبيعات", 164, 472467.00, 164, 472467.00, "مطابق", "مطابقة كاملة"],
  ["دوحة المستهلك", "نشطة", "مشتريات", 245, 289362.7400, 0, 0, "لم يرحل", "يتطلب موجة مشتريات مستقلة"],
  ["دوحة المستهلك", "نشطة", "مصروفات", 4, 1100.0000, 0, 0, "لم يرحل", "يتطلب موجة مستقلة"],
  ["دوحة المستهلك", "نشطة", "مصروفات ثابتة", 10, 18073.7100, 0, 0, "لم يرحل", "الأصول والإهلاك خارج النطاق الحالي"],
  ["دوحة المستهلك", "نشطة", "رواتب", 3, 52700.1000, 0, 0, "لم يرحل", "3 مسيرات رواتب في المصدر"],
  ["دوحة المستهلك", "نشطة", "سلف موظفين", 8, 1760.0000, 0, 0, "لم يرحل", "8 سجلات نشطة"],
  ["دوحة المستهلك", "نشطة", "مصروفات موظفين", 3, 4490.0000, 0, 0, "لم يرحل", "يتطلب عقد HR مستقل"],
  ["وقت الكرك", "نشطة", "مبيعات", 102, 2022645.0600, 102, 2022645.0600, "مطابق", "مطابقة كاملة"],
  ["وقت الكرك", "نشطة", "مشتريات ومصروفات وأصول", 306, 63112.3040, 306, 63112.3000, "مطابق ضمن التقريب", "306 فاتورة مورد و306 دفعة؛ فرق SAR -0.004 من التقريب"],
  ["وقت الكرك", "نشطة", "رواتب", 3, 21404.8100, 0, 0, "لم يرحل", "توجد 3 مسيرات؛ لا تحويل إلى كشوف رواتب بعد"],
  ["وقت الكرك", "نشطة", "سلف موظفين", 24, 12900.0000, 0, 0, "لم يرحل", "24 سجلًا نشطًا"],
  ["وقت الكرك", "نشطة", "تسوية راتب صافي معتمدة", 1, 10216.6700, 1, 10216.6700, "مطابق", "PR-2605-001 فقط، قيد بنك مالك-معتمد وليس مسير رواتب"],
  ["SHAMI TAX", "نشطة", "مشتريات", 36, 275480.0000, 0, 0, "لم يرحل", "لا توجد خريطة شركة في QA"],
  ["TEST", "تجريبية", "كل العمليات النشطة", 25, 16430.0000, 0, 0, "مستبعد", "بيانات اختبار؛ لا تهاجر تلقائيًا"],
  ["TEST1", "مؤرشفة تجريبية", "مبيعات", 1, 2000.0000, 0, 0, "مستبعد", "بيانات اختبار مؤرشفة"],
];

const excludedRows = [
  ["ARZ", "مبيعات", 11, 51760.00, "ملغى في نوركس؛ لا ينشأ بيع أو قيد في أودو"],
  ["ARZ", "مشتريات", 9, 1966.09, "ملغى في نوركس؛ لا ينشأ مورد أو دفعة"],
  ["ARZ", "مصروفات", 3, 5531.50, "ملغى في نوركس"],
  ["ARZ", "مصروفات ثابتة", 3, 7839.69, "ملغى في نوركس"],
  ["ARZ", "رواتب", 12, 22345.16, "ملغى في نوركس"],
  ["ARZ", "سلف موظفين", 1, 100.00, "ملغى في نوركس"],
  ["المعلم الشامي", "مبيعات", 2, 2751.00, "ملغى في نوركس"],
  ["المعلم الشامي", "مشتريات", 32, 9775.47, "ملغى في نوركس"],
  ["المعلم الشامي", "مصروفات", 14, 76290.54, "ملغى في نوركس"],
  ["المعلم الشامي", "رواتب", 1, 900.00, "ملغى في نوركس"],
  ["المعلم الشامي", "سلف موظفين", 3, 400.00, "ملغى في نوركس"],
  ["دوحة المستهلك", "مبيعات", 1, 3753.00, "ملغى في نوركس"],
  ["وقت الكرك", "مبيعات", 1, 3204.00, "ملغى في نوركس"],
  ["وقت الكرك", "مشتريات", 1, 789.00, "ملغى في نوركس"],
  ["وقت الكرك", "سلف موظفين", 1, 250.00, "ملغى في نوركس"],
  ["TEST1", "مصروفات", 1, 115.00, "ملغى في نوركس"],
];

const workbook = Workbook.create();
const summary = workbook.worksheets.add("ملخص");
const detail = workbook.worksheets.add("تفصيل العمليات");
const excluded = workbook.worksheets.add("المستبعدات");
const sources = workbook.worksheets.add("المصادر والمنهجية");

for (const sheet of [summary, detail, excluded, sources]) {
  sheet.showGridLines = false;
  sheet.tabColor = "#7A4D6D";
}

summary.getRange("A1:H1").merge();
summary.getRange("A1").values = [["تسوية عمليات نوركس مع أودو — النسخة التجريبية"]];
summary.getRange("A2:H2").merge();
summary.getRange("A2").values = [["حتى أرشيف نوركس الموحد بتاريخ 2026-09-13؛ جميع المبالغ بالريال السعودي والإجمالي شامل الضريبة حيث ينطبق"]];
summary.getRange("A4:H4").values = [["النطاق", "سجلات المصدر", "مبلغ المصدر", "سجلات أودو", "مبلغ أودو", "الفرق", "الحالة", "ملاحظة"]];
summary.getRange("A5:H10").values = [
  ["مبيعات الشركات التشغيلية الأربع", 670, 6168068.06, 669, 6168068.06, 0, "مطابق", "سجلا ARZ في 2026-05-26 مدمجان في ملخص واحد مع حفظ النسب"],
  ["مشتريات ومصروفات وقت الكرك", 306, 63112.3040, 306, 63112.3000, -0.0040, "مطابق ضمن التقريب", "306 فاتورة مورد و306 دفعة أصلية"],
  ["تسوية صافي راتب وقت الكرك المعتمدة", 1, 10216.6700, 1, 10216.6700, 0, "مطابق", "قيد بنك واحد؛ ليس استيراد مسير رواتب"],
  ["الرواتب لجميع الشركات", 22, 425079.6783, 0, 0, -425079.6783, "غير مرحّلة", "يمثل صفوف الرواتب غير المرحّلة فقط؛ لا يشمل تسوية PR-2605-001 أعلاه"],
  ["مشتريات ومصروفات وأصول غير وقت الكرك", 2706, 2012659.0830, 0, 0, -2012659.0830, "غير مرحّلة", "ARZ والمعلم والدوحة وSHAMI TAX؛ بيانات TEST مستبعدة"],
  ["سلف الموظفين للشركات التشغيلية", 194, 154526.0000, 0, 0, -154526.0000, "غير مرحّلة", "تحتاج قرار معالجة سلف ورصيد افتتاحي/تسوية"],
];
summary.getRange("A13:H13").merge();
summary.getRange("A13").values = [["خلاصة الفجوات"]];
summary.getRange("A14:H17").values = [
  ["الشركات ذات خريطة QA", "ARZ، المعلم الشامي، دوحة المستهلك، وقت الكرك، وalias وقت الكرك", null, null, null, null, null, null],
  ["بلا خريطة شركة QA", "SHAMI TAX؛ TEST؛ TEST1", null, null, null, null, null, null],
  ["الملغيات", "لا تُرحّل؛ تحفظ كدليل فقط", null, null, null, null, null, null],
  ["شرط الترحيل التالي", "تقرير تسوية شركة × شهر × نوع × ضريبة × دفع، ثم موجات مستقلة قابلة للإعادة", null, null, null, null, null, null],
];

detail.getRange("A1:J1").merge();
detail.getRange("A1").values = [["تفصيل العمليات النشطة والمقارنة مع أودو QA"]];
detail.getRange("A3:J3").values = [["الشركة", "حالة الشركة", "نوع العملية", "عدد المصدر", "إجمالي المصدر", "عدد أودو", "إجمالي أودو", "الفرق", "الحالة", "المعالجة أو الملاحظة"]];
detail.getRange(`A4:I${sourceRows.length + 3}`).values = sourceRows.map((row, index) => [
  ...row.slice(0, 7),
  null,
  row[7],
]);
detail.getRange(`J4:J${sourceRows.length + 3}`).values = sourceRows.map((row) => [row[8]]);
detail.getRange("H4").formulas = [["=G4-E4"]];
detail.getRange(`H4:H${sourceRows.length + 3}`).fillDown();
const totalRow = sourceRows.length + 5;
detail.getRange(`A${totalRow}:J${totalRow}`).values = [["إجمالي الصفوف المعروضة", null, null, null, null, null, null, null, null, null]];
detail.getRange(`D${totalRow}`).formulas = [[`=SUM(D4:D${sourceRows.length + 3})`]];
detail.getRange(`E${totalRow}`).formulas = [[`=SUM(E4:E${sourceRows.length + 3})`]];
detail.getRange(`F${totalRow}`).formulas = [[`=SUM(F4:F${sourceRows.length + 3})`]];
detail.getRange(`G${totalRow}`).formulas = [[`=SUM(G4:G${sourceRows.length + 3})`]];
detail.getRange(`H${totalRow}`).formulas = [[`=SUM(H4:H${sourceRows.length + 3})`]];

excluded.getRange("A1:E1").merge();
excluded.getRange("A1").values = [["سجلات نوركس الملغاة أو المستبعدة"]];
excluded.getRange("A3:E3").values = [["الشركة", "نوع العملية", "العدد", "الإجمالي", "المعالجة"]];
excluded.getRange(`A4:E${excludedRows.length + 3}`).values = excludedRows;

sources.getRange("A1:D1").merge();
sources.getRange("A1").values = [["المصادر والمنهجية"]];
sources.getRange("A3:D3").values = [["المصدر", "الهوية", "الاستخدام", "حد المقارنة"]];
sources.getRange("A4:D7").values = [
  ["أرشيف نوركس الموحد", "SHA-256: 948db34074c397f7caef3feb29fd954b9d49aa03104e3a43dec625d837636e1c", "مصدر الأعداد والمبالغ وحالات المستندات", "العمليات النشطة تقارن؛ الملغيات تحفظ كدليل"],
  ["خرائط ترحيل QA", "sales summary maps=670؛ purchase maps=306؛ payroll settlement maps=1", "تثبت وجود مقابل في أودو ومنع التكرار", "المبيعات 670 مصدر إلى 669 هدف بسبب دمج معتمد"],
  ["مبيعات QA", "أربع شركات تشغيلية", "مقارنة الشركة والإجمالي والعملاء وقنوات التحصيل", "إجمالي نوركس شامل VAT 15% حسب قرار المالك"],
  ["مشتريات وقت الكرك QA", "306 فاتورة و306 دفعة", "مطابقة الوثيقة والضريبة والدفع والتسوية", "فرق المصدر الخام عن SAR المقرب: -0.004"],
];
sources.getRange("A10:D10").merge();
sources.getRange("A10").values = [["قواعد القراءة"]];
sources.getRange("A11:D14").values = [
  ["1", "لا يقارن حقل ضريبة نوركس الصفري بضريبة أودو للمبيعات", "قرار الأعمال يعامل إجمالي المبيعات شامل ضريبة 15%", null],
  ["2", "لا تعد تسوية PR-2605-001 مسير رواتب كامل", "هي قيد صافي راتب معتمد من المالك فقط", null],
  ["3", "صفوف TEST وTEST1 ليست فجوة ترحيل تلقائية", "تصنف كبيانات تجريبية حتى يصدر قرار مختلف", null],
  ["4", "أي ترحيل لاحق يحتاج مفتاح مصدر، تسوية شهرية، وإعادة تشغيل بلا تكرار", "لا تعتمد المقارنة على الاسم أو المبلغ فقط", null],
];

const title = { fill: "#4A2443", font: { bold: true, color: "#FFFFFF", size: 16 }, horizontalAlignment: "center", verticalAlignment: "center" };
const subtitle = { fill: "#F5EEF3", font: { color: "#5C4A57", italic: true }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
const header = { fill: "#7A4D6D", font: { bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
const section = { fill: "#E9D8E4", font: { bold: true, color: "#4A2443" }, horizontalAlignment: "right", verticalAlignment: "center" };
const grid = { borders: { preset: "all", style: "thin", color: "#D9CCD5" }, verticalAlignment: "center", wrapText: true };

for (const [sheet, titleRange, subtitleRange, headers, body] of [
  [summary, "A1:H1", "A2:H2", ["A4:H4"], ["A5:H10", "A14:H17"]],
  [detail, "A1:J1", null, ["A3:J3"], [`A4:J${sourceRows.length + 3}`, `A${totalRow}:J${totalRow}`]],
  [excluded, "A1:E1", null, ["A3:E3"], [`A4:E${excludedRows.length + 3}`]],
  [sources, "A1:D1", null, ["A3:D3"], ["A4:D7", "A11:D14"]],
]) {
  sheet.getRange(titleRange).format = title;
  sheet.getRange(titleRange).format.rowHeight = 28;
  if (subtitleRange) sheet.getRange(subtitleRange).format = subtitle;
  for (const range of headers) sheet.getRange(range).format = header;
  for (const range of body) sheet.getRange(range).format = grid;
}
summary.getRange("A13:H13").format = section;
sources.getRange("A10:D10").format = section;
detail.getRange(`A${totalRow}:J${totalRow}`).format = { ...section, borders: { preset: "doubleBottom", style: "medium", color: "#7A4D6D" } };

for (const sheet of [summary, detail, excluded]) {
  sheet.getRange("D:D").format.numberFormat = "#,##0";
  sheet.getRange("E:E").format.numberFormat = "#,##0.0000;(#,##0.0000);-";
  sheet.getRange("F:F").format.numberFormat = "#,##0";
  sheet.getRange("G:G").format.numberFormat = "#,##0.00;(#,##0.00);-";
  sheet.getRange("H:H").format.numberFormat = "#,##0.0000;(#,##0.0000);-";
}
summary.getRange("C5:C10").format.numberFormat = "#,##0.0000;(#,##0.0000);-";
summary.getRange("E5:E10").format.numberFormat = "#,##0.00;(#,##0.00);-";
summary.getRange("F5:F10").format.numberFormat = "#,##0.0000;(#,##0.0000);-";
excluded.getRange(`C4:C${excludedRows.length + 3}`).format.numberFormat = "#,##0";
excluded.getRange(`D4:D${excludedRows.length + 3}`).format.numberFormat = "#,##0.00;(#,##0.00);-";

summary.freezePanes.freezeRows(4);
detail.freezePanes.freezeRows(3);
excluded.freezePanes.freezeRows(3);
sources.freezePanes.freezeRows(3);

for (const [sheet, widths] of [
  [summary, [30, 14, 17, 14, 17, 15, 20, 46]],
  [detail, [18, 16, 25, 12, 17, 12, 17, 16, 20, 54]],
  [excluded, [20, 22, 12, 17, 48]],
  [sources, [25, 50, 45, 48]],
]) {
  widths.forEach((width, index) => { sheet.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width; });
}

detail.getRange(`I4:I${sourceRows.length + 3}`).conditionalFormats.add("containsText", { text: "مطابق", format: { fill: "#E2F0D9", font: { color: "#2F6B31" } } });
detail.getRange(`I4:I${sourceRows.length + 3}`).conditionalFormats.add("containsText", { text: "لم يرحل", format: { fill: "#FCE4D6", font: { color: "#9C3D1B" } } });

const inspect = await workbook.inspect({ kind: "table", range: "ملخص!A1:H17", include: "values,formulas", tableMaxRows: 20, tableMaxCols: 10 });
console.log(inspect.ndjson);
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "formula error scan" });
console.log(errors.ndjson);
await fs.mkdir(outputDir, { recursive: true });
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(outputPath);
for (const [sheetName, range] of [["ملخص", "A1:H17"], ["تفصيل العمليات", `A1:J${totalRow}`], ["المستبعدات", `A1:E${excludedRows.length + 3}`], ["المصادر والمنهجية", "A1:D14"]]) {
  const preview = await workbook.render({ sheetName, range, scale: 1.2 });
  await fs.writeFile(`${outputDir}${sheetName}.png`, new Uint8Array(await preview.arrayBuffer()));
}
console.log(JSON.stringify({ outputPath, totalRows: sourceRows.length, totalExcludedRows: excludedRows.length }));
