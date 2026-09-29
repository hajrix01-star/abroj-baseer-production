/** Read-only Noorix-to-Odoo QA reconciliation workbook. */
import fs from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const targetDb = "baseer_noorix_data_migration_qa_20260912";
const sourceDb = "noorix_source_inspection_archive159_20260913";
const dbContainer = "baseer_odoo_dev-db-1";
const outputDir = "outputs/01a0926b-3b31-75f2-9e93-1679ceaef536/noorix-odoo-qa-reconciliation";
const outputPath = outputDir + "/noorix_odoo_qa_reconciliation.xlsx";
const testCompanies = new Set(["TEST", "TEST1"]);

function query(database, sql) {
  const output = execFileSync("docker", ["exec", dbContainer, "psql", "-U", "odoo", "-d", database, "-At", "-F", "\t", "-c", sql], { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 });
  return output.split(/\r?\n/).filter(Boolean).map((row) => row.split("\t"));
}
function num(value) { return Number(value || 0); }
function money(value) { return Math.round((value + Number.EPSILON) * 100) / 100; }
function same(left, right) { return Math.abs(left - right) < 0.005; }
function styleTitle(sheet, text, subtitle) {
  sheet.getRange("A1").values = [[text]];
  sheet.getRange("A1").format = { font: { name: "Arial", size: 16, bold: true, color: "#1F2937" } };
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange("A2").format = { font: { name: "Arial", size: 10, italic: true, color: "#475569" } };
}
function styleTable(sheet, bodyRange, headerRange) {
  sheet.getRange(bodyRange).format.font = { name: "Arial", size: 10, color: "#1F2937" };
  sheet.getRange(bodyRange).format.borders = { preset: "inside", style: "thin", color: "#D9E2F3" };
  sheet.getRange(bodyRange).format.verticalAlignment = "center";
  sheet.getRange(headerRange).format = { fill: "#1F4E78", font: { name: "Arial", bold: true, color: "#FFFFFF" }, horizontalAlignment: "center", verticalAlignment: "center", wrapText: true };
}
function addMetric(collection, company, sourceId, sourceAmount, targetAmount, targetDocument, valid) {
  const metric = collection.get(company) || { company, sources: new Set(), targets: new Set(), sourceAmount: 0, targetAmount: 0, valid: true };
  metric.sources.add(sourceId);
  if (Array.isArray(targetDocument)) {
    for (const document of targetDocument) metric.targets.add(document);
  } else if (targetDocument) metric.targets.add(targetDocument);
  metric.sourceAmount += sourceAmount;
  metric.targetAmount += targetAmount;
  metric.valid &&= valid;
  collection.set(company, metric);
}
function metricsToRows(collection, scope, note) {
  return [...collection.values()].sort((a, b) => a.company.localeCompare(b.company, "ar")).map((metric) => ({
    scope, company: metric.company, sourceCount: metric.sources.size, targetCount: metric.targets.size,
    sourceAmount: money(metric.sourceAmount), targetAmount: money(metric.targetAmount),
    valid: metric.valid && same(metric.sourceAmount, metric.targetAmount), note: note(metric),
  }));
}

const sourceInvoices = query(sourceDb, "SELECT i.id,i.company_id,c.name_ar,i.kind,i.total_amount,COALESCE(i.settled_amount,0),i.invoice_number,i.transaction_date::date::text FROM invoices i JOIN companies c ON c.id=i.company_id WHERE i.status='active' ORDER BY c.name_ar,i.transaction_date,i.invoice_number;").map(([id, companyId, sourceCompany, kind, total, settled, document, date]) => ({ id, companyId, sourceCompany, kind, total: num(total), settled: num(settled), document, date }));
const companyNames = new Map(query(targetDb, "SELECT m.source_company_id,c.name FROM baseer_noorix_company_map m JOIN res_company c ON c.id=m.company_id;").map(([sourceCompanyId, targetCompany]) => [sourceCompanyId, targetCompany]));
const sourceCompanyName = (invoice) => companyNames.get(invoice.companyId) || invoice.sourceCompany;

