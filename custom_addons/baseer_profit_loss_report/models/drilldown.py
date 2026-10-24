"""Read-only signed summary composition and allocation provenance."""
from decimal import Decimal
from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.fields import Domain
from odoo.addons.baseer_reports_menu.report_drill import drill_result, exact_selector, positive_id
from odoo.addons.baseer_reports_menu.report_values import require_active_filters, source_money
from .profit_loss import EXPENSE_KEYS, SECTION_GROUPS
from ..report.profit_loss_report import LABELS

SECTIONS = {'income': 'income', 'cost_of_sales': 'expense_direct_cost', 'expense': 'expense',
            'other_income': 'income_other', 'other_expense': 'expense_other'}
FORMULAS = {
    'gross_profit': [('income', 1), ('cost_of_sales', -1)],
    'net_operating_income': [('gross_profit', 1), ('expense', -1)],
    'net_other_income': [('other_income', 1), ('other_expense', -1)],
    'net_income': [('net_operating_income', 1), ('net_other_income', 1)],
}


class ProfitLossDrill(models.AbstractModel):
    _inherit = 'baseer.profit.loss.report'

    def _drill_scope(self, filters, selector):
        require_active_filters(self.env, filters, {
            'period', 'comparison', 'journal_ids', 'date_from', 'date_to', 'period_mode', 'anchor_date',
            'period_direction', 'comparison_mode', 'comparison_count', 'comparison_order',
            'comparison_date_from', 'comparison_date_to'})
        kind = selector.get('kind') if type(selector) is dict else None
        keys = {'row': {'kind', 'row_key', 'period_key'}, 'account': {'kind', 'account_id', 'period_key'},
                'channel': {'kind', 'account_id', 'channel_key', 'period_key'}}
        if type(kind) is not str or kind not in keys:
            raise ValidationError(_('Select a valid report detail.'))
        exact_selector(selector, keys[kind])
        if kind == 'row' and (type(selector['row_key']) is not str or selector['row_key'] not in LABELS):
            raise ValidationError(_('Select a valid report row.'))
        if kind != 'row':
            positive_id(selector['account_id'])
        if kind == 'channel' and (type(selector['channel_key']) is not str or len(selector['channel_key']) > 80):
            raise ValidationError(_('Select a valid payment channel.'))
        company, _start, _end, _journals, domain = self._filters(filters, selector['period_key'])
        if kind != 'row':
            account = self.env['account.account'].with_context(active_test=False).browse(selector['account_id'])
            if not account.exists():
                raise AccessError(_('The account is not available.'))
            account.check_access('read')
            if company not in account.company_ids or (kind == 'channel' and account.account_type not in ('income', 'income_other')):
                raise AccessError(_('The account is not available in this report.'))
            domain &= Domain('account_id', '=', account.id)
        aml = self.env['account.move.line'].with_context(active_test=False)
        if aml.search_count(domain, limit=5001) > 5000:
            raise ValidationError(_('The complete detail is too large. Select a shorter period.'))
        grouped = self._section_rows(domain)
        return company, domain, grouped

    def _drill_rows(self, filters, selector):
        company, domain, grouped = self._drill_scope(filters, selector)
        currency = company.currency_id
        ar = (self.env.lang or '').startswith('ar')
        label = lambda key: LABELS[key][0 if ar else 1]
        fmt = lambda value: self._format_money(value, currency)
        columns = [{'key': 'label', 'label': 'المكوّن أو المصدر' if ar else 'Component or source'},
                   {'key': 'amount', 'label': 'المساهمة' if ar else 'Contribution', 'numeric': True}]
        period_key = selector['period_key']
        rows = []
        basis = ('مكوّنات خادمية بنفس الفترة والدفاتر. الإشارة تحدد الإضافة أو الطرح؛ لا يمثل الرقم مجموع الصفحة.' if ar else
                 'Server components for the same period and journals. Signs indicate addition or subtraction; the value is not a page total.')
        kind = selector['kind']
        if kind == 'row':
            report_rows, _totals = self._report_rows({period_key: grouped}, [{'key': period_key}], currency)
            by_key = {row['key']: row for row in report_rows}
            key = selector['row_key']
            title, value = label(key), by_key[key]['amounts'][period_key]['amount']
            if key in FORMULAS:
                for child, sign in FORMULAS[key]:
                    rows.append({'key': child, 'cells': {'label': label(child),
                        'amount': fmt(source_money(by_key[child]['amounts'][period_key]['amount']) * sign)},
                        'drill': {'kind': 'row', 'row_key': child, 'period_key': period_key}})
            else:
                section = SECTIONS[key]
                for group in SECTION_GROUPS.get(section, (section,)):
                    for item in grouped[group]:
                        account = item['account']
                        rows.append({'key': account.id, 'cells': {'label': account.display_name, 'amount': fmt(item['raw'])},
                            'drill': {'kind': 'account', 'account_id': account.id, 'period_key': period_key}})
        else:
            account = self.env['account.account'].browse(selector['account_id'])
            title = account.display_name
            if kind == 'channel':
                contributions = []
                channels = self._revenue_channels(company, domain, provenance=contributions).get(account.id, {})
                key = selector['channel_key']
                if key not in channels:
                    # A channel present in another comparison period can be zero here.
                    _company, _journals, periods, _pc, _cc = self._scope(filters)
                    found = False
                    for period in periods:
                        other_domain = period['domain'] & Domain('account_id', '=', account.id)
                        if self.env['account.move.line'].search_count(other_domain, limit=5001) > 5000:
                            raise ValidationError(_('Select a shorter period.'))
                        other_channels = self._revenue_channels(company, other_domain).get(account.id, {})
                        if key in other_channels:
                            name = other_channels[key][0]
                            found = True
                            break
                    if not found:
                        raise AccessError(_('The payment channel is not in this report.'))
                    amount = Decimal('0')
                else:
                    name, amount = channels[key]
                title += ' · ' + (name or self._unallocated_channel_label())
                value = fmt(amount)
                basis = ('توزيع إيراد الحساب على طريقة الدفع؛ المساهمة ليست إجمالي الإيصال أو القيد. غير الموزع يبقى ظاهرًا دون تخمين.' if ar else
                         'Account revenue allocated to this payment channel; each contribution is not the receipt or journal total. Unallocated revenue is retained without guessing.')
                for item in contributions:
                    if item['channel_key'] == key:
                        move = self.env['account.move'].browse(item['move_id'])
                        rows.append({'key': move.id, 'cells': {'label': move.name or '', 'amount': fmt(item['value'])},
                            'source': {'kind': 'channel_source', 'parent': dict(selector), 'move_id': move.id}})
            else:
                matches = [item for items in grouped.values() for item in items if item['account'].id == account.id]
                if not matches and account.account_type not in grouped:
                    raise AccessError(_('The account is not in this report.'))
                value = fmt(matches[0]['raw'] if matches else Decimal('0'))
                lines = self.env['account.move.line'].with_context(active_test=False).search(domain, order='date,id')
                self._verify_links(lines)
                for line in lines:
                    amount = self._decimal(line.debit) - self._decimal(line.credit)
                    if account.account_type not in EXPENSE_KEYS:
                        amount = -amount
                    rows.append({'key': line.id, 'cells': {'label': f'{line.date} · {line.move_id.name}', 'amount': fmt(amount)},
                        'source': {'kind': 'source', 'parent': dict(selector), 'line_id': line.id}})
        return title, value, basis, columns, rows

    def _get_drilldown(self, filters, selector, page=1):
        return drill_result(*self._drill_rows(filters, selector), page=page)

    def _open_drill_source(self, filters, selector):
        kind = selector.get('kind') if type(selector) is dict else None
        field = 'move_id' if kind == 'channel_source' else 'line_id'
        exact_selector(selector, {'kind', 'parent', field})
        if kind not in ('source', 'channel_source'):
            raise ValidationError(_('Select a valid source.'))
        positive_id(selector[field])
        _title, _value, _basis, _columns, rows = self._drill_rows(filters, selector['parent'])
        if not any(row.get('source') == selector for row in rows):
            raise AccessError(_('The source is not in this report detail.'))
        move = (self.env['account.move'].browse(selector[field]) if field == 'move_id' else
                self.env['account.move.line'].browse(selector[field]).move_id)
        move.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Journal Entry'), 'res_model': 'account.move',
                'res_id': move.id, 'views': [[False, 'form']], 'target': 'current'}
