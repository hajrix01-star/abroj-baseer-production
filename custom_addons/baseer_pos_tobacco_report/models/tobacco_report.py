from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from odoo import _, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


RIYADH = ZoneInfo('Asia/Riyadh')
MAX_REPORT_LINES = 5000
WESTERN_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


class TobaccoReportTooLarge(ValidationError):
    """The selected period exceeds the bounded operational report size."""


def _western(value):
    return str(value).translate(WESTERN_DIGITS)


def _money(value, quantum):
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _format_money(value):
    return _western(f'{value:,.2f}')


class BaseerPosTobaccoReport(models.AbstractModel):
    _name = 'report.baseer_pos_tobacco_report.report_pos_tobacco_fees'
    _description = 'Tobacco Fee Report'

    def _date_bounds_utc(self, wizard):
        start_local = datetime.combine(wizard.date_from, time.min, tzinfo=RIYADH)
        end_local = datetime.combine(wizard.date_to + timedelta(days=1), time.min, tzinfo=RIYADH)
        return (
            start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None),
        )

    def _order_tax_base_lines(self, order, lines=None):
        tax_model = self.env['account.tax'].with_company(order.company_id)
        source_lines = order.lines if lines is None else lines
        base_lines = source_lines.sorted('id')._prepare_tax_base_line_values()
        for base in base_lines:
            base['account_id'].check_access('read')
        tax_model._add_tax_details_in_base_lines(base_lines, order.company_id)
        tax_model._round_base_lines_tax_details(base_lines, order.company_id)
        tax_model._add_accounting_data_in_base_lines_tax_details(base_lines, order.company_id)
        return tax_model, base_lines

    def _order_fee_data(self, order, quantum, lines=None):
        tax_model, base_lines = self._order_tax_base_lines(order, lines=lines)
        refund_factor = -1 if (order.is_refund or order.amount_total < 0.0) else 1
        fee_lines = []
        for base_line in base_lines:
            line_fee = Decimal('0')
            has_tobacco_repartition = False
            for tax_data in base_line['tax_details']['taxes_data']:
                for rep_data in tax_data.get('tax_reps_data', []):
                    account = rep_data.get('account')
                    if account:
                        account.check_access('read')
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

    def _checked_tax_links(self, records, field_name):
        """Private identity-only proof for fixed native tax Many2many relations."""
        records.check_access('read')
        linked = records[field_name]
        linked.check_access('read')
        if records:
            relation = records._fields[field_name]
            records.flush_model([field_name])
            self.env.cr.execute(SQL(
                'SELECT %s,%s FROM %s WHERE %s=ANY(%s)',
                SQL.identifier(relation.column1), SQL.identifier(relation.column2),
                SQL.identifier(relation.relation), SQL.identifier(relation.column1), records.ids,
            ))
            if set(self.env.cr.fetchall()) != {
                    (record.id, child.id) for record in records for child in record[field_name]}:
                raise AccessError(_('The POS source is not available.'))
        return linked

    def _tobacco_candidates(self, orders, lines, company):
        """Screen only identities/metadata; native per-order math stays authoritative.

        A blank target can fall back to the native base account. Such orders
        must be evaluated, not assumed unrelated. Never cache across requests.
        """
        line_model = self.env['pos.order.line']
        line_model.flush_model(['order_id'])
        self.env.cr.execute('SELECT order_id,id FROM pos_order_line WHERE order_id=ANY(%s)',
                            [orders.ids])
        if set(self.env.cr.fetchall()) != {(line.order_id.id, line.id) for line in lines}:
            raise AccessError(_('The POS source is not available.'))
        if any(order.company_id != company for order in orders):
            raise AccessError(_('The POS source is not available.'))
        if any(order.currency_id != company.currency_id for order in orders):
            raise ValidationError(_('A POS order uses a different currency. Split or correct the source before reporting.'))
        positions = orders.fiscal_position_id
        positions.check_access('read')
        if any(position.company_id and position.company_id != company for position in positions):
            raise AccessError(_('The POS source is not available.'))
        original_taxes = self._checked_tax_links(lines, 'tax_ids')
        mapping_taxes = self._checked_tax_links(positions, 'tax_ids')
        self._checked_tax_links(mapping_taxes, 'original_tax_ids')
        self._checked_tax_links(original_taxes, 'fiscal_position_ids')
        all_taxes = original_taxes | mapping_taxes
        frontier = all_taxes
        while frontier:
            children = self._checked_tax_links(frontier, 'children_tax_ids')
            frontier = children - all_taxes
            all_taxes |= children
        if any(tax.company_id != company for tax in all_taxes):
            raise AccessError(_('The POS source is not available.'))
        all_repartitions = all_taxes.invoice_repartition_line_ids | all_taxes.refund_repartition_line_ids
        all_repartitions.check_access('read')
        self.env['account.tax.repartition.line'].flush_model(['tax_id'])
        self.env.cr.execute('SELECT tax_id,id FROM account_tax_repartition_line WHERE tax_id=ANY(%s)',
                            [all_taxes.ids])
        if set(self.env.cr.fetchall()) != {(rep.tax_id.id, rep.id) for rep in all_repartitions}:
            raise AccessError(_('The POS source is not available.'))
        all_repartitions.account_id.check_access('read')
        all_taxes.cash_basis_transition_account_id.check_access('read')
        candidates, tax_candidates, mapped = set(), {}, {}
        for line in lines:
            position = line.order_id.fiscal_position_id
            source_taxes = line.tax_ids
            mapping_key = (company.id, position.id, tuple(source_taxes.ids))
            if mapping_key not in mapped:
                # Exact native computed-field mapping, without writing that field
                # for thousands of noncandidate lines. Amounts still use native
                # preparation independently for every selected order below.
                mapped[mapping_key] = position.map_tax(source_taxes)
                mapped[mapping_key].check_access('read')
                if set(mapped[mapping_key].ids) - set(all_taxes.ids):
                    raise AccessError(_('The POS source is not available.'))
            taxes = mapped[mapping_key]
            key = tuple(taxes.ids)
            if key not in tax_candidates:
                flattened = taxes._flatten_taxes_and_sort_them()[0]
                flattened.check_access('read')
                if any(tax.company_id != company for tax in taxes | flattened):
                    raise AccessError(_('The POS source is not available.'))
                repartitions = (flattened.invoice_repartition_line_ids
                                | flattened.refund_repartition_line_ids)
                repartitions.check_access('read')
                tax_repartitions = repartitions.filtered(lambda item: item.repartition_type == 'tax')
                possible = bool(taxes) and not tax_repartitions
                for repartition in tax_repartitions:
                    account = repartition.with_company(company)._get_aml_target_tax_account()
                    account.check_access('read')
                    if account and company not in account.company_ids:
                        raise AccessError(_('The POS source is not available.'))
                    if not account or account.with_company(company).code == '201021':
                        possible = True
                tax_candidates[key] = possible
            if tax_candidates[key]:
                candidates.add(line.order_id.id)
        return orders.filtered(lambda order: order.id in candidates)

    def _collect_rows(self, orders, currency, quantum, lines_by_order=None):
        rows = []
        exceptions = []
        running = debit_total = credit_total = Decimal('0')
        for order in orders:
            if order.currency_id != currency:
                raise ValidationError(_('A POS order uses a different currency. Split or correct the source before reporting.'))
            fee_lines, mismatch, computed_total, saved_total = (
                self._order_fee_data(order, quantum) if lines_by_order is None else
                self._order_fee_data(order, quantum, lines=lines_by_order[order]))
            local_date = fields.Datetime.to_datetime(order.date_order).replace(
                tzinfo=timezone.utc,
            ).astimezone(RIYADH)
            date_text = _western(local_date.strftime('%d-%m-%Y %H:%M'))
            order_text = _western(order.name)
            if mismatch and fee_lines:
                exceptions.append({
                    'date': date_text,
                    'order': order_text,
                    'computed_total': _format_money(_money(computed_total, quantum)),
                    'saved_total': _format_money(_money(saved_total, quantum)),
                    '_order_id': order.id,
                    '_computed_total': _money(computed_total, quantum),
                    '_saved_total': _money(saved_total, quantum),
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
                    'products': f'{_western(line.product_id.with_context(display_default_code=False).display_name)} × {qty}',
                    'type': _('Refund') if fee < 0 else _('Sale'),
                    'debit': _format_money(debit),
                    'credit': _format_money(credit),
                    'running': _format_money(running),
                    '_order_id': order.id,
                    '_line_id': line.id,
                    '_fee': fee,
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
            raise TobaccoReportTooLarge(_('This period exceeds 5,000 POS lines. Split it into smaller reports.'))
        orders.check_access('read')
        lines = self.env['pos.order.line'].search(
            [('order_id', 'in', orders.ids)], limit=MAX_REPORT_LINES + 1,
        ) if orders else self.env['pos.order.line']
        if len(lines) > MAX_REPORT_LINES:
            raise TobaccoReportTooLarge(_('This period exceeds 5,000 POS lines. Split it into smaller reports.'))
        lines.check_access('read')

        selected_orders = self._tobacco_candidates(orders, lines, company)
        selected_lines = lines.filtered(lambda line: line.order_id in selected_orders)
        # Keep all companion lines, but do not ask Odoo to compute fields for
        # unrelated orders through a wide prefetch set during native tax math.
        lines_by_order = selected_lines.with_prefetch(selected_lines.ids).grouped('order_id')

        rows, exceptions, debit_total, credit_total, running = self._collect_rows(
            selected_orders, currency, quantum, lines_by_order=lines_by_order,
        )

        return {
            'wizard': wizard,
            'company': company,
            'from_text': _western(wizard.date_from.strftime('%d-%m-%Y')),
            'to_text': _western(wizard.date_to.strftime('%d-%m-%Y')),
            'rows': rows,
            'show_products': wizard.show_products,
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
                'title': _('Tobacco Fee Report'),
                'from': _('From:'),
                'to': _('To:'),
                'currency': _('Currency:'),
                'tax_number': _('Tax Registration Number:'),
                'date': _('Date and Time'),
                'order': _('POS Order Number'),
                'product': _('Product and Quantity'),
                'type': _('Type'),
                'debit': _('Debit'),
                'credit': _('Credit'),
                'running': _('Cumulative Total'),
                'opening': _('Period Cumulative Total at Start'),
                'empty': _('No completed POS tobacco-fee sales were found in this period.'),
                'mismatch': _('Recalculated order totals differing from saved totals'),
                'computed_total': _('Recalculated Order Total'),
                'saved_total': _('Saved Order Total'),
                'total': _('Recalculated Net Tobacco Fees for Period'),
                'rows': _('Rows'),
                'of': _('of'),
                'page': _('Page'),
                'more_differences': _('More differences are listed in the PDF.'),
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