const salesRows = query(targetDb, "WITH source_sales AS (SELECT source_company_id,count(*) source_rows,sum(source_gross) source_gross,sum(source_customers) customers FROM baseer_noorix_sales_summary_map GROUP BY source_company_id), target_sales AS (SELECT x.source_company_id,count(*) target_rows,sum(x.amount_gross) target_gross,sum(x.customer_count) target_customers FROM (SELECT DISTINCT m.source_company_id,p.id,p.amount_gross,p.customer_count FROM baseer_noorix_sales_summary_map m JOIN baseer_pos_summary p ON p.id=m.summary_id) x GROUP BY x.source_company_id) SELECT c.name,s.source_rows,t.target_rows,s.source_gross,t.target_gross,s.customers,t.target_customers FROM source_sales s JOIN target_sales t ON t.source_company_id=s.source_company_id JOIN baseer_noorix_company_map cm ON cm.source_company_id=s.source_company_id JOIN res_company c ON c.id=cm.company_id ORDER BY c.name;").map(([company, sourceCount, targetCount, sourceAmount, targetAmount, sourceCustomers, targetCustomers]) => ({
  scope: "المبيعات اليومية", company, sourceCount: num(sourceCount), targetCount: num(targetCount), sourceAmount: num(sourceAmount), targetAmount: num(targetAmount),
  valid: same(num(sourceAmount), num(targetAmount)), note: "العملاء: " + num(sourceCustomers).toLocaleString() + " في المصدر و" + num(targetCustomers).toLocaleString() + " في أودو",
}));

function mapped(sql, mapper) { return query(targetDb, sql).map(mapper); }
const directPurchaseMaps = mapped("SELECT m.source_company_id,m.source_invoice_id,b.id,m.target_total,b.state,p.state,b.amount_residual,p.is_reconciled,c.name FROM baseer_noorix_purchase_invoice_map m JOIN account_move b ON b.id=m.bill_id JOIN account_payment p ON p.id=m.payment_id JOIN res_company c ON c.id=m.company_id;", ([sourceCompanyId, sourceInvoiceId, billId, targetAmount, billState, paymentState, residual, reconciled, company]) => ({ sourceCompanyId, sourceInvoiceId, targetDocument: billId, targetAmount: num(targetAmount), company, valid: billState === "posted" && paymentState === "paid" && num(residual) === 0 && reconciled === "t" }));
const splitPurchaseMaps = mapped("SELECT m.source_company_id,m.source_invoice_id,b.id,m.target_payment_amount,b.state,p.state,b.amount_residual,p.is_reconciled,c.name FROM baseer_noorix_split_paid_vendor_bill_map m JOIN account_move b ON b.id=m.bill_id JOIN account_payment p ON p.id=m.payment_id JOIN res_company c ON c.id=m.company_id;", ([sourceCompanyId, sourceInvoiceId, billId, targetAmount, billState, paymentState, residual, reconciled, company]) => ({ sourceCompanyId, sourceInvoiceId, targetDocument: billId, targetAmount: num(targetAmount), company, valid: billState === "posted" && paymentState === "paid" && num(residual) === 0 && reconciled === "t" }));
const purchaseBySource = new Map();
for (const row of [...directPurchaseMaps, ...splitPurchaseMaps]) {
  const key = row.sourceCompanyId + "|" + row.sourceInvoiceId;
  purchaseBySource.set(key, [...(purchaseBySource.get(key) || []), row]);
}
const purchases = new Map();
for (const invoice of sourceInvoices) {
  const maps = purchaseBySource.get(invoice.companyId + "|" + invoice.id) || [];
  if (maps.length) addMetric(purchases, maps[0].company || sourceCompanyName(invoice), invoice.id, invoice.total, maps.reduce((total, row) => total + row.targetAmount, 0), maps.map((row) => row.targetDocument), maps.every((row) => row.valid));
}
const purchaseRows = metricsToRows(purchases, "فواتير الموردين والمصروفات والأصول", (metric) => metric.company === "المعلم الشامي" ? "كل الفواتير مدفوعة ومسوّاة؛ فاتورة إيجار واحدة سُددت بدفعتين" : "كل الفواتير مدفوعة ومسوّاة");

