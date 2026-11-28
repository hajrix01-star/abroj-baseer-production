"""PDF and Excel exports of the daily sales and customers report."""

import base64
import io
import re
from datetime import datetime

import xlsxwriter

from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import file_path



def _font_data_uri(relative_path):
    with open(file_path(relative_path), 'rb') as handle:
        return 'data:font/truetype;base64,%s' % base64.b64encode(handle.read()).decode()


def _safe_filename(name):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '-', (name or '').strip())
    return (cleaned.strip('-') or 'daily-sales')[:80]


class PosDailyReportExport(models.TransientModel):
    _inherit = 'baseer.pos.daily.report'

    def _ensure_generated(self):
        self.ensure_one()
        self._authorize()
        if not self.generated:
            self.action_generate()
        if not self.generated:
            raise UserError(_('The report could not be generated for these filters.'))
        return self

    def _export_is_arabic(self):
        return (self.env.lang or '').startswith('ar')

    def _export_status_labels(self):
        return dict(self.env['baseer.pos.daily.report.line']._fields['status']._description_selection(self.env))

    def _export_label(self, english, arabic):
        """Prefer explicit Arabic copy so short shared terms stay in this report."""
        return arabic if self._export_is_arabic() else english

    def _export_document(self):
        """Structured payload shared by the PDF layout and the Excel workbook."""
        self._ensure_generated()
        status_labels = self._export_status_labels()
        arabic = self._export_is_arabic()
        period = '%s – %s' % (self.date_from.isoformat(), self.date_to.isoformat())
        lines = []
        for line in self.line_ids.sorted('business_date'):
            lines.append({
                'date': line.business_date.isoformat(),
                'status': line.status,
                'status_label': status_labels.get(line.status, line.status),
                'sales': line.sales if line.has_sales else None,
                'customers': line.customers if line.has_sales else None,
                'has_sales': bool(line.has_sales),
            })
        document = {
            'title': self._export_label('Daily sales and customers', 'المبيعات والعملاء يوميًا'),
            'company': self.company_id.name,
            'currency': self.currency_id.name or 'SAR',
            'date_from': self.date_from.isoformat(),
            'date_to': self.date_to.isoformat(),
            'period': period,
            'arabic': arabic,
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M'),
            'filters': [
                {'label': self._export_label('Company', 'الشركة'), 'value': self.company_id.name},
                {'label': self._export_label('Period', 'الفترة'), 'value': period},
                {'label': self._export_label('Currency', 'العملة'), 'value': self.currency_id.name or 'SAR'},
            ],
            'kpis': [
                {'label': self._export_label('Recorded Sales', 'المبيعات المسجلة'), 'value': self.recorded_sales, 'kind': 'money'},
                {'label': self._export_label('Recorded Customers', 'العملاء المسجلون'), 'value': self.recorded_customers, 'kind': 'count'},
                {'label': self._export_label('Complete Sales', 'مبيعات الأيام المكتملة'), 'value': self.complete_sales, 'kind': 'money'},
                {'label': self._export_label('Complete Customers', 'عملاء الأيام المكتملة'), 'value': self.complete_customers, 'kind': 'count'},
                {'label': self._export_label('Average Daily Sales', 'متوسط المبيعات اليومية'), 'value': self.average_daily_sales if self.operating_days else None, 'kind': 'money'},
                {'label': self._export_label('Average Daily Customers', 'متوسط العملاء اليومي'), 'value': self.average_daily_customers if self.operating_days else None, 'kind': 'decimal'},
                {'label': self._export_label('Operating Days', 'أيام التشغيل'), 'value': self.operating_days, 'kind': 'count'},
                {'label': self._export_label('Closed Days', 'أيام الإغلاق'), 'value': self.closed_days, 'kind': 'count'},
                {'label': self._export_label('Incomplete Days', 'الأيام غير المكتملة'), 'value': self.incomplete_days, 'kind': 'count'},
                {'label': self._export_label('Missing Days', 'الأيام الناقصة'), 'value': self.missing_days, 'kind': 'count'},
            ],
            'columns': [
                {'key': 'date', 'label': self._export_label('Date', 'التاريخ')},
                {'key': 'status', 'label': self._export_label('Status', 'الحالة')},
                {'key': 'sales', 'label': self._export_label('Sales including VAT', 'المبيعات شاملة الضريبة')},
                {'key': 'customers', 'label': self._export_label('Customers', 'العملاء')},
            ],
            'lines': lines,
            'totals': {
                'label': self._export_label('Totals', 'الإجماليات'),
                'sales': self.recorded_sales,
                'customers': self.recorded_customers,
                'count': len(lines),
            },
            'note': self._export_label(
                'Each complete operating date counts once, regardless of its shifts. Closed and incomplete dates are excluded from daily averages. Recorded totals include approved entries from incomplete dates. Sales include VAT.',
                'يُحسب يوم التشغيل المكتمل مرة واحدة مهما كان عدد شفتاته. تُستبعد أيام الإغلاق والأيام غير المكتملة من المتوسطات اليومية. وتشمل الإجماليات المسجلة الملخصات المعتمدة للأيام غير المكتملة. المبيعات شاملة للضريبة.',
            ),
            'font_regular': _font_data_uri('baseer_report_layout/static/fonts/IBMPlexSansArabic-Regular.ttf'),
            'font_bold': _font_data_uri('baseer_report_layout/static/fonts/IBMPlexSansArabic-Bold.ttf'),
        }
        document['kpi_rows'] = [
            document['kpis'][index:index + 2]
            for index in range(0, len(document['kpis']), 2)
        ]
        return document

    def action_export_pdf(self):
        self._ensure_generated()
        return self.env.ref('baseer_pos_summary.action_daily_sales_pdf').report_action(self, config=False)

    def action_export_xlsx(self):
        self._ensure_generated()
        content, filename = self._export_xlsx_bytes()
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'raw': content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'new',
        }

    def _export_xlsx_bytes(self):
        document = self._export_document()
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True, 'default_date_format': 'YYYY-MM-DD'})
        sheet = workbook.add_worksheet(_sheet_name(document['title']))
        if document['arabic']:
            sheet.right_to_left()

        font_name = 'IBM Plex Sans Arabic'
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 16, 'font_name': font_name,
            'align': 'right' if document['arabic'] else 'left',
        })
        text_fmt = workbook.add_format({
            'font_name': font_name,
            'align': 'right' if document['arabic'] else 'left', 'valign': 'vcenter',
        })
        label_fmt = workbook.add_format({
            'bold': True, 'font_name': font_name,
            'align': 'right' if document['arabic'] else 'left', 'valign': 'vcenter',
        })
        header_fmt = workbook.add_format({
            'bold': True, 'font_name': font_name,
            'bg_color': '#25364B', 'font_color': '#FFFFFF', 'border': 1,
            'align': 'center', 'valign': 'vcenter',
        })
        money_fmt = workbook.add_format({
            'num_format': '#,##0.00', 'font_name': font_name,
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        count_fmt = workbook.add_format({
            'num_format': '#,##0', 'font_name': font_name,
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        decimal_fmt = workbook.add_format({
            'num_format': '#,##0.00', 'font_name': font_name,
            'align': 'right', 'valign': 'vcenter', 'border': 1,
        })
        date_fmt = workbook.add_format({
            'num_format': 'YYYY-MM-DD', 'font_name': font_name,
            'align': 'center', 'valign': 'vcenter', 'border': 1,
        })
        cell_fmt = workbook.add_format({
            'font_name': font_name,
            'align': 'right' if document['arabic'] else 'left', 'valign': 'vcenter', 'border': 1,
        })
        total_label_fmt = workbook.add_format({
            'bold': True, 'font_name': font_name,
            'bg_color': '#D9DDE0', 'border': 1, 'valign': 'vcenter',
            'align': 'right' if document['arabic'] else 'left',
        })
        total_money_fmt = workbook.add_format({
            'bold': True, 'num_format': '#,##0.00', 'font_name': font_name,
            'bg_color': '#D9DDE0', 'border': 1, 'align': 'right',
        })
        total_count_fmt = workbook.add_format({
            'bold': True, 'num_format': '#,##0', 'font_name': font_name,
            'bg_color': '#D9DDE0', 'border': 1, 'align': 'right',
        })
        note_fmt = workbook.add_format({
            'italic': True, 'font_name': font_name,
            'font_color': '#566A75', 'text_wrap': True, 'valign': 'top',
            'align': 'right' if document['arabic'] else 'left',
        })
        empty_fmt = workbook.add_format({
            'font_name': font_name,
            'align': 'right', 'valign': 'vcenter', 'border': 1, 'font_color': '#B8C1CA',
        })

        sheet.set_column(0, 0, 28)
        sheet.set_column(1, 1, 28)
        sheet.set_column(2, 2, 22)
        sheet.set_column(3, 3, 16)

        row = 0
        sheet.write(row, 0, document['title'], title_fmt)
        row += 1
        for item in document['filters']:
            sheet.write(row, 0, item['label'], label_fmt)
            sheet.write(row, 1, item['value'], text_fmt)
            row += 1
        sheet.write(row, 0, self._export_label('Generated at', 'أُنشئ في'), label_fmt)
        sheet.write(row, 1, document['generated_at'], text_fmt)
        row += 2

        sheet.write(row, 0, self._export_label('Summary', 'الملخص'), label_fmt)
        row += 1
        for kpi in document['kpis']:
            sheet.write(row, 0, kpi['label'], text_fmt)
            if kpi['value'] is None:
                sheet.write(row, 1, '—', text_fmt)
            elif kpi['kind'] == 'money':
                sheet.write_number(row, 1, float(kpi['value']), money_fmt)
            elif kpi['kind'] == 'decimal':
                sheet.write_number(row, 1, float(kpi['value']), decimal_fmt)
            else:
                sheet.write_number(row, 1, int(kpi['value']), count_fmt)
            row += 1
        row += 1

        header_row = row
        for index, column in enumerate(document['columns']):
            sheet.write(header_row, index, column['label'], header_fmt)
        row += 1
        first_data_row = row
        for line in document['lines']:
            sheet.write_datetime(row, 0, datetime.strptime(line['date'], '%Y-%m-%d'), date_fmt)
            sheet.write(row, 1, line['status_label'], cell_fmt)
            if line['has_sales']:
                sheet.write_number(row, 2, float(line['sales']), money_fmt)
                sheet.write_number(row, 3, int(line['customers']), count_fmt)
            else:
                sheet.write(row, 2, '—', empty_fmt)
                sheet.write(row, 3, '—', empty_fmt)
            row += 1
        last_data_row = row - 1
        if document['lines']:
            sheet.autofilter(header_row, 0, last_data_row, 3)
        sheet.write(row, 0, document['totals']['label'], total_label_fmt)
        sheet.write(row, 1, document['totals']['count'], total_count_fmt)
        sheet.write_number(row, 2, float(document['totals']['sales']), total_money_fmt)
        sheet.write_number(row, 3, int(document['totals']['customers']), total_count_fmt)
        row += 2
        sheet.merge_range(row, 0, row + 1, 3, document['note'], note_fmt)
        # Freeze below the column header so filters stay visible while scrolling.
        sheet.freeze_panes(header_row + 1, 0)
        workbook.close()
        filename = '%s-%s-%s.xlsx' % (
            _safe_filename(document['title']),
            document['date_from'],
            document['date_to'],
        )
        return buffer.getvalue(), filename


class PosDailySalesPDF(models.AbstractModel):
    _name = 'report.baseer_pos_summary.daily_sales_pdf'
    _description = 'Daily sales and customers PDF'

    def _get_report_values(self, docids, data=None):
        docs = self.env['baseer.pos.daily.report'].browse(docids)
        if not docs:
            raise UserError(_('Choose a daily sales report to export.'))
        documents = []
        for doc in docs:
            documents.append((doc, doc._export_document()))
        return {
            'doc_ids': list(docs.ids),
            'doc_model': 'baseer.pos.daily.report',
            'docs': docs,
            'documents': documents,
        }


def _sheet_name(name):
    cleaned = ''.join(char for char in (name or 'Report') if char not in '[]:*?/\\')
    return (cleaned or 'Report')[:31]
