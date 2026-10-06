from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError


RIYADH = ZoneInfo('Asia/Riyadh')
MAX_REPORT_LINES = 5000
WESTERN_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _western(value):
    return str(value).translate(WESTERN_DIGITS)


def _money(value, quantum):
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _format_money(value):
    return _western(f'{value:,.2f}')


class BaseerPosTobaccoReport(models.AbstractModel):
    _name = 'report.baseer_pos_tobacco_report.report_pos_tobacco_fees'
    _description = 'Operational POS Tobacco Fee Register'

    def _date_bounds_utc(self, wizard):
        start_local = datetime.combine(wizard.date_from, time.min, tzinfo=RIYADH)
        end_local = datetime.combine(wizard.date_to + timedelta(days=1), time.min, tzinfo=RIYADH)
        return (
            start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None),
        )

    def _order_tax_base_lines(self, order):
        tax_model = self.env['account.tax'].with_company(order.company_id)
        base_lines = order.lines.sorted('id')._prepare_tax_base_line_values()
        tax_model._add_tax_details_in_base_lines(base_lines, order.company_id)
        tax_model._round_base_lines_tax_details(base_lines, order.company_id)
        tax_model._add_accounting_data_in_base_lines_tax_details(base_lines, order.company_id)
        return tax_model, base_lines

    def _order_fee_data(self, order, quantum):
        tax_model, base_lines = self._order_tax_base_lines(order)
        refund_factor = -1 if (order.is_refund or order.amount_total < 0.0) else 1
        fee_lines = []
        for base_line in base_lines:
            line_fee = Decimal('0')
            has_tobacco_repartition = False
            for tax_data in base_line['tax_details']['taxes_data']:
                for rep_data in tax_data.get('tax_reps_data', []):
                    account = rep_data.get('account')
                    if account and account.with_company(order.company_id).code == '201021':
                        has_tobacco_repartition = True
                        line_fee += _money(rep_data['tax_amount_currency'], quantum)
            if has_tobacco_repartition:
                line = base_line['record']
                fee_lines.append((line, _money(line_fee * refund_factor, quantum)))

        cash_rounding = None
        if (
            order.config_id.cash_rounding
            and not order.config_id.only_round_cash_method
            and order.config_id.rounding_method
        ):
            cash_rounding = order.config_id.rounding_method
        tax_totals = tax_model._get_tax_totals_summary(
            base_lines=base_lines,
            currency=order.currency_id,
            company=order.company_id,
            cash_rounding=cash_rounding,
        )
        computed_total = Decimal(str(tax_totals['total_amount_currency'])) * refund_factor
        saved_total = Decimal(str(order.amount_total))
        mismatch = abs(computed_total - saved_total) > quantum / 2
        return fee_lines, mismatch, computed_total, saved_total

    def _collect_rows(self, orders, currency, quantum):
        rows = []
        exceptions = []
        running = debit_total = credit_total = Decimal('0')
        for order in orders:
            if order.currency_id != currency:
                raise ValidationError(_('A POS order uses a different currency. Split or correct the source before reporting.'))
            fee_lines, mismatch, computed_total, saved_total = self._order_fee_data(order, quantum)
            local_date = fields.Datetime.to_datetime(order.date_order).replace(
                tzinfo=timezone.utc,
            ).astimezone(RIYADH)
            date_text = _western(local_date.strftime('%d-%m-%Y %H:%M'))
            order_text = _western(order.name)
            if mismatch:
                exceptions.append({
                    'date': date_text,
                    'order': order_text,
                    'computed_total': _format_money(_money(computed_total, quantum)),
                    'saved_total': _format_money(_money(saved_total, quantum)),
                })
            for line, fee in fee_lines:
                debit = max(-fee, Decimal('0'))
                credit = max(fee, Decimal('0'))
                running += fee
                debit_total += debit
                credit_total += credit
                qty = _western(format(Decimal(str(line.qty)).normalize(), 'f'))
                rows.append({
                    'date': date_text,
                    'order': order_text,
                    'products': f'{_western(line.product_id.display_name)} × {qty}',
                    'type': _('Refund') if fee < 0 else _('Sale'),
                    'debit': _format_money(debit),
                    'credit': _format_money(credit),
                    'running': _format_money(running),
                })
        return rows, exceptions, debit_total, credit_total, running

    def _build_report(self, wizard):
        wizard.check_access('read')
        wizard._check_report_access()
        wizard._check_period()
        company = wizard.company_id
        currency = company.currency_id
        quantum = Decimal('1').scaleb(-currency.decimal_places)
        if currency.name != 'SAR' or currency.decimal_places != 2:
            raise ValidationError(_('This register requires a company currency of SAR with two decimal places.'))

        start_utc, end_utc = self._date_bounds_utc(wizard)
        order_model = self.env['pos.order']
        orders = order_model.search([
            ('company_id', '=', company.id),
            ('source', '=', 'pos'),
            ('state', 'in', ('paid', 'done')),
            ('date_order', '>=', fields.Datetime.to_string(start_utc)),
            ('date_order', '<', fields.Datetime.to_string(end_utc)),
        ], order='date_order,id', limit=MAX_REPORT_LINES + 1)
        if len(orders) > MAX_REPORT_LINES:
            raise ValidationError(_('This period exceeds 5,000 POS lines. Split it into smaller reports.'))
        orders.check_access('read')
        lines = self.env['pos.order.line'].search(
            [('order_id', 'in', orders.ids)], limit=MAX_REPORT_LINES + 1,
        ) if orders else self.env['pos.order.line']
        if len(lines) > MAX_REPORT_LINES:
            raise ValidationError(_('This period exceeds 5,000 POS lines. Split it into smaller reports.'))
        lines.check_access('read')

        rows, exceptions, debit_total, credit_total, running = self._collect_rows(
            orders, currency, quantum,
        )

        return {
            'wizard': wizard,
            'company': company,
            'from_text': _western(wizard.date_from.strftime('%d-%m-%Y')),
            'to_text': _western(wizard.date_to.strftime('%d-%m-%Y')),
            'rows': rows,
            'exceptions': exceptions,
            'opening': _format_money(Decimal('0')),
            'debit_total': _format_money(debit_total),
            'credit_total': _format_money(credit_total),
            'closing': _format_money(running),
            'exception_count': _western(len(exceptions)),
            'order_count': _western(len(rows)),
            'currency': _western(currency.name),
            'is_rtl': (self.env.user.lang or '').startswith('ar'),
            'labels': {
                'title': _('Operational POS Tobacco Fee Register'),
                'from': _('From:'),
                'to': _('To:'),
                'currency': _('Currency:'),
                'disclaimer': _('Operational report, not an accounting ledger.'),
                'method': _('Fees are recalculated from current tax settings. The running total starts at zero for this period.'),
                'exceptions': _('Orders requiring review:'),
                'date': _('Date'),
                'order': _('POS Order'),
                'product': _('Product / Quantity'),
                'type': _('Type'),
                'debit': _('Debit'),
                'credit': _('Credit'),
                'running': _('Period Running Total'),
                'opening': _('Opening within selected period'),
                'empty': _('No completed POS tobacco-fee sales were found in this period.'),
                'mismatch': _('Recalculated order totals differing from saved totals'),
                'computed_total': _('Recalculated Order Total'),
                'saved_total': _('Saved Order Total'),
                'total': _('Recalculated total for selected period'),
            },
        }

    def _get_report_values(self, docids, data=None):
        wizards = self.env['baseer.pos.tobacco.report.wizard'].browse(docids).exists()
        if len(wizards) != 1:
            raise AccessError(_('Open the tobacco fee report from its period form.'))
        report_data = self._build_report(wizards)
        return {
            'doc_ids': wizards.ids,
            'doc_model': wizards._name,
            'docs': wizards,
            'report_data': report_data,
        }