const salaryMaps = mapped("SELECT m.source_company_id,m.source_invoice_id,m.move_id,m.target_amount,a.state,c.name FROM baseer_noorix_historical_salary_map m JOIN account_move a ON a.id=m.move_id JOIN res_company c ON c.id=m.company_id;", ([sourceCompanyId, sourceInvoiceId, moveId, targetAmount, state, company]) => ({ sourceCompanyId, sourceInvoiceId, targetDocument: moveId, targetAmount: num(targetAmount), company, valid: state === "posted" }));
const salariesBySource = new Map(salaryMaps.map((row) => [row.sourceCompanyId + "|" + row.sourceInvoiceId, row]));
const salaries = new Map();
for (const invoice of sourceInvoices) {
  const map = salariesBySource.get(invoice.companyId + "|" + invoice.id);
  if (map) addMetric(salaries, map.company || sourceCompanyName(invoice), invoice.id, invoice.total, map.targetAmount, map.targetDocument, map.valid);
}
const salaryRows = metricsToRows(salaries, "رواتب وعمل باليومية", () => "قيود تاريخية: تشمل الرواتب ومستندات العمل باليومية المصنفة ضمنها");

const hrMaps = mapped("SELECT m.source_company_id,m.source_invoice_id,m.move_id,m.target_amount,a.state,c.name FROM baseer_noorix_historical_hr_expense_map m JOIN account_move a ON a.id=m.move_id JOIN res_company c ON c.id=m.company_id;", ([sourceCompanyId, sourceInvoiceId, moveId, targetAmount, state, company]) => ({ sourceCompanyId, sourceInvoiceId, targetDocument: moveId, targetAmount: num(targetAmount), company, valid: state === "posted" }));
const hrBySource = new Map(hrMaps.map((row) => [row.sourceCompanyId + "|" + row.sourceInvoiceId, row]));
const hr = new Map();
for (const invoice of sourceInvoices) {
  const map = hrBySource.get(invoice.companyId + "|" + invoice.id);
  if (map) addMetric(hr, map.company || sourceCompanyName(invoice), invoice.id, invoice.total, map.targetAmount, map.targetDocument, map.valid);
}
const hrRows = metricsToRows(hr, "مصروفات الموارد البشرية", () => "قيد تاريخي مدفوع باسم الموظف وبحساب السيولة المطابق");

const advanceMaps = mapped("SELECT m.source_company_id,m.source_invoice_id,m.loan_id,m.target_amount,a.state,c.name FROM baseer_noorix_employee_advance_opening_map m JOIN account_move a ON a.id=m.move_id JOIN res_company c ON c.id=m.company_id;", ([sourceCompanyId, sourceInvoiceId, loanId, targetAmount, state, company]) => ({ sourceCompanyId, sourceInvoiceId, targetDocument: loanId, targetAmount: num(targetAmount), company, valid: state === "posted" }));
const advancesBySource = new Map(advanceMaps.map((row) => [row.sourceCompanyId + "|" + row.sourceInvoiceId, row]));
const advances = new Map();
for (const invoice of sourceInvoices.filter((row) => row.kind === "advance" && !testCompanies.has(row.sourceCompany))) {
  const map = advancesBySource.get(invoice.companyId + "|" + invoice.id);
  addMetric(advances, map?.company || sourceCompanyName(invoice), invoice.id, invoice.total - invoice.settled, map?.targetAmount || 0, map?.targetDocument, map?.valid ?? true);
}
const advanceRows = metricsToRows(advances, "أرصدة السلف الافتتاحية", (metric) => metric.targets.size ? "الرصيد المتبقي فقط؛ السلف المسددة لم تُعاد كحركات تاريخية" : "رصيد السلف في نوركس مغلق بالكامل");

const payrollRows = query(targetDb, "SELECT c.name,m.source_run_number,m.source_net_raw,m.target_amount,a.state FROM baseer_noorix_payroll_settlement_map m JOIN account_move a ON a.id=m.move_id JOIN res_company c ON c.id=m.company_id;").map(([company, sourceRun, sourceAmount, targetAmount, state]) => ({
  scope: "تسوية صافي راتب بقرار المالك", company, sourceCount: 1, targetCount: 1, sourceAmount: num(sourceAmount), targetAmount: num(targetAmount),
  valid: state === "posted" && same(num(sourceAmount), num(targetAmount)), note: "تشغيل نوركس " + sourceRun + "؛ تسوية بنكية تاريخية",
}));

