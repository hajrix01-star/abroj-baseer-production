"""PDF and Excel exports of the daily purchases report."""

import base64
import io
import re
from decimal import Decimal

import xlsxwriter

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import file_path

from .daily_report import CUSTODY_KEY, STATUS_FILTERS


def _font_data_uri(relative_path):
    with open(file_path(relative_path), 'rb') as handle:
        return 'data:font/truetype;base64,%s' % base64.b64encode(handle.read()).decode()


def _safe_filename(name):
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '-', (name or '').strip())
    return (cleaned.strip('-') or 'daily-purchases')[:80]


def _sheet_name(name):
    cleaned = ''.join(char for char in (name or 'Report') if char not in '[]:*?/\\')
    return (cleaned or 'Report')[:31]


def _parse_money(value):
    """Parse the western-digit strings produced by ``_money`` into a float."""
    if value in (None, ''):
        return None
    return float(Decimal(str(value).replace(',', '')))


class PurchaseDailyReportExport(models.AbstractModel):
    _inherit = 'baseer.purchase.daily.report'

    def _export_is_arabic(self):
        return (self.env.lang or '').startswith('ar')

    def _export_label(self, english, arabic):
        """Prefer explicit Arabic copy so short shared terms stay in this report."""
        return arabic if self._export_is_arabic() else english

    def _export_status_label(self, status):
        return {
            'all': self._export_label('All statuses', 'كل الحالات'),
            'not_paid': self._export_label('Unpaid', 'غير مدفوعة'),
            'partial': self._export_label('Partially paid', 'مدفوعة جزئيًا'),
            'in_payment': self._export_label('In payment', 'قيد الدفع'),
            'paid': self._export_label('Paid', 'مدفوعة'),
            'reversed': self._export_label('Reversed', 'معكوسة'),
            'blocked': self._export_label('Blocked', 'موقوفة'),
            'draft': self._export_label('Drafts', 'المسودات'),
            'invoicing_legacy': self._export_label('Legacy', 'قديم'),
        }.get(status, status or '—')

    def _export_method_label(self, method, payload):
        if method == 'all':
            return self._export_label('All payment methods', 'كل طرق الدفع')
        if method == CUSTODY_KEY:
            return self._export_label('Paid via Osama', 'مدفوعة عبر أسامة')
        if method == 'cash':
            return self._export_label('Paid in cash', 'مدفوعة نقدًا')
        for card in payload.get('methods') or []:
            if card.get('key') == method:
                return card.get('label') or method
        return method

    def _export_bill_status_label(self, status):
        return self._export_status_label(status if status in STATUS_FILTERS or status == 'draft' else status)

    def _export_bills(self, date_from, date_to, status, method):
        """Every bill in the filtered range, in invoice-date order, not paginated."""
        company = self.env.company
        first, last = self._date(date_from), self._date(date_to)
        domain = self._domain(company, first, last, status)
        records = self.env['account.move'].sudo().search(domain, order='invoice_date, id')
        self._prefetch_cash_allocation(records)
        if method != 'all':
            records = records.filtered(
                lambda move: any(item['key'] == method for item in self._bill_methods(move))
            )
        entry_sources = self._entry_sources(records)
        return [self._bill_row(move, entry_sources) for move in records]

    @api.model
    def _export_document(self, date_from, date_to, status='all', method='all'):
        """Structured payload shared by the PDF layout and the Excel workbook."""
        if not isinstance(status, str) or status not in STATUS_FILTERS:
            status = 'all'
        if not self._method_key_valid(method):
            method = 'all'
        payload = self.get_days(date_from, date_to, status, method)
        table = payload['table']
        company = payload['company']
        arabic = self._export_is_arabic()
        period = '%s – %s' % (date_from, date_to)
        columns = list(table['columns'])
        show_custody = bool(table.get('show_custody'))
        rows = []
        for row in table['rows']:
            amounts = row.get('amounts') or {}
            exported = {
                'kind': row.get('kind'),
                'date': row['date'],
                'count': row['count'] if row.get('kind') == 'day' else None,
                'has_bills': bool(row.get('has_bills')),
                'amounts': {column['key']: _parse_money(amounts.get(column['key'])) for column in columns},
                'total': _parse_money(row['total']) if row.get('kind') == 'day' else None,
                'transfer': _parse_money(row['transfer']) if show_custody else None,
                'balance': _parse_money(row['balance']) if show_custody else None,
            }
            rows.append(exported)
        totals = {column['key']: _parse_money(table['totals'].get(column['key'])) or 0.0 for column in columns}
        export_columns = (
            [{'key': 'date', 'label': self._export_label('Date', 'التاريخ'), 'kind': 'date'}]
            + [{'key': 'count', 'label': self._export_label('Bills', 'الفواتير'), 'kind': 'count'}]
            + [{'key': column['key'], 'label': column['label'], 'kind': 'money'} for column in columns]
            + [{'key': 'total', 'label': self._export_label('Total', 'الإجمالي'), 'kind': 'money'}]
        )
        if show_custody:
            export_columns += [
                {'key': 'transfer', 'label': self._export_label('Transferred to custody', 'المحوّل إلى العهدة'), 'kind': 'money'},
                {'key': 'balance', 'label': self._export_label('Custody balance', 'رصيد العهدة'), 'kind': 'money'},
            ]
        bills = []
        for bill in self._export_bills(date_from, date_to, status, method):
            bills.append({
                'date': bill['date'],
                'number': bill['number'],
                'vendor': bill['vendor'],
                'status': bill['status'],
                'status_label': self._export_bill_status_label(bill['status']),
                'kind': bill['kind'],
                'amounts': {column['key']: _parse_money((bill.get('table_amounts') or {}).get(column['key'])) for column in columns},
                'total': _parse_money(bill['company_total']),
            })
        kpis = [
            {'label': self._export_label('Total purchases', 'إجمالي المشتريات'), 'value': _parse_money(table['total']) or 0.0, 'kind': 'money'},
            {'label': self._export_label('Bills', 'الفواتير'), 'value': table['count'], 'kind': 'count'},
        ]
        custody = payload.get('custody') or {}
        if show_custody and custody:
            kpis.extend([
                {'label': self._export_label('Custody in', 'وارد العهدة'), 'value': _parse_money(custody.get('funded')) or 0.0, 'kind': 'money'},
                {'label': self._export_label('Spent from custody', 'مصروف من العهدة'), 'value': _parse_money(custody.get('spent')) or 0.0, 'kind': 'money'},
                {'label': self._export_label('Remaining', 'المتبقي'), 'value': _parse_money(custody.get('remaining')) or 0.0, 'kind': 'money'},
            ])
        filters = [
            {'label': self._export_label('Company', 'الشركة'), 'value': company['name']},
            {'label': self._export_label('Period', 'الفترة'), 'value': period},
            {'label': self._export_label('Currency', 'العملة'), 'value': company['currency']},
            {'label': self._export_label('Payment status', 'حالة الدفع'), 'value': self._export_status_label(status)},
            {'label': self._export_label('Payment methods', 'طرق الدفع'), 'value': self._export_method_label(method, payload)},
        ]
        note = self._export_label(
            'Amounts in %s. Grouped by invoice date. Payment status is current.' % company['currency'],
            'المبالغ بعملة %s. مجمّعة حسب تاريخ الفاتورة. حالة الدفع الحالية.' % company['currency'],
        )
        if show_custody:
            start = (custody.get('start') or '')
            note = '%s %s' % (note, self._export_label(
                'Custody transfers are shown for reference and are not part of the purchase total. Balance counted from %s.' % start,
                'تحويلات العهدة للإيضاح وليست جزءًا من إجمالي المشتريات. يُحتسب الرصيد من %s.' % start,
            ))
        document = {
            'title': self._export_label('Daily purchases', 'تقرير المشتريات اليومي'),
            'company': company['name'],
            'company_id': company['id'],
            'currency': company['currency'],
            'date_from': date_from,
            'date_to': date_to,
            'period': period,
            'arabic': arabic,
            'generated_at': fields.Datetime.context_timestamp(self, fields.Datetime.now()).strftime('%Y-%m-%d %H:%M'),
            'filters': filters,
            'kpis': kpis,
            'columns': export_columns,
            'method_columns': columns,
            'rows': rows,
            'bills': bills,
            'show_custody': show_custody,
            'purchase_colspan': 3 + len(columns),
            'group_purchases': self._export_label('Purchases', 'المشتريات'),
            'group_custody': self._export_label('Custody fund', 'صندوق العهدة'),
            'totals': {
                'label': self._export_label('Totals', 'الإجماليات'),
                'count': table['count'],
                'amounts': totals,
                'total': _parse_money(table['total']) or 0.0,
                'transfer': _parse_money(table.get('transfer_total')) if show_custody else None,
                'balance': _parse_money(table.get('balance')) if show_custody else None,
            },
            'note': note,
            'bills_title': self._export_label('Bills in this period', 'فواتير الفترة'),
            'bill_columns': [
                {'key': 'date', 'label': self._export_label('Date', 'التاريخ'), 'kind': 'date'},
                {'key': 'number', 'label': self._export_label('Bill', 'الفاتورة'), 'kind': 'text'},
                {'key': 'vendor', 'label': self._export_label('Supplier', 'المورد'), 'kind': 'text'},
                {'key': 'status', 'label': self._export_label('Payment status', 'حالة الدفع'), 'kind': 'text'},
            ] + [{'key': column['key'], 'label': column['label'], 'kind': 'money'} for column in columns] + [
                {'key': 'total', 'label': self._export_label('Total', 'الإجمالي'), 'kind': 'money'},
            ],
            'font_regular': _font_data_uri('baseer_report_layout/static/fonts/IBMPlexSansArabic-Regular.ttf'),
            'font_bold': _font_data_uri('baseer_report_layout/static/fonts/IBMPlexSansArabic-Bold.ttf'),
        }
        document['kpi_rows'] = [
            document['kpis'][index:index + 2]
            for index in range(0, len(document['kpis']), 2)
        ]
        return document

    @api.model
    def action_export_pdf(self, date_from, date_to, status='all', method='all'):
        self._export_document(date_from, date_to, status, method)
        return {
            'type': 'ir.actions.report',
            'report_name': 'baseer_purchase_daily_report.daily_purchases_pdf',
            'report_type': 'qweb-pdf',
            'report_file': 'baseer_purchase_daily_report.daily_purchases_pdf',
            'data': {
                'date_from': date_from,
                'date_to': date_to,
                'status': status,
                'method': method,
                'company_id': self.env.company.id,
            },
            'context': dict(self.env.context),
        }

    @api.model
    def action_export_xlsx(self, date_from, date_to, status='all', method='all'):
        content, filename = self._export_xlsx_bytes(date_from, date_to, status, method)
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'raw': content,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'new',
        }

    @api.model
    def _export_xlsx_bytes(self, date_from, date_to, status='all', method='all'):
        document = self._export_document(date_from, date_to, status, method)
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True, 'default_date_format': 'YYYY-MM-DD'})
        self._write_main_sheet(workbook, document)
        self._write_bills_sheet(workbook, document)
        workbook.close()
        filename = '%s-%s-%s.xlsx' % (
            _safe_filename(document['title']),
            document['date_from'],
            document['date_to'],
        )
        return buffer.getvalue(), filename

    def _xlsx_formats(self, workbook, arabic):
        font_name = 'IBM Plex Sans Arabic'
        align = 'right' if arabic else 'left'
        return {
            'title': workbook.add_format({
                'bold': True, 'font_size': 16, 'font_name': font_name, 'align': align,
            }),
            'section': workbook.add_format({
                'bold': True, 'font_size': 12, 'font_name': font_name, 'align': align,
            }),
            'text': workbook.add_format({
                'font_name': font_name, 'align': align, 'valign': 'vcenter',
            }),
            'label': workbook.add_format({
                'bold': True, 'font_name': font_name, 'align': align, 'valign': 'vcenter',
            }),
            'header': workbook.add_format({
                'bold': True, 'font_name': font_name,
                'bg_color': '#25364B', 'font_color': '#FFFFFF', 'border': 1,
                'align': 'center', 'valign': 'vcenter', 'text_wrap': True,
            }),
            'group': workbook.add_format({
                'bold': True, 'font_name': font_name,
                'bg_color': '#3B4B5E', 'font_color': '#FFFFFF', 'border': 1,
                'align': 'center', 'valign': 'vcenter',
            }),
            'custody_header': workbook.add_format({
                'bold': True, 'font_name': font_name,
                'bg_color': '#6B3F68', 'font_color': '#FFFFFF', 'border': 1,
                'align': 'center', 'valign': 'vcenter',
            }),
            'money': workbook.add_format({
                'num_format': '#,##0.00', 'font_name': font_name,
                'align': 'right', 'valign': 'vcenter', 'border': 1,
            }),
            'count': workbook.add_format({
                'num_format': '#,##0', 'font_name': font_name,
                'align': 'right', 'valign': 'vcenter', 'border': 1,
            }),
            'date': workbook.add_format({
                'num_format': 'YYYY-MM-DD', 'font_name': font_name,
                'align': 'center', 'valign': 'vcenter', 'border': 1,
            }),
            'cell': workbook.add_format({
                'font_name': font_name, 'align': align, 'valign': 'vcenter', 'border': 1,
            }),
            'total_label': workbook.add_format({
                'bold': True, 'font_name': font_name, 'bg_color': '#D9DDE0',
                'border': 1, 'valign': 'vcenter', 'align': align,
            }),
            'total_money': workbook.add_format({
                'bold': True, 'num_format': '#,##0.00', 'font_name': font_name,
                'bg_color': '#D9DDE0', 'border': 1, 'align': 'right',
            }),
            'total_count': workbook.add_format({
                'bold': True, 'num_format': '#,##0', 'font_name': font_name,
                'bg_color': '#D9DDE0', 'border': 1, 'align': 'right',
            }),
            'note': workbook.add_format({
                'italic': True, 'font_name': font_name, 'font_color': '#566A75',
                'text_wrap': True, 'valign': 'top', 'align': align,
            }),
            'empty': workbook.add_format({
                'font_name': font_name, 'align': 'right', 'valign': 'vcenter',
                'border': 1, 'font_color': '#B8C1CA',
            }),
        }

    def _write_header_block(self, sheet, document, formats, last_col):
        row = 0
        sheet.merge_range(row, 0, row, last_col, document['title'], formats['title'])
        row += 1
        for item in document['filters']:
            sheet.write(row, 0, item['label'], formats['label'])
            sheet.write(row, 1, item['value'], formats['text'])
            row += 1
        sheet.write(row, 0, self._export_label('Generated at', 'أُنشئ في'), formats['label'])
        sheet.write(row, 1, document['generated_at'], formats['text'])
        row += 2
        for kpi_row in document['kpi_rows']:
            column = 0
            for kpi in kpi_row:
                sheet.write(row, column, kpi['label'], formats['label'])
                if kpi['value'] is None:
                    sheet.write(row, column + 1, '—', formats['text'])
                elif kpi['kind'] == 'money':
                    sheet.write_number(row, column + 1, float(kpi['value']), formats['money'])
                else:
                    sheet.write_number(row, column + 1, int(kpi['value']), formats['count'])
                column += 2
            row += 1
        row += 1
        return row

    def _write_main_sheet(self, workbook, document):
        sheet = workbook.add_worksheet(_sheet_name(document['title']))
        if document['arabic']:
            sheet.right_to_left()
        formats = self._xlsx_formats(workbook, document['arabic'])
        columns = document['columns']
        last_col = len(columns) - 1
        for index, column in enumerate(columns):
            width = 16
            if column['key'] in ('date', 'transfer', 'balance'):
                width = 22
            elif column['kind'] == 'money':
                width = 16
            sheet.set_column(index, index, width)
        row = self._write_header_block(sheet, document, formats, last_col)
        if document['show_custody']:
            purchase_last = document['purchase_colspan'] - 1
            sheet.merge_range(row, 0, row, purchase_last, document['group_purchases'], formats['group'])
            sheet.merge_range(row, purchase_last + 1, row, last_col, document['group_custody'], formats['custody_header'])
            row += 1
        header_row = row
        for index, column in enumerate(columns):
            sheet.write(row, index, column['label'], formats['header'])
        row += 1
        first_data_row = row
        from datetime import date as date_type
        for item in document['rows']:
            col = 0
            day = date_type.fromisoformat(item['date'])
            sheet.write_datetime(row, col, day, formats['date'])
            col += 1
            if item['count'] is None:
                sheet.write(row, col, '—', formats['empty'])
            else:
                sheet.write_number(row, col, int(item['count']), formats['count'])
            col += 1
            for column in document['method_columns']:
                value = item['amounts'].get(column['key'])
                if value is None:
                    sheet.write(row, col, '—', formats['empty'])
                else:
                    sheet.write_number(row, col, float(value), formats['money'])
                col += 1
            if item['total'] is None:
                sheet.write(row, col, '—', formats['empty'])
            else:
                sheet.write_number(row, col, float(item['total']), formats['money'])
            col += 1
            if document['show_custody']:
                if item['transfer'] is None:
                    sheet.write(row, col, '—', formats['empty'])
                else:
                    sheet.write_number(row, col, float(item['transfer']), formats['money'])
                col += 1
                if item['balance'] is None:
                    sheet.write(row, col, '—', formats['empty'])
                else:
                    sheet.write_number(row, col, float(item['balance']), formats['money'])
            row += 1
        last_data_row = row - 1
        if document['rows']:
            sheet.autofilter(header_row, 0, last_data_row, last_col)
        totals = document['totals']
        sheet.write(row, 0, totals['label'], formats['total_label'])
        sheet.write_number(row, 1, int(totals['count']), formats['total_count'])
        col = 2
        for column in document['method_columns']:
            sheet.write_number(row, col, float(totals['amounts'].get(column['key']) or 0.0), formats['total_money'])
            col += 1
        sheet.write_number(row, col, float(totals['total']), formats['total_money'])
        col += 1
        if document['show_custody']:
            if totals['transfer'] is None:
                sheet.write(row, col, '—', formats['empty'])
            else:
                sheet.write_number(row, col, float(totals['transfer']), formats['total_money'])
            col += 1
            if totals['balance'] is None:
                sheet.write(row, col, '—', formats['empty'])
            else:
                sheet.write_number(row, col, float(totals['balance']), formats['total_money'])
        row += 2
        if last_col >= 1:
            sheet.merge_range(row, 0, row + 1, last_col, document['note'], formats['note'])
        else:
            sheet.write(row, 0, document['note'], formats['note'])
        sheet.freeze_panes(header_row + 1, 0)
        sheet.repeat_rows(header_row, header_row)
        sheet.fit_to_pages(1, 0)
        sheet.set_landscape()
        sheet.set_paper(9)  # A4
        sheet.set_header('&R&P / &N') if not document['arabic'] else sheet.set_header('&L&P / &N')

    def _write_bills_sheet(self, workbook, document):
        sheet = workbook.add_worksheet(_sheet_name(document['bills_title']))
        if document['arabic']:
            sheet.right_to_left()
        formats = self._xlsx_formats(workbook, document['arabic'])
        columns = document['bill_columns']
        last_col = len(columns) - 1
        widths = {'date': 14, 'number': 22, 'vendor': 28, 'status': 18, 'total': 16}
        for index, column in enumerate(columns):
            sheet.set_column(index, index, widths.get(column['key'], 16))
        row = 0
        sheet.merge_range(row, 0, row, last_col, document['bills_title'], formats['title'])
        row += 1
        for item in document['filters']:
            sheet.write(row, 0, item['label'], formats['label'])
            sheet.write(row, 1, item['value'], formats['text'])
            row += 1
        row += 1
        header_row = row
        for index, column in enumerate(columns):
            sheet.write(row, index, column['label'], formats['header'])
        row += 1
        from datetime import date as date_type
        for bill in document['bills']:
            col = 0
            sheet.write_datetime(row, col, date_type.fromisoformat(bill['date']), formats['date'])
            col += 1
            sheet.write(row, col, bill['number'] or '—', formats['cell'])
            col += 1
            sheet.write(row, col, bill['vendor'] or '—', formats['cell'])
            col += 1
            sheet.write(row, col, bill['status_label'], formats['cell'])
            col += 1
            for column in document['method_columns']:
                value = bill['amounts'].get(column['key'])
                if value is None:
                    sheet.write(row, col, '—', formats['empty'])
                else:
                    sheet.write_number(row, col, float(value), formats['money'])
                col += 1
            if bill['total'] is None:
                sheet.write(row, col, '—', formats['empty'])
            else:
                sheet.write_number(row, col, float(bill['total']), formats['money'])
            row += 1
        last_data_row = row - 1
        if document['bills']:
            sheet.autofilter(header_row, 0, last_data_row, last_col)
        # Totals on the bills sheet match the purchase totals (not custody transfers).
        sheet.write(row, 0, document['totals']['label'], formats['total_label'])
        sheet.write(row, 1, '', formats['total_label'])
        sheet.write(row, 2, '', formats['total_label'])
        sheet.write_number(row, 3, int(document['totals']['count']), formats['total_count'])
        col = 4
        for column in document['method_columns']:
            sheet.write_number(row, col, float(document['totals']['amounts'].get(column['key']) or 0.0), formats['total_money'])
            col += 1
        sheet.write_number(row, col, float(document['totals']['total']), formats['total_money'])
        sheet.freeze_panes(header_row + 1, 0)
        sheet.repeat_rows(header_row, header_row)
        sheet.set_landscape()
        sheet.set_paper(9)
        sheet.fit_to_pages(1, 0)


class PurchaseDailyPDF(models.AbstractModel):
    _name = 'report.baseer_purchase_daily_report.daily_purchases_pdf'
    _description = 'Daily purchases PDF'

    def _get_report_values(self, docids, data=None):
        data = data or {}
        report = self.env['baseer.purchase.daily.report']
        date_from = data.get('date_from')
        date_to = data.get('date_to')
        if not date_from or not date_to:
            raise UserError(self.env._('Choose a daily purchases report to export.'))
        company_id = data.get('company_id') or self.env.company.id
        company = self.env['res.company'].browse(int(company_id))
        if not company.exists():
            raise UserError(self.env._('Choose a daily purchases report to export.'))
        status = data.get('status') or 'all'
        method = data.get('method') or 'all'
        scoped = report.with_company(company).with_context(
            allowed_company_ids=company.ids,
        )
        document = scoped._export_document(date_from, date_to, status, method)
        return {
            'doc_ids': [],
            'doc_model': 'baseer.purchase.daily.report',
            'docs': report.browse(),
            'documents': [document],
        }
