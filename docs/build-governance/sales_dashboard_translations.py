"""Generate complete Arabic translations for this module's literal UI messages."""
import json
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[2] / 'custom_addons/baseer_sales_dashboard'
translations = {
    'Applications share of total sales (%)': 'نسبة التطبيقات من إجمالي المبيعات (%)',
    'Chart view': 'الرسم البياني', 'Details': 'التفاصيل', 'Sales by category': 'المبيعات حسب الفئة',
    'Sales by payment method': 'المبيعات حسب طريقة الدفع',
    'Payment method': 'طريقة الدفع', 'Category': 'الفئة',
    'Share of total sales (%)': 'النسبة من إجمالي المبيعات (%)',
    'Covered sales': 'المبيعات المشمولة', 'Covered summaries': 'الملخصات المشمولة',
    'Inconsistent allocations': 'توزيعات غير متطابقة', 'Missing allocations': 'توزيعات غير مسجلة',
    'No payment allocations recorded in this period': 'لا توجد توزيعات دفع مسجلة في هذه الفترة',
    'Sales excluded from payment breakdown': 'مبيعات غير مشمولة بتفصيل طرق الدفع',
    'Approved sales allocations, not bank balances or settlement amounts.': 'توزيع المبيعات المعتمدة على طرق الدفع؛ ولا يمثل أرصدة البنوك أو مبالغ التسويات.',
    'Some approved summaries have missing or inconsistent payment allocations. The breakdown is partial and percentages are unavailable.': 'توجد ملخصات معتمدة بتوزيعات دفع غير مسجلة أو غير متطابقة. التفصيل جزئي والنسب غير متاحة.',
    'Approved payment allocations': 'توزيعات الدفع المعتمدة',
    'Choose a valid native date filter.': 'اختر فترة صحيحة من فلتر التاريخ.',
    'Morning': 'الشفت الصباحي', 'Evening': 'الشفت المسائي', 'Full day': 'دوام كامل',
    'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.': 'يتجاوز التقرير 100,000 سجل مصدر. اختر فترة أقصر؛ لم تُستبعد أي سجلات.',
    'This report exceeds the supported 100-year date span. Choose a shorter period; no dates have been omitted.': 'تتجاوز فترة التقرير الحد المدعوم وهو 100 سنة. اختر فترة أقصر؛ لم تُستبعد أي تواريخ.',
    'Shift performance': 'أداء الشفتات', 'Shift': 'الشفت', 'Metric': 'المؤشر',
    'No recorded shifts in this period': 'لا توجد شفتات مسجلة في هذه الفترة',
    'This metric is unavailable for the recorded shifts': 'هذا المؤشر غير متاح للشفتات المسجلة',
    'Full-day summaries are shown separately and are not split into shifts.': 'تُعرض ملخصات الدوام الكامل مستقلة ولا تُقسّم إلى شفتات.',
    'Sales as bars and registered customers as a line over the selected period': 'أعمدة للمبيعات وخط للعملاء المسجلين خلال الفترة المختارة',
    'Customers (count)': 'العملاء (العدد)',
    'Sales and customers': 'المبيعات والعملاء',
    'No data yet — illustrative preview': 'لا توجد بيانات بعد — عرض توضيحي',
    'Sales summaries': 'ملخصات المبيعات',
    'This month': 'هذا الشهر', 'Last month': 'الشهر السابق', 'Last 30 days': 'آخر 30 يومًا',
    'This year': 'هذه السنة', 'Last year': 'السنة السابقة', 'Custom period': 'فترة مخصصة',
    'Total sales': 'إجمالي المبيعات', 'Tax included': 'شاملة الضريبة',
    'Registered customers': 'العملاء المسجلون', 'From approved summaries': 'من الملخصات المعتمدة',
    'Average daily sales': 'متوسط المبيعات اليومي', 'Completed operating days': 'أيام التشغيل المكتملة',
    'Average daily customers': 'متوسط العملاء اليومي', 'Average bill': 'معدل الفاتورة',
    'Per registered customer': 'لكل عميل مسجل', 'Monthly': 'شهري', 'Daily': 'يومي',
    'Approved sales over the selected period': 'المبيعات المعتمدة خلال الفترة المختارة',
    'Registered customers over the selected period': 'العملاء المسجلون خلال الفترة المختارة',
    'Approved sales and registered customers': 'المبيعات المعتمدة والعملاء المسجلون',
    'Period': 'الفترة', 'From': 'من', 'To': 'إلى', 'Apply': 'تطبيق', 'Refresh': 'تحديث',
    'View approved summaries': 'عرض الملخصات المعتمدة', 'Loading the selected period…': 'جارٍ تحميل الفترة المختارة…',
    'Try again': 'إعادة المحاولة', 'Choose a date range, then apply.': 'حدد تاريخ البداية والنهاية، ثم اضغط تطبيق.',
    'Compared with': 'مقارنة بالفترة', 'Previous': 'السابق', 'Sales': 'المبيعات', 'Customers': 'العملاء',
    'Unavailable': 'غير متاح', 'Partial period': 'فترة غير مكتملة',
    'No approved sales summaries in this period': 'لا توجد ملخصات مبيعات معتمدة في هذه الفترة',
    'Approved summaries will appear here. Unrecorded and closed periods are shown as gaps.': 'تظهر الملخصات بعد اعتمادها. الفترات المغلقة أو غير المدخلة تظهر كفجوات في الرسم.',
    'Completed days': 'أيام مكتملة', 'Partial days': 'أيام غير مكتملة', 'Closed days': 'أيام مغلقة',
    'Unrecorded days': 'أيام غير مدخلة',
    'Daily averages use completed operating days only. Totals include all approved summaries, including partial days.': 'المتوسطات اليومية لأيام التشغيل المكتملة فقط. الإجماليات تشمل جميع الملخصات المعتمدة، بما فيها الأيام غير المكتملة.',
    'Some approved sales have no registered customers. Affected averages are unavailable.': 'توجد مبيعات معتمدة دون عدد عملاء مسجل؛ المتوسطات المتأثرة غير متاحة.',
    'Triangles mark partial periods. Gaps represent closed or unrecorded periods.': 'المثلث يشير إلى فترة غير مكتملة؛ والفجوات لفترات مغلقة أو غير مدخلة.',
    'Period details': 'تفاصيل الفترة', 'Coverage': 'اكتمال البيانات', 'Complete': 'مكتمل',
    'Partial': 'غير مكتمل', 'Closed': 'مغلق', 'Not recorded': 'غير مدخل',
    'Increase': 'ارتفاع', 'Decrease': 'انخفاض', 'No change': 'دون تغيير', 'New': 'جديد',
    'Comparison unavailable': 'المقارنة غير متاحة',
    'The dashboard could not be loaded. Please try again.': 'تعذر تحميل اللوحة. يرجى إعادة المحاولة.',
    'Choose valid dashboard filters.': 'اختر فلاتر صالحة للوحة البيانات.',
    'Choose a valid date range of at most 366 days.': 'اختر فترة صحيحة لا تتجاوز 366 يومًا.',
    'Not available': 'غير متاح', 'This sales dashboard is not available.': 'لوحة ملخصات المبيعات غير متاحة.',
    'This dashboard is not available for the active company.': 'هذه اللوحة غير متاحة للشركة النشطة.',
    'Point of Sale access is required to view sales summaries.': 'يلزم امتلاك صلاحية نقطة البيع لعرض ملخصات المبيعات.',
    'Approved sales summaries': 'ملخصات المبيعات المعتمدة',
}
terms = {}
for path in root.rglob('*'):
    if path.suffix not in ('.py', '.js'):
        continue
    for match in re.finditer(r'''(?:_t|_)\(\s*(['"])(.*?)\1''', path.read_text(encoding='utf-8')):
        terms.setdefault(match.group(2), []).append(path.relative_to(root).as_posix())