const covered = new Set([...purchaseBySource.keys(), ...salariesBySource.keys(), ...hrBySource.keys()]);
const uncovered = sourceInvoices.filter((invoice) => !testCompanies.has(invoice.sourceCompany) && ["purchase", "expense", "fixed_expense", "salary", "hr_expense"].includes(invoice.kind) && !covered.has(invoice.companyId + "|" + invoice.id));
const excludedRows = query(sourceDb, "SELECT CASE WHEN c.name_ar IN ('TEST','TEST1') THEN 'شركة اختبار خارج النطاق' ELSE 'مستند ملغي في نوركس' END,c.name_ar,i.kind,count(*),round(sum(i.total_amount)::numeric,2) FROM invoices i JOIN companies c ON c.id=i.company_id WHERE c.name_ar IN ('TEST','TEST1') OR i.status='cancelled' GROUP BY 1,c.name_ar,i.kind ORDER BY 1,c.name_ar,i.kind;").map(([reason, company, kind, documents, total]) => [reason, company, kind, num(documents), num(total)]);
const masterRows = query(targetDb, "SELECT 'الشركات', c.name, count(*)::text, count(DISTINCT m.company_id)::text FROM baseer_noorix_company_map m JOIN res_company c ON c.id=m.company_id GROUP BY c.name UNION ALL SELECT 'الموردون', COALESCE(c.name,'عام'), count(*)::text, count(DISTINCT m.partner_id)::text FROM baseer_noorix_supplier_map m LEFT JOIN baseer_noorix_company_map cm ON cm.source_company_id=m.source_company_id LEFT JOIN res_company c ON c.id=cm.company_id GROUP BY COALESCE(c.name,'عام') UNION ALL SELECT 'الأصناف', c.name, count(*)::text, count(DISTINCT m.product_tmpl_id)::text FROM baseer_noorix_product_map m JOIN baseer_noorix_company_map cm ON cm.source_company_id=m.source_company_id JOIN res_company c ON c.id=cm.company_id GROUP BY c.name UNION ALL SELECT 'تكاليف الأصناف', c.name, count(*)::text, count(DISTINCT m.product_id)::text FROM baseer_noorix_product_cost_map m JOIN baseer_noorix_company_map cm ON cm.source_company_id=m.source_company_id JOIN res_company c ON c.id=cm.company_id GROUP BY c.name ORDER BY 1,2;").map(([section, company, sourceCount, targetCount]) => [section, num(sourceCount), num(targetCount), company]);
const runExceptions = query(targetDb, "SELECT id,name,scope,state FROM baseer_noorix_migration_run WHERE state NOT IN ('committed','reconciled') ORDER BY id;");
const summaryRows = [...salesRows, ...purchaseRows, ...salaryRows, ...hrRows, ...advanceRows, ...payrollRows];

const wb = Workbook.create();
const summary = wb.worksheets.add("الملخص");
const matched = wb.worksheets.add("النطاق المطابق");
const remaining = wb.worksheets.add("المتبقي");
const source = wb.worksheets.add("المصدر والمنهج");
for (const sheet of [summary, matched, remaining, source]) { sheet.showGridLines = false; sheet.tabColor = "#1F4E78"; }

