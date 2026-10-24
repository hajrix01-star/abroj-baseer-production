"""Fixed read-only drill selectors for the Saudi VAT report."""

from decimal import Decimal, ROUND_HALF_UP

from odoo import _, api, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain

from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id


class TaxReportDrill(models.TransientModel):
    _inherit = 'baseer.tax.report.wizard'

    @staticmethod
    def _drill_money(value, currency):
        amount = Decimal(str(value)).quantize(
            Decimal('1').scaleb(-currency.decimal_places), rounding=ROUND_HALF_UP,
        )
        return f'{amount:,.{currency.decimal_places}f}'

    def _drill_wizard(self, filters):
        keys = {'company_id', 'period_type', 'year', 'month', 'quarter', 'display_mode', 'journal_ids'}
        if type(filters) is not dict or set(filters) != keys:
            raise ValidationError(_('Select valid report filters.'))
        if type(filters['company_id']) is not int or filters['company_id'] != self.env.company.id:
            raise AccessError(_('Select the active company report.'))
        return self._hub_wizard(filters)

    def _drill_cell(self, wizard, report, selector):
        exact_selector(selector, ('kind', 'box', 'column'))
        if selector['kind'] != 'cell' or type(selector['box']) is not str or selector['box'] not in {str(number) for number in range(1, 17)}:
            raise ValidationError(_('Select a valid VAT box.'))
        if type(selector['column']) is not str or selector['column'] not in {'base', 'tax'}:
            raise ValidationError(_('Select a valid VAT column.'))
        row = next((item for item in report['rows'] if item['number'] == selector['box']), None)
        if not row or row[selector['column']] is None:
            raise ValidationError(_('This VAT cell is not available.'))
        return row

    def _direct_lines(self, wizard, report, selector):
        row = self._drill_cell(wizard, report, selector)
        column = selector['column']
        formula = row['direct'].get(column)
        if not formula:
            return row, None, []
        tags = self.env['account.account.tag']._get_tax_tags(
            formula, wizard.company_id.account_fiscal_country_id.id,
        )
        domain = wizard._base_domain() & Domain('tax_tag_ids', 'in', tags.ids)
        lines = self.env['account.move.line'].search(domain, order='date,id', limit=5001)
        if len(lines) > 5000:
            raise ValidationError(_('The complete detail is too large. Select a shorter period.'))
        lines.check_access('read')
        lines.check_access_rule('read')
        for records in (lines.mapped('move_id'), lines.mapped('journal_id'), lines.mapped('account_id')):
            records.check_access('read')
            records.check_access_rule('read')
        sign = Decimal('-1') if formula.startswith('-') else Decimal('1')
        quantum = Decimal('1').scaleb(-wizard.company_id.currency_id.decimal_places)
        total = sum((Decimal(str(line.balance)) * sign for line in lines), Decimal('0')).quantize(
            quantum, rounding=ROUND_HALF_UP,
        )
        if total != row[column]:
            raise AccessError(_('The complete VAT source is not available.'))
        return row, sign, lines

    def _exception_lines(self, wizard, report, selector):
        exact_selector(selector, ('kind', 'class'))
        if selector['kind'] != 'exception' or type(selector['class']) is not str or selector['class'] not in {'vat', 'other'}:
            raise ValidationError(_('Select a valid VAT exception.'))
        exception = wizard._untagged_vat(wizard._base_domain())
        domain = exception['domain'] if selector['class'] == 'vat' else exception['other_domain']
        expected = exception['amount'] if selector['class'] == 'vat' else exception['other_amount']
        lines = self.env['account.move.line'].search(domain, order='date,id', limit=5001)
        if len(lines) > 5000:
            raise ValidationError(_('The complete detail is too large. Select a shorter period.'))
        lines.check_access('read')
        lines.check_access_rule('read')
        for records in (lines.mapped('move_id'), lines.mapped('journal_id'), lines.mapped('account_id')):
            records.check_access('read')
            records.check_access_rule('read')
        total = sum((Decimal(str(line.balance)) for line in lines), Decimal('0'))
        if total != expected:
            raise AccessError(_('The complete VAT source is not available.'))
        return lines, expected

    def _source_rows(self, wizard, report, selector, lines, sign=Decimal('1')):
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        columns = [
            {'key': 'date', 'label': 'التاريخ' if ar else 'Date'},
            {'key': 'entry', 'label': 'القيد' if ar else 'Entry'},
            {'key': 'account', 'label': 'الحساب' if ar else 'Account'},
            {'key': 'amount', 'label': 'المبلغ' if ar else 'Amount', 'numeric': True},
        ]
        currency = wizard.company_id.currency_id
        rows = []
        for line in lines:
            rows.append({
                'key': str(line.id),
                'cells': {'date': line.date.isoformat(), 'entry': line.move_id.name or line.move_id.ref or '',
                          'account': line.account_id.display_name,
                          'amount': self._drill_money(Decimal(str(line.balance)) * sign, currency)},
                'source': {'kind': 'source', 'parent': dict(selector), 'line_id': line.id},
            })
        return columns, rows

    @api.model
    def _get_drilldown(self, filters, selector, page):
        wizard = self._drill_wizard(filters)
        report = wizard._build_report()
        ar = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        basis = ('قيود مرحلة ضمن الفترة والدفاتر المحددة، وفق خانات ضريبة القيمة المضافة الحالية.' if ar
                 else 'Posted entries in the selected period and journals under the current VAT box definition.')
        if type(selector) is not dict or type(selector.get('kind')) is not str:
            raise ValidationError(_('Select a valid VAT detail.'))
        if selector['kind'] == 'exception':
            lines, total = self._exception_lines(wizard, report, selector)
            columns, rows = self._source_rows(wizard, report, selector, lines)
            title = (('قيود ضريبة غير مصنفة' if ar else 'Untagged VAT entries') if selector['class'] == 'vat'
                     else ('رسوم وضرائب أخرى غير موسومة' if ar else 'Other untagged taxes'))
            return drill_result(title, self._drill_money(total, wizard.company_id.currency_id), basis, columns, rows, page)
        row, sign, lines = self._direct_lines(wizard, report, selector)
        title = ('الخانة %s — %s' % (selector['box'], selector['column']))
        if sign is not None:
            columns, rows = self._source_rows(wizard, report, selector, lines, sign)
            return drill_result(title, self._drill_money(row[selector['column']], wizard.company_id.currency_id), basis,
                                columns, rows, page)
        components = row['components'].get(selector['column'], [])
        basis += (' المكونات تحمل الإشارات المؤدية إلى الإجمالي؛ فتح المكوّن يعرض مصدر خانته الأصلية.' if ar
                  else ' Component values retain the signs used to form the aggregate; opening a component shows its original cell source.')
        columns = [{'key': 'box', 'label': 'الخانة' if ar else 'Box'},
                   {'key': 'name', 'label': 'البيان' if ar else 'Description'},
                   {'key': 'amount', 'label': 'المبلغ' if ar else 'Amount', 'numeric': True}]
        rows = [{
            'key': '%s:%s' % (item['number'], item['column']),
            'cells': {'box': item['number'], 'name': item['name'], 'amount': item['amount_text']},
            'drill': {'kind': 'cell', 'box': item['number'], 'column': item['column']},
        } for item in components]
        return drill_result(title, self._drill_money(row[selector['column']], wizard.company_id.currency_id), basis,
                            columns, rows, page)

    @api.model
    def _open_drill_source(self, filters, selector):
        exact_selector(selector, ('kind', 'parent', 'line_id'))
        if selector['kind'] != 'source' or type(selector['parent']) is not dict:
            raise ValidationError(_('Select a valid source.'))
        line_id = positive_id(selector['line_id'])
        wizard = self._drill_wizard(filters)
        report = wizard._build_report()
        parent = selector['parent']
        if parent.get('kind') == 'exception':
            lines, _exception_total = self._exception_lines(wizard, report, parent)
        else:
            _row, sign, lines = self._direct_lines(wizard, report, parent)
            if sign is None:
                raise ValidationError(_('Open a component source, not an aggregated VAT cell.'))
        if line_id not in lines.ids:
            raise AccessError(_('The journal item is not available in this report.'))
        line = self.env['account.move.line'].browse(line_id).exists()
        line.check_access('read')
        line.check_access_rule('read')
        return {'type': 'ir.actions.act_window', 'name': _('Journal Items'),
                'res_model': 'account.move.line', 'view_mode': 'list,form',
                'domain': [('id', '=', line.id)], 'target': 'current'}
