"""XLSX and PDF exports of an already computed report."""

import base64
import io
from datetime import date

import xlsxwriter

from odoo import _, api, models
from odoo.exceptions import ValidationError


class BaseerReportExport(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _export_payload(self, report_code, options):
        engine = self.with_context(baseer_gl_export=True)
        payload = engine.get_report(report_code, options, with_accounts=True)
        if payload['report'].get('report_kind') == 'cash_flow':
            unfolded = options.get('unfolded_lines', [])
            unfold_all = options.get('unfold_all', False)
            if type(unfold_all) is not bool or not isinstance(unfolded, list) or any(not isinstance(code, str) for code in unfolded):
                raise ValidationError(_('The report options are not valid.'))
            for line in payload['lines']:
                line['export_unfolded'] = line.get('foldable') and (unfold_all or line['code'] in unfolded)
                line['export_total_label'] = _('Total %s') % line['name']
                if not line['export_unfolded']:
                    line['accounts'] = []
            return payload
        if payload['report'].get('report_kind') not in ('partner_ledger', 'aged'):
            return payload
        unfolded = options.get('unfolded_partners', [])
        unfold_all = options.get('unfold_all', False)
        if type(unfold_all) is not bool or not isinstance(unfolded, list) or any(type(i) is not int or i < 0 for i in unfolded):
            raise ValidationError(_('The report options are not valid.'))
        normalized = engine._normalize_options(engine._definition(report_code), options)
        keys = [line['partner_id'] for line in payload['lines'] if line.get('foldable')
                and (unfold_all or line['partner_id'] in unfolded)]
        pages = engine.get_partner_items_batch(report_code, options, keys)
        for line in payload['lines']:
            if not line.get('foldable') or line['partner_id'] not in keys:
                continue
            if line['partner_id'] in pages:
                page = pages[line['partner_id']]
                line['ledger'] = {'rows': ([page['initial']] if page['initial'] else []) + page['items'],
                                  'has_more': page['has_more'], 'next_offset': page['next_offset']}
        labels = engine._labels()
        filters = [labels['account_filter'] + ' ' + payload['options']['account_filter_label']]
        for key, model, label in (('partner_ids', 'res.partner', _('Partners')), ('partner_category_ids', 'res.partner.category', _('Partner Categories'))):
            if normalized[key]:
                filters.append(label + ': ' + ', '.join(engine.env[model].browse(normalized[key]).mapped('display_name')))
        if normalized['unreconciled']:
            filters.append(labels['unreconciled_entries'])
        if not normalized['posted_only']:
            filters.append(labels['draft_entries'])
        payload['filter_line'] = ' · '.join(filters)
        return payload

    @api.model
    def export_xlsx(self, report_code, options=None):
        payload = self._export_payload(report_code, options or {})
        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {'in_memory': True})
        sheet = workbook.add_worksheet(_sheet_name(payload['report']['name']))
        if (self.env.lang or '').startswith('ar'):
            sheet.right_to_left()
        title = workbook.add_format({'bold': True, 'font_size': 14})
        header = workbook.add_format({'bold': True, 'bg_color': '#E6EEF2'})
        section = workbook.add_format({'bold': True, 'bg_color': '#D8DADD'})
        total = workbook.add_format({'bold': True, 'top': 1})
        money = workbook.add_format({'num_format': '#,##0.00'})
        money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True})
        indents = [workbook.add_format({'indent': level}) for level in range(8)]
        sheet.write(0, 0, payload['report']['name'], title)
        sheet.write(1, 0, ' · '.join(company['name'] for company in payload['companies']))
        sheet.write(2, 0, payload['currency']['code'])
        grid = bool(payload.get('column_groups'))
        grid_bold = workbook.add_format({'bold': True})
        grid_header = workbook.add_format({'align': 'center', 'border': 1, 'border_color': '#D8DADD'})
        grid_sub = workbook.add_format({'align': 'right'})
        grid_sub_shaded = workbook.add_format({'align': 'right', 'bg_color': '#F9FAFB'})
        grid_money = workbook.add_format({'num_format': '#,##0.00', 'bg_color': '#F9FAFB'})
        grid_money_bold = workbook.add_format({'num_format': '#,##0.00', 'bold': True, 'bg_color': '#F9FAFB'})
        partner = payload['report'].get('report_kind') == 'partner_ledger'
        aged = payload['report'].get('report_kind') == 'aged'
        if partner:
            sheet.write(3, 0, payload['column_groups'][0]['label'])
            sheet.write(4, 0, payload['filter_line'])
        row = 6 if partner else 4
        if payload.get('column_groups'):
            index = 1
            for group in payload['column_groups']:
                end = index + group['colspan'] - 1
                if end > index:
                    sheet.merge_range(row, index, row, end, group['label'], grid_header if grid else header)
                else:
                    sheet.write(row, index, group['label'], grid_header if grid else header)
                index = end + 1
            row += 1
        sheet.write(row, 0, '' if grid else _('Line'), grid_sub if grid else header)
        for index, column in enumerate(payload['columns'], start=1):
            sheet.write(row, index, column['label'], (grid_sub_shaded if column['figure'] == 'debit' or column['kind'] == 'end' else grid_sub) if grid else header)
        row += 1
        for line in payload['lines']:
            if (line['level'] == 0 and line['display'] == 'section') or (not grid and payload['report']['date_mode'] == 'range' and line['display'] == 'total'):
                label_format, amount_format = section, money_bold
            elif line['display'] in ('total', 'section'):
                label_format, amount_format = (grid_bold if grid else total), money_bold
            else:
                label_format = indents[min(line['level'], 7)]
                amount_format = money
            sheet.write(row, 0, line['name'], label_format)
            ledger = payload['report'].get('report_kind') == 'ledger'
            if not line.get('hide_amounts') and not line.get('export_unfolded') and not (aged and line['display'] == 'section'):
                if grid:
                    for amount_index, amount in enumerate(line['amounts']):
                        index = ([6, 7, 9][amount_index] if partner else amount_index + (4 if ledger else 2 if aged else 1))
                        col = payload['columns'][index - 1]
                        shaded = col['figure'] == 'debit' or col['kind'] == 'end'
                        fmt = (grid_money_bold if line['display'] == 'total' else grid_money) if shaded else amount_format
                        sheet.write_number(row, index, float(amount['value']), fmt)
                else:
                    _write_amounts(sheet, row, line['amounts'], amount_format, label_format)
            row += 1
            if ledger and line.get('ledger'):
                for item in line['ledger']['rows']:
                    sheet.write(row, 0, item['name'], grid_bold if item['type'] == 'total' else indents[1])
                    if item.get('date_raw'):
                        sheet.write_datetime(row, 1, date.fromisoformat(item['date_raw']), workbook.add_format({'num_format': 'yyyy-mm-dd'}))
                    sheet.write(row, 2, item.get('partner', ''))
                    sheet.write(row, 3, item.get('currency', ''))
                    for index, amount in enumerate(item['amounts'], start=4):
                        sheet.write_number(row, index, float(amount['value']), money_bold if item['type'] == 'total' else money)
                    row += 1
            if aged and line.get('ledger'):
                for item in line['ledger']['rows']:
                    sheet.write(row, 0, item['name'], indents[1])
                    sheet.write(row, 1, item.get('invoice_date', ''))
                    for index, amount in enumerate(item['amounts'], start=2):
                        sheet.write_number(row, index, float(amount['value']), money)
                    row += 1
            if partner and line.get('ledger'):
                date_format = workbook.add_format({'num_format': 'yyyy-mm-dd'})
                overdue_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'font_color': '#d23f3a'})
                for item in line['ledger']['rows']:
                    sheet.write(row, 0, item['name'], grid_bold if item['type'] == 'total' else indents[1])
                    for index, key in ((1, 'journal'), (2, 'account'), (5, 'matching'), (8, 'amount_currency')):
                        sheet.write(row, index, item.get(key, ''))
                    for index, key in ((3, 'invoice_date_raw'), (4, 'due_date_raw')):
                        if item.get(key):
                            sheet.write_datetime(row, index, date.fromisoformat(item[key]), overdue_format if index == 4 and item.get('overdue') else date_format)
                    for index, amount in zip((6, 7, 9), item['amounts']):
                        sheet.write_number(row, index, float(amount['value']), money_bold if item['type'] == 'total' else money)
                    row += 1
            for account in line.get('accounts', []):
                detail = indents[min(line['level'] + 1, 7)]
                sheet.write(row, 0, f"{account['code']} {account['name']}".strip(), detail)
                _write_amounts(sheet, row, account['amounts'], money, detail)
                row += 1
            if line.get('export_unfolded'):
                sheet.write(row, 0, _('Total %s') % line['name'], total)
                _write_amounts(sheet, row, line['amounts'], money_bold, total)
                row += 1
        for note in payload['notes']:
            sheet.write(row, 0, note)
            row += 1
        sheet.set_column(0, 0, 52)
        if payload['columns']:
            sheet.set_column(1, len(payload['columns']), 18)
        sheet.freeze_panes(8 if partner else 5, 1)
        workbook.close()
        return {
            'filename': '%s.xlsx' % payload['report']['code'].replace('_', '-'),
            'content': base64.b64encode(buffer.getvalue()).decode(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        }

    @api.model
    def export_pdf(self, report_code, options=None):
        self._check_report_access()
        report = self._definition(report_code)
        normalized = self._normalize_options(report, options or {})
        public_options = {key: value for key, value in normalized.items() if key != 'columns'}
        if report.report_kind in ('partner_ledger', 'aged'):
            public_options.update({key: (options or {}).get(key, default) for key, default in [('unfold_all', False), ('unfolded_partners', [])]})
        if report.report_kind == 'cash_flow':
            public_options.update({key: (options or {}).get(key, default) for key, default in [('unfold_all', False), ('unfolded_lines', [])]})
        if report.report_kind == 'ledger':
            public_options.update({key: (options or {}).get(key, default) for key, default in [('unfold_all', False), ('unfolded_accounts', [])]})
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