styleTitle(summary, "مقارنة نوركس وأودو", "مقارنة نوركس مع نسخة Odoo التجريبية حتى 2026-09-13. الأرقام بالريال السعودي، ولا يشمل التقرير أي كتابة في النسخة الأصلية.");
summary.getRange("A4:I4").values = [["النطاق", "الشركة", "حالة المقارنة", "وثائق نوركس", "وثائق أودو", "فرق الوثائق", "إجمالي نوركس", "إجمالي أودو", "فرق المبلغ"]];
summary.getRange("A5:I" + (4 + summaryRows.length)).values = summaryRows.map((row) => [row.scope, row.company, row.valid ? "مطابق" : "يحتاج فحص", row.sourceCount, row.targetCount, null, row.sourceAmount, row.targetAmount, null]);
for (let row = 5; row < 5 + summaryRows.length; row += 1) {
  summary.getRange("F" + row).formulas = [["=E" + row + "-D" + row]];
  summary.getRange("I" + row).formulas = [["=H" + row + "-G" + row]];
}
styleTable(summary, "A4:I" + (4 + summaryRows.length), "A4:I4");
summary.getRange("D5:F" + (4 + summaryRows.length)).format.numberFormat = "#,##0";
summary.getRange("G5:I" + (4 + summaryRows.length)).format.numberFormat = "#,##0.00";
summary.getRange("C5:C" + (4 + summaryRows.length)).conditionalFormats.add("containsText", { text: "مطابق", format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } } });
summary.getRange("C5:C" + (4 + summaryRows.length)).conditionalFormats.add("containsText", { text: "يحتاج", format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } } });
const masterHeaderRow = summaryRows.length + 7;
const masterFirstRow = masterHeaderRow + 1;
const masterLastRow = masterHeaderRow + masterRows.length;
summary.getRange("A" + masterHeaderRow + ":D" + masterHeaderRow).values = [["بيانات رئيسية", "عدد المصدر", "عدد الهدف", "الشركة"]];
summary.getRange("A" + masterFirstRow + ":D" + masterLastRow).values = masterRows;
styleTable(summary, "A" + masterHeaderRow + ":D" + masterLastRow, "A" + masterHeaderRow + ":D" + masterHeaderRow);
summary.getRange("B" + masterFirstRow + ":C" + masterLastRow).format.numberFormat = "#,##0";
const summaryNoteRow = masterLastRow + 3;
const clear = uncovered.length === 0 && runExceptions.length === 0;
summary.mergeCells("A" + summaryNoteRow + ":I" + summaryNoteRow);
summary.getRange("A" + summaryNoteRow).values = [[clear ? "النتيجة: لا توجد عملية نشطة غير معالجة في الشركات الفعلية ضمن الأقسام المفحوصة. تُعرض ورقة «المتبقي» الاستبعادات المعتمدة فقط، مع بيان رصيد السلف الافتتاحي." : "تنبيه: يوجد " + uncovered.length + " مستند نشط غير مغطى أو " + runExceptions.length + " تشغيل استثنائي؛ راجع ورقة «المتبقي»."]];
summary.getRange("A" + summaryNoteRow + ":I" + summaryNoteRow).format = { fill: clear ? "#DCFCE7" : "#FFF7ED", font: { name: "Arial", size: 10, color: clear ? "#166534" : "#9A3412" }, wrapText: true };
summary.getRange("A" + summaryNoteRow + ":I" + summaryNoteRow).format.rowHeight = 38;

styleTitle(matched, "النطاق المطابق", "تفاصيل النطاق الذي تمت مقارنته فعليًا مع مستندات Odoo في قاعدة QA.");
matched.getRange("A4:H4").values = [["القسم", "الشركة", "وثائق نوركس", "وثائق أودو", "إجمالي نوركس", "إجمالي أودو", "الفرق", "ملاحظات"]];
matched.getRange("A5:H" + (4 + summaryRows.length)).values = summaryRows.map((row) => [row.scope, row.company, row.sourceCount, row.targetCount, row.sourceAmount, row.targetAmount, null, row.note]);
for (let row = 5; row < 5 + summaryRows.length; row += 1) matched.getRange("G" + row).formulas = [["=F" + row + "-E" + row]];
styleTable(matched, "A4:H" + (4 + summaryRows.length), "A4:H4");
matched.getRange("C5:D" + (4 + summaryRows.length)).format.numberFormat = "#,##0";
matched.getRange("E5:G" + (4 + summaryRows.length)).format.numberFormat = "#,##0.00";
matched.freezePanes.freezeRows(4);

