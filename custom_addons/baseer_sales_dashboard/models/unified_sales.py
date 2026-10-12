"""Union of approved summaries, native POS, and posted Sales invoices.

Amounts and dates are resolved on the server. The pre-existing daily/shift
panels remain scoped to approved summaries; sale tender categories are unified.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import ZERO, money

from .dashboard import MAX_SOURCE_ROWS, _card, _display
from .executive import _utc_at


class UnifiedSalesDashboard(models.Model):
    _inherit = 'spreadsheet.dashboard'

    def _baseer_unified_access(self):
        """A combined headline must fail closed when any source is unreadable."""
        for name in (
            'baseer.pos.summary', 'pos.order', 'pos.session', 'pos.config',
            'account.move', 'account.move.line', 'sale.order', 'sale.order.line',
        ):
            self.env[name].check_access('read')
        if self.env.company.currency_id.name != 'SAR':
            raise ValidationError(_('Unified sales currently support SAR companies only.'))

    def _baseer_unified_pos_domain(self, company, first=None, last=None, include_bridges=False):
        domain = [
            ('company_id', '=', company.id), ('session_id.company_id', '=', company.id),
            ('state', 'in', ('paid', 'done')),
        ]
        if not include_bridges:
            domain += [
                ('baseer_summary_id', '=', False), ('source', '!=', 'baseer_summary'),
                ('session_id.baseer_summary_id', '=', False),
                ('config_id.baseer_summary_only', '=', False),
            ]
        if first and last:
            domain += [
                ('session_id.start_at', '>=', _utc_at(first, 0)),
                ('session_id.start_at', '<', _utc_at(last + timedelta(days=1), 0)),
            ]
        return domain

    def _baseer_unified_invoice_base_domain(self, company, first=None, last=None):
        # The POS links are checked globally, independent of the invoice date.
        domain = [
            ('company_id', '=', company.id), ('state', '=', 'posted'),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('invoice_line_ids.sale_line_ids', '!=', False),
            ('pos_order_ids', '=', False), ('reversed_pos_order_id', '=', False),
            # An ordinary Sales invoice has no reversal parent. Explicitly
            # admit that case: a dotted negative test alone can discard NULL
            # parents at the ORM/SQL relation join. A real reversal parent
            # must have neither kind of POS origin.
            '|', ('reversed_entry_id', '=', False),
            '&', ('reversed_entry_id.pos_order_ids', '=', False),
            ('reversed_entry_id.reversed_pos_order_id', '=', False),
        ]
        if first and last:
            domain += [('invoice_date', '>=', first), ('invoice_date', '<=', last)]
        return domain

    def _baseer_unified_deep_pos_reversal_ids(self, company, first=None, last=None):
        """Exclude POS-origin reversals at any depth, without guessing a depth limit.

        Odoo copies sale_line_ids on reversal, so a reverse of a POS credit note
        still looks like a Sales invoice. Only the exceptional multi-hop rows
        are traversed, under the same 100k source budget and ordinary ACLs.
        """
        Move = self.env['account.move']
        domain = self._baseer_unified_invoice_base_domain(company, first, last)
        domain.append(('reversed_entry_id.reversed_entry_id', '!=', False))
        if Move.search_count(domain, limit=MAX_SOURCE_ROWS + 1) > MAX_SOURCE_ROWS:
            raise ValidationError(_(
                'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.'
            ))
        candidates = Move.search(domain)
        parents = {}
        pos_origins = {}
        visited = set()
        frontier = candidates
        while frontier:
            # One batched ACL/rule-protected read per ancestry level, not one
            # ORM traversal per invoice. A foreign/inaccessible ancestor fails
            # the entire calculation rather than silently hiding an origin.
            frontier.check_access('read')
            rows = frontier.read([
                'company_id', 'reversed_entry_id', 'pos_order_ids', 'reversed_pos_order_id',
            ], load=None)
            parent_ids = set()
            pos_order_ids = set()
            for row in rows:
                company_value = row['company_id']
                company_id = company_value[0] if isinstance(company_value, (tuple, list)) else company_value
                if company_id != company.id:
                    raise ValidationError(_(
                        'An invoice reversal has an invalid origin chain. Unified sales cannot be calculated.'
                    ))
                parent_value = row['reversed_entry_id']
                parent_id = parent_value[0] if isinstance(parent_value, (tuple, list)) else parent_value
                reversed_value = row['reversed_pos_order_id']
                reversed_order_id = reversed_value[0] if isinstance(reversed_value, (tuple, list)) else reversed_value
                pos_order_ids.update(row['pos_order_ids'])
                if reversed_order_id:
                    pos_order_ids.add(reversed_order_id)
                parents[row['id']] = parent_id or False
                pos_origins[row['id']] = bool(row['pos_order_ids'] or reversed_order_id)
                if parent_id and parent_id not in visited:
                    parent_ids.add(parent_id)
            self.env['pos.order'].browse(sorted(pos_order_ids)).check_access('read')
            visited.update(frontier.ids)
            parent_ids.difference_update(visited)
            if len(visited) + len(parent_ids) > MAX_SOURCE_ROWS:
                raise ValidationError(_(
                    'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.'
                ))
            frontier = Move.browse(sorted(parent_ids))

        resolved = {}
        excluded = set()
        for invoice_id in candidates.ids:
            chain = []
            chain_seen = set()
            node = invoice_id
            while node and node not in resolved:
                if node in chain_seen or node not in parents:
                    raise ValidationError(_(
                        'An invoice reversal has an invalid origin chain. Unified sales cannot be calculated.'
                    ))
                chain.append(node)
                chain_seen.add(node)
                if pos_origins[node]:
                    break
                node = parents[node]
            pos_origin = pos_origins[node] if node and pos_origins[node] else resolved.get(node, False)
            for entry_id in chain:
                resolved[entry_id] = pos_origin
            if pos_origin:
                excluded.add(invoice_id)
        return excluded

    def _baseer_unified_invoice_domain(self, company, first=None, last=None):
        domain = self._baseer_unified_invoice_base_domain(company, first, last)
        excluded = self._baseer_unified_deep_pos_reversal_ids(company, first, last)
        if excluded:
            domain.append(('id', 'not in', sorted(excluded)))
        return domain

    def _baseer_unified_missing_dates(self, company):
        POS = self.env['pos.order']
        if POS.search_count(self._baseer_unified_pos_domain(company, include_bridges=True)
                            + [('session_id.start_at', '=', False)], limit=1):
            raise ValidationError(_(
                'A confirmed POS order has no session opening time; its sales day cannot be determined.'
            ))
        Move = self.env['account.move']
        if Move.search_count(self._baseer_unified_invoice_domain(company)
                             + [('invoice_date', '=', False)], limit=1):
            raise ValidationError(_(
                'A posted Sales invoice has no invoice date; its sales day cannot be determined.'
            ))

    def _baseer_source_bounds(self):
        """Include all three sources in the native All time/open-range filters."""
        self._baseer_unified_access()
        company = self.env.company
        self._baseer_unified_missing_dates(company)
        self._baseer_unified_validate_bridges(company, None, None)
        manual_first, manual_last = super()._baseer_source_bounds()
        bounds = [day for day in (manual_first, manual_last) if day]

        POS = self.env['pos.order']
        groups = POS._read_group(
            self._baseer_unified_pos_domain(company), ['session_id'], [],
            limit=MAX_SOURCE_ROWS + 1,
        )
        if len(groups) > MAX_SOURCE_ROWS:
            raise ValidationError(_(
                'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.'
            ))
        sessions = self.env['pos.session'].browse([row[0].id for row in groups if row[0]])
        sessions.check_access('read')
        for session in sessions:
            if not session.start_at:
                raise ValidationError(_('A confirmed POS order has no session opening time.'))
            bounds.append(fields.Datetime.context_timestamp(
                self.with_context(tz='Asia/Riyadh'), session.start_at,
            ).date())

        Move = self.env['account.move']
        invoice_domain = self._baseer_unified_invoice_domain(company)
        for order in ('invoice_date asc, id asc', 'invoice_date desc, id desc'):
            invoice = Move.search(invoice_domain, order=order, limit=1)
            if invoice:
                bounds.append(invoice.invoice_date)
        return (min(bounds), max(bounds)) if bounds else (None, None)

    def _baseer_check_capacity(self, company, periods):
        super()._baseer_check_capacity(company, periods)
        self._baseer_unified_access()
        self._baseer_unified_missing_dates(company)
        remaining = MAX_SOURCE_ROWS
        for first, last in periods:
            if not first or not last:
                continue
            domains = (
                ('baseer.pos.summary', [
                    ('company_id', '=', company.id), ('state', '=', 'approved'),
                    ('business_date', '>=', first), ('business_date', '<=', last),
                ]),
                ('pos.order', self._baseer_unified_pos_domain(company, first, last)),
                ('account.move', self._baseer_unified_invoice_domain(company, first, last)),
            )
            for name, domain in domains:
                count = self.env[name].search_count(domain, limit=remaining + 1)
                remaining -= count
                if remaining < 0:
                    raise ValidationError(_(
                        'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.'
                    ))

    def _baseer_unified_validate_bridges(self, company, first, last):
        POS = self.env['pos.order']
        raw = self._baseer_unified_pos_domain(company, first, last, include_bridges=True)
        linked_domain = raw + [
            '|', '|', '|', ('baseer_summary_id', '!=', False),
            ('source', '=', 'baseer_summary'),
            ('session_id.baseer_summary_id', '!=', False),
            ('config_id.baseer_summary_only', '=', True),
        ]
        if POS.search_count(linked_domain, limit=MAX_SOURCE_ROWS + 1) > MAX_SOURCE_ROWS:
            raise ValidationError(_(
                'This report exceeds 100,000 source rows. Choose a shorter period; no records have been omitted.'
            ))
        linked = POS.search(linked_domain)
        for order in linked:
            summary = order.baseer_summary_id or order.session_id.baseer_summary_id
            if (not summary or summary.state != 'approved' or summary.order_id != order
                    or summary.session_id != order.session_id
                    or order.session_id.baseer_summary_id != summary
                    or order.config_id != summary.config_id
                    or order.session_id.config_id != summary.config_id
                    or summary.config_id.company_id != company
                    or order.company_id != company or summary.company_id != company
                    or summary.currency_id != company.currency_id
                    or order.currency_id != company.currency_id
                    or money(order.amount_total) != money(summary.amount_gross)
                    or not order.config_id.baseer_summary_only
                    or order.source != 'baseer_summary'):
                raise ValidationError(_(
                    'A POS order has an inconsistent approved-summary link. Unified sales cannot be calculated.'
                ))

    def _baseer_unified_period(self, company, first, last):
        totals = {'manual': ZERO, 'pos': ZERO, 'restaurant': ZERO, 'sales': ZERO}
        by_day = defaultdict(lambda: ZERO)
        sale_days = set()
        new_days = set()
        new_count = 0
        guests = {'known_count': 0, 'known_rows': 0, 'missing_rows': 0,
                  'by_day': defaultdict(lambda: {'known_count': 0, 'known_rows': 0, 'missing_rows': 0}),
                  'sale_days': set()}
        if not first or not last:
            return {'totals': totals, 'by_day': by_day, 'sale_days': sale_days,
                    'new_days': new_days, 'new_count': 0, 'guests': guests,
                    'summaries': self.env['baseer.pos.summary'],
                    'orders': self.env['pos.order'], 'invoices': self.env['account.move']}

        summaries = self.env['baseer.pos.summary'].search([
            ('company_id', '=', company.id), ('state', '=', 'approved'),
            ('business_date', '>=', first), ('business_date', '<=', last),
        ])
        # A summary is keyed by business_date, while its generated POS session
        # may have a different opening date. Validate this side of the bridge
        # independently of the POS-period search before excluding its order.
        summaries.mapped('order_id').check_access('read')
        summaries.mapped('session_id').check_access('read')
        for summary in summaries:
            order, session = summary.order_id, summary.session_id
            if not order and not session and money(summary.amount_gross) == ZERO:
                # Native zero-sales approvals intentionally create no POS
                # session/order; their zero remains a legitimate record.
                by_day[summary.business_date] += ZERO
                sale_days.add(summary.business_date)
                guests['known_rows'] += 1
                guests['by_day'][summary.business_date]['known_rows'] += 1
                continue
            if (not order or not session or summary.currency_id != company.currency_id
                    or order.company_id != company or session.company_id != company
                    or order.state not in ('paid', 'done')
                    or order.baseer_summary_id != summary
                    or session.baseer_summary_id != summary
                    or order.session_id != session or session.order_ids != order
                    or order.config_id != summary.config_id
                    or session.config_id != summary.config_id
                    or summary.config_id.company_id != company
                    or order.currency_id != company.currency_id
                    or money(order.amount_total) != money(summary.amount_gross)
                    or not summary.config_id.baseer_summary_only
                    or order.source != 'baseer_summary'):
                raise ValidationError(_(
                    'An approved summary has an inconsistent generated POS order. Unified sales cannot be calculated.'
                ))
            amount = money(summary.amount_gross)
            totals['manual'] += amount
            by_day[summary.business_date] += amount
            sale_days.add(summary.business_date)
            if amount > ZERO:
                guests['sale_days'].add(summary.business_date)
                row = guests['by_day'][summary.business_date]
                if summary.customer_count > 0:
                    guests['known_count'] += summary.customer_count
                    guests['known_rows'] += 1
                    row['known_count'] += summary.customer_count
                    row['known_rows'] += 1
                else:
                    guests['missing_rows'] += 1
                    row['missing_rows'] += 1

        self._baseer_unified_validate_bridges(company, first, last)
        orders = self.env['pos.order'].search(self._baseer_unified_pos_domain(company, first, last))
        has_guest_field = bool(orders._fields.get('customer_count'))
        has_refund_field = bool(orders._fields.get('is_refund'))
        orders.mapped('session_id').check_access('read')
        orders.mapped('config_id').check_access('read')
        for order in orders:
            if not order.session_id.start_at:
                raise ValidationError(_('A confirmed POS order has no session opening time.'))
            if order.currency_id != company.currency_id:
                raise ValidationError(_(
                    'A POS order uses another currency; unified SAR sales cannot silently convert it.'
                ))
            day = fields.Datetime.context_timestamp(
                self.with_context(tz='Asia/Riyadh'), order.session_id.start_at,
            ).date()
            amount = money(order.amount_total)
            key = 'restaurant' if order.config_id.module_pos_restaurant else 'pos'
            totals[key] += amount
            by_day[day] += amount
            sale_days.add(day)
            new_days.add(day)
            new_count += 1
            if amount > ZERO and not (has_refund_field and order.is_refund):
                guests['sale_days'].add(day)
                row = guests['by_day'][day]
                if has_guest_field and order.customer_count > 0:
                    guests['known_count'] += order.customer_count
                    guests['known_rows'] += 1
                    row['known_count'] += order.customer_count
                    row['known_rows'] += 1
                else:
                    guests['missing_rows'] += 1
                    row['missing_rows'] += 1

        invoices = self.env['account.move'].search(
            self._baseer_unified_invoice_domain(company, first, last),
        )
        for invoice in invoices:
            if not invoice.invoice_date:
                raise ValidationError(_('A posted Sales invoice has no invoice date.'))
            # amount_total_signed is Odoo's signed amount in company currency;
            # a customer credit note is negative without a custom residual.
            amount = money(invoice.amount_total_signed)
            totals['sales'] += amount
            by_day[invoice.invoice_date] += amount
            sale_days.add(invoice.invoice_date)
            new_days.add(invoice.invoice_date)
            new_count += 1
            if amount > ZERO:
                guests['sale_days'].add(invoice.invoice_date)
                guests['missing_rows'] += 1
                guests['by_day'][invoice.invoice_date]['missing_rows'] += 1
        return {'totals': totals, 'by_day': by_day, 'sale_days': sale_days,
                'new_days': new_days, 'new_count': new_count, 'guests': guests,
                'summaries': summaries, 'orders': orders, 'invoices': invoices}

    def _baseer_unified_action(self, company, first, last, key):
        if key == 'manual':
            return self._baseer_source_action(company, first, last)
        if key in ('pos', 'restaurant'):
            domain = self._baseer_unified_pos_domain(company, first, last)
            domain += [('config_id.module_pos_restaurant', '=', key == 'restaurant')]
            name, model = _('Point of Sale orders'), 'pos.order'
        else:
            domain = self._baseer_unified_invoice_domain(company, first, last)
            name, model = _('Sales invoices'), 'account.move'
        if not first or not last:
            domain.append(('id', '=', False))
        return {
            'type': 'ir.actions.act_window', 'name': name,
            'res_model': model, 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': domain,
            'context': {'create': False, 'allowed_company_ids': [company.id]},
        }

    def _baseer_unified_tender_action(self, company, key, ids):
        model, name = (
            ('baseer.pos.summary.allocation', _('Approved payment allocations'))
            if key == 'summary' else ('pos.payment', _('Point of Sale payments'))
        )
        return {
            'type': 'ir.actions.act_window', 'name': name,
            'res_model': model, 'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', sorted(ids)), ('company_id', '=', company.id)],
            'context': {'create': False, 'allowed_company_ids': [company.id]},
        }

    def _baseer_unified_payment_performance(self, company, period, sales_total):
        """Recorded sale tender, never a claim of bank/platform collection."""
        translate = self.env._
        for model in ('baseer.pos.summary.allocation', 'pos.payment',
                      'pos.payment.method', 'baseer.pos.payment.category'):
            self.env[model].check_access('read')
        # Source-row cap does not bound payment splits: one order can carry
        # many tender lines. Check the union budget before traversing either
        # relation, rather than silently truncating a payment category.
        summary_lines = self.env['baseer.pos.summary.allocation'].search_count(
            [('summary_id', 'in', period['summaries'].ids), ('company_id', '=', company.id)],
            limit=MAX_SOURCE_ROWS + 1,
        ) if period['summaries'] else 0
        remaining = MAX_SOURCE_ROWS - summary_lines
        pos_lines = self.env['pos.payment'].search_count(
            [('pos_order_id', 'in', period['orders'].ids), ('company_id', '=', company.id)],
            limit=max(remaining, 0) + 1,
        ) if period['orders'] else 0
        if summary_lines + pos_lines > MAX_SOURCE_ROWS:
            raise ValidationError(_(
                'This report exceeds 100,000 payment rows. Choose a shorter period; no records have been omitted.'
            ))
        by_method = {}
        by_category = {}
        settlement_difference = ZERO
        absolute_difference = ZERO
        mismatched_count = 0
        unclassified_count = 0
        covered_summary_count = 0
        missing_summary_count = 0
        mismatched_summary_count = 0
        covered_sales = ZERO

        def add_tender(method, amount, source, source_id):
            nonlocal unclassified_count
            method.check_access('read')
            if method.company_id != company:
                raise ValidationError(translate('A sale tender method belongs to another company.'))
            # Archived categories remain historically classified by their
            # stored ID/name. Active status governs new configuration only.
            category = method.with_context(active_test=False).baseer_category_id
            if category:
                category.check_access('read')
                if category.company_id != company:
                    raise ValidationError(translate('A sale tender category belongs to another company.'))
            if not category:
                category_id, category_name, kind = -1, translate('Unclassified'), 'unclassified'
                unclassified_count += 1
            else:
                category_id, category_name, kind = category.id, category.name, category.kind
            method_bucket = by_method.setdefault(method.id, {
                'name': method.name, 'category_id': category_id, 'category_name': category_name,
                'kind': kind, 'sales': ZERO, 'source_ids': defaultdict(set),
            })
            if method_bucket['category_id'] != category_id:
                raise ValidationError(translate('A sale tender method changed category during reporting.'))
            method_bucket['sales'] += amount
            method_bucket['source_ids'][source].add(source_id)
            category_bucket = by_category.setdefault(category_id, {
                'name': category_name, 'kind': kind, 'sales': ZERO,
                'source_ids': defaultdict(set),
            })
            category_bucket['sales'] += amount
            category_bucket['source_ids'][source].add(source_id)

        def reconcile(gross, tender):
            nonlocal settlement_difference, absolute_difference, mismatched_count
            difference = money(gross - tender)
            settlement_difference += difference
            absolute_difference += abs(difference)
            if difference:
                mismatched_count += 1
            return not difference

        for summary in period['summaries']:
            lines = summary.allocation_ids
            lines.check_access('read')
            tender = ZERO
            for line in lines:
                if line.company_id != company or line.currency_id != company.currency_id:
                    raise ValidationError(_('A summary tender allocation has another company or currency.'))
                amount = money(line.amount)
                tender += amount
                if amount:
                    add_tender(line.payment_method_id, amount, 'summary', line.id)
            gross = money(summary.amount_gross)
            if not lines and gross > ZERO:
                missing_summary_count += 1
            elif reconcile(gross, tender):
                covered_summary_count += 1
                covered_sales += gross
                continue
            else:
                mismatched_summary_count += 1
            # Missing allocations also contribute an explicit per-source
            # difference, rather than a made-up headline minus category sum.
            if not lines and gross > ZERO:
                reconcile(gross, ZERO)

        for order in period['orders']:
            payments = order.payment_ids
            payments.check_access('read')
            tender = ZERO
            for payment in payments:
                if payment.company_id != company or payment.currency_id != company.currency_id:
                    raise ValidationError(_('A POS tender payment has another company or currency.'))
                amount = money(payment.amount)
                tender += amount
                if amount:
                    add_tender(payment.payment_method_id, amount, 'pos', payment.id)
            gross = money(order.amount_total)
            if reconcile(gross, tender):
                covered_sales += gross

        invoice_unknown = period['totals']['sales']
        unclassified_sales = by_category.get(-1, {}).get('sales', ZERO)
        complete = not (mismatched_count or unclassified_count or period['invoices'])
        shares_available = complete and sales_total > ZERO
        category_result = self._baseer_category_performance(by_category, sales_total, shares_available)

        def actions(source_ids):
            return [
                {'key': key, 'name': translate('Summary allocations') if key == 'summary'
                 else translate('POS payments'),
                 'action': self._baseer_unified_tender_action(company, key, ids)}
                for key, ids in (('summary', source_ids.get('summary', set())),
                                 ('pos', source_ids.get('pos', set()))) if ids
            ]

        rows = []
        for method_id, bucket in sorted(by_method.items()):
            category = {'id': bucket['category_id'], 'name': bucket['category_name'],
                        'kind': bucket['kind']}
            rows.append({
                'method_id': method_id, 'name': bucket['name'], 'category': category,
                'sales': _card(bucket['sales']),
                'share': _card(bucket['sales'] * Decimal(100) / sales_total
                               if shares_available else None, shares_available),
                'source_actions': actions(bucket['source_ids']),
            })
        for row in category_result['rows']:
            row['source_actions'] = actions(by_category[row['category_id']]['source_ids'])
        application_sales = sum((bucket['sales'] for bucket in by_category.values()
                                 if bucket['kind'] == 'platform'), ZERO)
        invoice_card = _card(invoice_unknown)
        difference_card = _card(settlement_difference)
        unclassified_card = _card(unclassified_sales)
        coverage = {
            'complete': complete, 'summary_count': len(period['summaries']),
            'pos_order_count': len(period['orders']), 'invoice_count': len(period['invoices']),
            'covered_summary_count': covered_summary_count,
            'missing_summary_count': missing_summary_count,
            'mismatched_summary_count': mismatched_summary_count,
            'mismatched_source_count': mismatched_count,
            'unclassified_line_count': unclassified_count,
            'covered_sales': _card(covered_sales),
            'uncovered_sales': _card(None, False),
            'settlement_difference': difference_card,
            'settlement_difference_absolute': _card(absolute_difference),
            'invoice_tender_unknown': invoice_card,
            'unclassified_sales': unclassified_card,
        }
        return {
            'rows': rows, 'categories': category_result['rows'],
            'chart_categories': category_result['chart_rows'],
            'category_performance': category_result['performance'],
            'application_share': _card(
                application_sales * Decimal(100) / sales_total if shares_available else None,
                shares_available,
            ),
            'coverage': coverage,
            'invoice_tender_unknown': invoice_card,
            'settlement_difference': difference_card,
            'unclassified_sales': unclassified_card,
        }

    @api.readonly
    def get_baseer_sales_metrics(self, filters=None):
        payload = super().get_baseer_sales_metrics(filters=filters)
        company = self.env.company
        self._baseer_unified_access()
        first = fields.Date.to_date(payload['filters']['date_from'])
        last = fields.Date.to_date(payload['filters']['date_to'])
        previous_first = fields.Date.to_date(payload['comparison_period']['date_from'])
        previous_last = fields.Date.to_date(payload['comparison_period']['date_to'])
        current = self._baseer_unified_period(company, first, last)
        previous = self._baseer_unified_period(company, previous_first, previous_last)
        # The existing daily report is the monetary authority for approved
        # summaries. The union must never silently disagree with its subtotal.
        manual_original = Decimal(str(payload['cards']['sales']['value']))
        if money(manual_original) != money(current['totals']['manual']):
            raise ValidationError(_(
                'Approved-summary sales disagree with the daily report. Unified sales cannot be calculated.'
            ))
        current_total = sum(current['totals'].values(), ZERO)
        previous_total = sum(previous['totals'].values(), ZERO)
        current_sample = bool(current['sale_days'])
        previous_sample = bool(previous['sale_days'])

        cards = payload['cards']
        cards['sales'] = _card(current_total)
        cards['sales']['comparison'] = self._baseer_comparison(
            cards['sales'], _card(previous_total), current_sample and previous_sample,
        )
        day_count = len(current['sale_days'])
        previous_day_count = len(previous['sale_days'])
        cards['daily_sales'] = _card(
            current_total / Decimal(day_count) if day_count else None, bool(day_count),
        )
        cards['daily_sales']['comparison'] = self._baseer_comparison(
            cards['daily_sales'],
            _card(previous_total / Decimal(previous_day_count) if previous_day_count else None,
                  bool(previous_day_count)),
            current_sample and previous_sample,
        )
        current_guests = current['guests']
        previous_guests = previous['guests']
        current_guests_complete = bool(current_guests['known_rows'] and not current_guests['missing_rows'])
        previous_guests_complete = bool(previous_guests['known_rows'] and not previous_guests['missing_rows'])
        cards['customers'] = _card(
            current_guests['known_count'], bool(current_guests['known_rows']), integer=True,
        )
        cards['customers']['comparison'] = self._baseer_comparison(
            cards['customers'],
            _card(previous_guests['known_count'], bool(previous_guests['known_rows']), integer=True),
            current_guests_complete and previous_guests_complete,
        )
        current_guest_days = len(current_guests['sale_days'])
        previous_guest_days = len(previous_guests['sale_days'])
        cards['daily_customers'] = _card(
            Decimal(current_guests['known_count']) / Decimal(current_guest_days)
            if current_guest_days else None,
            current_guests_complete and bool(current_guest_days),
        )
        cards['daily_customers']['comparison'] = self._baseer_comparison(
            cards['daily_customers'],
            _card(Decimal(previous_guests['known_count']) / Decimal(previous_guest_days)
                  if previous_guest_days else None,
                  previous_guests_complete and bool(previous_guest_days)),
            current_guests_complete and previous_guests_complete,
        )
        cards['average_bill'] = _card(
            current_total / Decimal(current_guests['known_count'])
            if current_guests['known_count'] else None,
            current_guests_complete and bool(current_guests['known_count']),
        )
        cards['average_bill']['comparison'] = self._baseer_comparison(
            cards['average_bill'],
            _card(previous_total / Decimal(previous_guests['known_count'])
                  if previous_guests['known_count'] else None,
                  previous_guests_complete and bool(previous_guests['known_count'])),
            current_guests_complete and previous_guests_complete,
        )

        granularity = payload['timeline']['granularity']
        bucket_totals = defaultdict(lambda: ZERO)
        bucket_days = set()
        native_buckets = set()
        guest_buckets = defaultdict(lambda: {'known_count': 0, 'known_rows': 0, 'missing_rows': 0})
        bucket_key = lambda day: day.isoformat()[:7] if granularity == 'month' else day.isoformat()
        for day, amount in current['by_day'].items():
            bucket_totals[bucket_key(day)] += amount
        for day in current['sale_days']:
            bucket_days.add(bucket_key(day))
        for day in current['new_days']:
            native_buckets.add(bucket_key(day))
        for day, guest_row in current_guests['by_day'].items():
            bucket = guest_buckets[bucket_key(day)]
            for metric in bucket:
                bucket[metric] += guest_row[metric]
        for point in payload['timeline']['points']:
            key = point['key']
            if key in bucket_days:
                value = money(bucket_totals[key])
                point['sales'] = str(money(value))
                point['sales_display'] = _display(value)
                if key in native_buckets:
                    point['manual_status'] = point['status']
                    point['status'] = 'recorded'
            guest_row = guest_buckets[key]
            point['customer_coverage'] = {
                **guest_row,
                'complete': bool(guest_row['known_rows'] and not guest_row['missing_rows']),
            }
            point['customers'] = guest_row['known_count'] if guest_row['known_rows'] else None
            point['customers_display'] = _display(guest_row['known_count'], True) if guest_row['known_rows'] else '—'

        payload['cards'] = cards
        payload['has_data'] = current_sample
        payload['unified_sources'] = True
        payload['sources_complete'] = True
        payload['customer_coverage'] = {
            'known_count': current_guests['known_count'],
            'known_rows': current_guests['known_rows'],
            'missing_rows': current_guests['missing_rows'],
            'complete': current_guests_complete,
        }
        payload['payment_performance'] = self._baseer_unified_payment_performance(
            company, current, current_total,
        )
        payload['source_breakdown'] = [
            {'key': key, 'name': label, 'sales': _card(current['totals'][key]),
             'source_action': self._baseer_unified_action(company, first, last, key)}
            for key, label in (
                ('manual', _('Approved summaries')),
                ('pos', _('Point of Sale')),
                ('restaurant', _('Restaurants')),
                ('sales', _('Sales invoices')),
            )
        ]
        return payload
