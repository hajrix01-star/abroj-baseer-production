"""Tobacco register exports."""
import base64
import io
from decimal import Decimal
import xlsxwriter
from odoo import _, api, models


class TobaccoExport(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _tobacco_export_rows(self, section, show_products, show_cumulative=False):
        rows = [([self.env._('Cumulative at start'), '', '', '', '', '', '', section['opening']], 'total')] if show_cumulative else []
        balance = section['opening']
        for day in section['days']:
            rows.append(([day['date'], '', '', '', day['debit'], day['credit'], day['net'], day['cumulative']], 'day'))
            for item in (r for r in section['rows'] if r['date'][:10] == day['date']):
                balance += item['net']
                rows.append(([item['date'], item['name'], '%s × %s' % (item['product'], format(Decimal(str(item['quantity'])).normalize(), 'f')) if item['product'] else '', item['type'], max(-item['net'], 0), max(item['net'], 0), item['net'], balance], 'item'))
        rows.append(([self.env._('Total for period'), '', '', '', section['debit'], section['credit'], section['net'], ''], 'total'))
        if show_cumulative:
            rows.append(([self.env._('Cumulative at end'), '', '', '', '', '', '', section['closing']], 'total'))
        else:
            rows = [(values[:-1], kind) for values, kind in rows]
        if not show_products:
            rows = [(values[:2] + values[3:], kind)
                    for values, kind in rows]
        return rows

    @api.model
    def _export_payload(self, report_code, options):
        payload = super()._export_payload(report_code, options)
        if report_code == 'tobacco_service_fee':
            for section in payload['tobacco_sections']:
                section['export_rows'] = self._tobacco_export_rows(section, bool((options or {}).get('show_products')), bool((options or {}).get('show_cumulative')))
            payload['tobacco_show_cumulative'] = bool((options or {}).get('show_cumulative'))
            payload['tobacco_show_products'] = bool((options or {}).get('show_products'))
        return payload

    @api.model
    def export_xlsx(self, report_code, options=None):
        if report_code != 'tobacco_service_fee':
            return super().export_xlsx(report_code, options)
        payload = self._export_payload(report_code, options or {})
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(self.env._('Tobacco Service Fee')[:31])
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        if (self.env.lang or '').startswith('ar'):
            sheet.right_to_left()
        bold = workbook.add_format({'bold': True, 'bg_color': '#D8DADD'})
        money = workbook.add_format({'num_format': '#,##0.00;-#,##0.00', 'reading_order': 1})
        sheet.set_column(0, 0, 28)
        sheet.set_column(1, 3, 24)
        sheet.set_column(4, 7, 18)
        sheet.write(0, 0, payload['report']['name'], bold)
        row = 2
        for section in payload['tobacco_sections']:
            sheet.write(row, 0, '%s — %s' % (section['company'], section['account']), bold)
            row += 1
            summary = ([(self.env._('Cumulative at start'), section['opening'])] if payload['tobacco_show_cumulative'] else []) + [(self.env._('Debit'), section['debit']), (self.env._('Credit'), section['credit']), (self.env._('Net for period'), section['net'])]
            for col, (label, value) in enumerate(summary):
                sheet.write(row, col, label, bold)
                sheet.write_number(row + 1, col, value, money)
            row += 3
            labels = [self.env._('Date and Time'), self.env._('Document'), self.env._('Type'), self.env._('Debit'), self.env._('Credit'), self.env._('Net'), self.env._('Cumulative')]
            if not payload['tobacco_show_cumulative']:
                labels.pop()
            if payload['tobacco_show_products']:
                labels.insert(2, self.env._('Product and Quantity'))
            for col, label in enumerate(labels):
                sheet.write(row, col, label, bold)
            row += 1
            for values, kind in section['export_rows']:
                for col, value in enumerate(values):
                    if isinstance(value, (int, float)):
                        sheet.write_number(row, col, value, None if kind == 'count' else money)
                    else:
                        sheet.write(row, col, value, bold if kind in ('total', 'section', 'day') else None)
                row += 1
            row += 1
        workbook.close()
        return {'filename': 'tobacco_service_fee.xlsx', 'content': base64.b64encode(output.getvalue()).decode(),
                'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