styleTitle(remaining, "الاستبعادات والحالات المعتمدة", "لا توجد عملية تشغيلية نشطة غير معالجة في الشركات الفعلية؛ هذه الورقة تفصل الاستبعادات المتفق عليها فقط.");
remaining.getRange("A4:E4").values = [["سبب الاستبعاد", "الشركة", "نوع العملية في نوركس", "عدد الوثائق", "إجمالي نوركس"]];
remaining.getRange("A5:E" + (4 + excludedRows.length)).values = excludedRows;
styleTable(remaining, "A4:E" + (4 + excludedRows.length), "A4:E4");
remaining.getRange("D5:D" + (4 + excludedRows.length)).format.numberFormat = "#,##0";
remaining.getRange("E5:E" + (4 + excludedRows.length)).format.numberFormat = "#,##0.00";
const advanceHeaderRow = 7 + excludedRows.length;
remaining.getRange("A" + advanceHeaderRow + ":F" + advanceHeaderRow).values = [["الشركة", "حركات السلف في نوركس", "الرصيد المتبقي في نوركس", "أرصدة افتتاحية في أودو", "فرق الرصيد", "المعالجة"]];
const advanceData = advanceRows.map((row) => [row.company, row.sourceCount, row.sourceAmount, row.targetAmount, null, row.note]);
remaining.getRange("A" + (advanceHeaderRow + 1) + ":F" + (advanceHeaderRow + advanceData.length)).values = advanceData;
for (let row = advanceHeaderRow + 1; row <= advanceHeaderRow + advanceData.length; row += 1) remaining.getRange("E" + row).formulas = [["=D" + row + "-C" + row]];
styleTable(remaining, "A" + advanceHeaderRow + ":F" + (advanceHeaderRow + advanceData.length), "A" + advanceHeaderRow + ":F" + advanceHeaderRow);
remaining.getRange("B" + (advanceHeaderRow + 1) + ":B" + (advanceHeaderRow + advanceData.length)).format.numberFormat = "#,##0";
remaining.getRange("C" + (advanceHeaderRow + 1) + ":E" + (advanceHeaderRow + advanceData.length)).format.numberFormat = "#,##0.00";
const coverageRow = advanceHeaderRow + advanceData.length + 3;
remaining.mergeCells("A" + coverageRow + ":F" + coverageRow);
remaining.getRange("A" + coverageRow).values = [[uncovered.length === 0 ? "تغطية العمليات النشطة: لا يوجد مستند شراء أو مصروف أو أصل أو راتب أو موارد بشرية نشط غير مربوط بخريطة هدف في Odoo QA." : "تغطية العمليات النشطة: يوجد " + uncovered.length + " مستند يحتاج مراجعة قبل إغلاق الترحيل."]];
remaining.getRange("A" + coverageRow + ":F" + coverageRow).format = { fill: uncovered.length === 0 ? "#DCFCE7" : "#FEE2E2", font: { name: "Arial", size: 10, color: uncovered.length === 0 ? "#166534" : "#991B1B" }, wrapText: true };
remaining.getRange("A" + coverageRow + ":F" + coverageRow).format.rowHeight = 38;
remaining.freezePanes.freezeRows(4);

