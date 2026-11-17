"""Tobacco register exports."""
import base64
import io
from decimal import Decimal
import xlsxwriter
from odoo import _, api, models


class TobaccoExport(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _tobacco_export_rows(self, section, show_products):
        rows = [([self.env._('Cumulative at start'), '', '', '', '', '', '', section['opening']], 'total')]
        balance = section['opening']
        for day in section['days']:
            rows.append(([day['date'], '', '', '', day['debit'], day['credit'], day['net'], day['cumulative']], 'day'))
            for item in (r for r in section['rows'] if r['date'][:10] == day['date']):
                balance += item['net']
                rows.append(([item['date'], item['name'], '%s × %s' % (item['product'], format(Decimal(str(item['quantity'])).normalize(), 'f')) if item['product'] else '', item['type'], max(-item['net'], 0), max(item['net'], 0), item['net'], balance], 'item'))
        rows.extend([
            ([self.env._('Total for period'), '', '', '', section['debit'], section['credit'], section['net'], ''], 'total'),
            ([self.env._('Cumulative at end'), '', '', '', '', '', '', section['closing']], 'total'),
            ([self.env._('Reconciliation')], 'section'),
            ([self.env._('Register net for period'), section['net']], 'total'),
            ([self.env._('Fee account movement in the trial balance'), section['movement']], 'total'),
            ([self.env._('Difference'), section['difference']], 'total'),
            *[([label, cause['amount'], ', '.join(map(str, cause['ids']))], 'item')
              for label, cause in zip((self.env._('Open sessions'), self.env._('Session entry cancelled'),
                  self.env._('Session entry outside the period'), self.env._('Manual journal entries'),
                  self.env._('Order total mismatches')), section['causes'])],
            ([self.env._('Unexplained'), section['unexplained']], 'total'),
        ])
        if section['exceptions']:
            rows.append(([self.env._('Document'), self.env._('Recomputed total'), self.env._('Saved total')], 'section'))
            rows.extend(([e['name'], e['computed'], e['saved']], 'item') for e in section['exceptions'])
        if not show_products:
            rows = [(values[:2] + values[3:] if len(values) == 8 else values, kind)
                    for values, kind in rows]
        return rows

    @api.model
    def _export_payload(self, report_code, options):
        payload = super()._export_payload(report_code, options)
        if report_code == 'tobacco_service_fee':
            for section in payload['tobacco_sections']:
                section['export_rows'] = self._tobacco_export_rows(section, bool((options or {}).get('show_products')))
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
            summary = [(self.env._('Cumulative at start'), section['opening']), (self.env._('Debit'), section['debit']), (self.env._('Credit'), section['credit']), (self.env._('Net for period'), section['net'])]
            for col, (label, value) in enumerate(summary):
                sheet.write(row, col, label, bold)
                sheet.write_number(row + 1, col, value, money)
            row += 3
            labels = [self.env._('Date and Time'), self.env._('Document'), self.env._('Type'), self.env._('Debit'), self.env._('Credit'), self.env._('Net'), self.env._('Cumulative')]
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