terms.setdefault('Sales summaries', []).append('data/dashboard.xml')
assert not set(terms) - set(translations), sorted(set(terms) - set(translations))
lines = ['# Translation of Baseer Sales Summary Dashboard.', 'msgid ""', 'msgstr ""',
         '"Project-Id-Version: Odoo 19.0\\n"', '"Language: ar_001\\n"',
         '"Content-Type: text/plain; charset=UTF-8\\n"',
         '"Plural-Forms: nplurals=6; plural=n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 && n%100<=99 ? 4 : 5;\\n"', '']
for term, sources in sorted(terms.items()):
    lines.append('#. module: baseer_sales_dashboard')
    if any(source.endswith('.js') for source in sources):
        lines.append('#. odoo-javascript')
    if any(source.endswith('.py') for source in sources):
        lines.append('#. odoo-python')
    for source in sorted(set(sources)):
        if source.endswith('.xml'):
            lines.append('#: model:spreadsheet.dashboard,name:baseer_sales_dashboard.dashboard_sales_summary')
        else:
            lines.append('#: code:addons/baseer_sales_dashboard/' + source + ':0')
    lines += ['msgid ' + json.dumps(term, ensure_ascii=False), 'msgstr ' + json.dumps(translations[term], ensure_ascii=False), '']
(root / 'i18n').mkdir(exist_ok=True)
(root / 'i18n/ar.po').write_text('\n'.join(lines), encoding='utf-8')
print(f'Arabic translations complete: {len(terms)} messages')