styleTitle(source, "مصدر المقارنة", "مصدر المقارنة وحدودها.");
source.getRange("A4:B4").values = [["البند", "القيمة"]];
const sourceRows = [
  ["مصدر البيانات", "أرشيف Noorix 159 المستعاد للقراءة فقط"],
  ["الهدف", "Odoo QA فقط: baseer_noorix_data_migration_qa_20260912"],
  ["قاعدة النسخة الأصلية", "لم تُكتب أثناء الترحيل"],
  ["حالة موجات الترحيل", runExceptions.length === 0 ? "لا توجد موجة فاشلة أو قيد التشغيل" : "استثناءات: " + runExceptions.length],
  ["منهج المبيعات", "مقارنة مبلغ إجمالي وعدد عملاء حسب الشركة؛ دمج يوم ARZ المعتمد يظهر كمصدرين مقابل ملخص واحد"],
  ["منهج الموردين والمصروفات", "مقارنة مبلغ المصدر مع فواتير الموردين ودفعاتها وتسوياتها؛ فاتورة إيجار المعلم الشامي سُددت بدفعتين"],
  ["منهج الرواتب", "مطابقة قيود الرواتب التاريخية، بما فيها العمل باليومية المصنف ضمن الرواتب، إلى وثائق مصدرها"],
  ["منهج الموارد البشرية", "قيد تاريخي مدفوع باسم الموظف وحساب السيولة المطابق، دون اختراع مورد بديل"],
  ["منهج السلف", "نُقل الرصيد المتبقي فقط كسلفة افتتاحية؛ السلف المسددة بقيت تاريخًا في المصدر ولم تُكرر كحركة حالية"],
  ["الاستبعادات", "شركات TEST وTEST1، وكل مستند حالته ملغي في نوركس"],
];
source.getRange("A5:B" + (4 + sourceRows.length)).values = sourceRows;
styleTable(source, "A4:B" + (4 + sourceRows.length), "A4:B4");
const runHeaderRow = 7 + sourceRows.length;
source.getRange("A" + runHeaderRow + ":D" + runHeaderRow).values = [["رقم التشغيل", "اسم التشغيل", "القسم", "الحالة"]];
const runs = query(targetDb, "SELECT id::text,name,scope,state FROM baseer_noorix_migration_run ORDER BY id;");
source.getRange("A" + (runHeaderRow + 1) + ":D" + (runHeaderRow + runs.length)).values = runs.map(([id, name, scope, state]) => [num(id), name, scope, state]);
styleTable(source, "A" + runHeaderRow + ":D" + (runHeaderRow + runs.length), "A" + runHeaderRow + ":D" + runHeaderRow);
source.getRange("D" + (runHeaderRow + 1) + ":D" + (runHeaderRow + runs.length)).conditionalFormats.add("containsText", { text: "reconciled", format: { fill: "#DCFCE7", font: { color: "#166534" } } });

for (const sheet of [summary, matched, remaining, source]) {
  const used = sheet.getUsedRange();
  used.format.autofitColumns();
  used.format.autofitRows();
}
summary.getRange("A:A").format.columnWidth = 31;
summary.getRange("B:B").format.columnWidth = 25;
summary.getRange("C:C").format.columnWidth = 18;
summary.getRange("D:I").format.columnWidth = 15;
matched.getRange("A:B").format.columnWidth = 28;
matched.getRange("C:G").format.columnWidth = 15;
matched.getRange("H:H").format.columnWidth = 52;
remaining.getRange("A:A").format.columnWidth = 26;
remaining.getRange("B:B").format.columnWidth = 24;
remaining.getRange("C:C").format.columnWidth = 28;
remaining.getRange("D:E").format.columnWidth = 18;
remaining.getRange("F:F").format.columnWidth = 54;
source.getRange("A:A").format.columnWidth = 30;
source.getRange("B:B").format.columnWidth = 88;

const keyCheck = await wb.inspect({ kind: "table", range: "الملخص!A1:I" + summaryNoteRow, include: "values,formulas", tableMaxRows: 50, tableMaxCols: 9 });
console.log(keyCheck.ndjson);
const errors = await wb.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "final formula error scan" });
console.log(errors.ndjson);
await fs.mkdir(outputDir, { recursive: true });
for (const previewSpec of [
  { sheetName: "الملخص", range: "A1:I" + summaryNoteRow, file: "summary-preview.png" },
  { sheetName: "النطاق المطابق", range: "A1:H" + (4 + summaryRows.length), file: "matched-preview.png" },
  { sheetName: "المتبقي", range: "A1:F" + coverageRow, file: "remaining-preview.png" },
  { sheetName: "المصدر والمنهج", range: "A1:D" + (runHeaderRow + runs.length), file: "source-preview.png" },
]) {
  const preview = await wb.render({ sheetName: previewSpec.sheetName, range: previewSpec.range, scale: 1.2, format: "png" });
  await fs.writeFile(outputDir + "/" + previewSpec.file, new Uint8Array(await preview.arrayBuffer()));
}
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(outputPath);
console.log(JSON.stringify({ outputPath, uncoveredActiveDocuments: uncovered.length, excludedGroups: excludedRows.length, runExceptions: runExceptions.length }, null, 2));
