"""XLSX and PDF exports of an already computed report."""

import base64
import io

import xlsxwriter

from odoo import _, models


class BaseerReportExport(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    def export_xlsx(self, report_code, options=None):
        payload = self.get_report(report_code, options or {}, with_accounts=True)
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet = workbook.add_worksheet(_sheet_name(payload['report']['name']))
        title = workbook.add_format({'bold': True, 'font_size': 14})
        header = workbook.add_format({'bold': True, 'bg_color': '#E6EEF2'})
        section = workbook.add_format({'bold': True, 'bg_color': '#F4F7F8'})
        total = workbook.add_format({'bold': True, 'top': 1})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})
        indents = [workbook.add_format({'indent': level}) for level in range(8)]
        sheet.write(0, 0, payload['report']['name'], title)
        sheet.write(1, 0, ' · '.join(company['name'] for company in payload['companies']))
        sheet.write(2, 0, payload['currency']['code'])
        row = 4
        sheet.write(row, 0, _('Line'), header)
        for index, column in enumerate(payload['columns'], start=1):
            sheet.write(row, index, column['label'], header)
        row += 1
        for line in payload['lines']:
            if line['display'] == 'total':
                label_format, amount_format = total, money_bold
            elif line['display'] == 'section':
                label_format, amount_format = section, money_bold
            else:
                label_format = indents[min(line['level'], 7)]
                amount_format = money
            sheet.write(row, 0, line['name'], label_format)
            _write_amounts(sheet, row, line['amounts'], amount_format, label_format)
            row += 1
            for account in line['accounts']:
                detail = indents[min(line['level'] + 1, 7)]
                sheet.write(row, 0, f"{account['code']} {account['name']}".strip(), detail)
                _write_amounts(sheet, row, account['amounts'], money, detail)
                row += 1
        for note in payload['notes']:
            sheet.write(row, 0, note)
            row += 1
        sheet.set_column(0, 0, 52)
        if payload['columns']:
            sheet.set_column(1, len(payload['columns']), 18)
        sheet.freeze_panes(5, 1)
        workbook.close()
        return {
            'filename': '%s.xlsx' % payload['report']['code'].replace('_', '-'),
            'content': base64.b64encode(buffer.getvalue()).decode(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        }

    def export_pdf(self, report_code, options=None):
        self._check_report_access()
        report = self._definition(report_code)
        normalized = self._normalize_options(report, options or {})
        public_options = {key: value for key, value in normalized.items() if key != 'columns'}
        return self.env.ref('baseer_report_engine.action_report_pdf').report_action(
            report, data={'report_code': report.code, 'options': public_options},
        )


def _write_amounts(sheet, row, amounts, number_format, text_format):
    for index, amount in enumerate(amounts, start=1):
        if amount['value'] is None:
            sheet.write(row, index, amount['display'], text_format)
        else:
            sheet.write_number(row, index, float(amount['value']), number_format)


def _sheet_name(name):
    cleaned = ''.join(char for char in (name or 'Report') if char not in '[]:*?/\\')
    return (cleaned or 'Report')[:31]
