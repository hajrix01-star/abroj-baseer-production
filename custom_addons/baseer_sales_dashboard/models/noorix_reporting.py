"""Optional, secured Noorix evidence adapter. Never posts or changes a sale."""

from collections import defaultdict
from odoo import _, fields, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import ZERO, money
from odoo.addons.baseer_pos_summary.models.operations import covered_slots

from .dashboard import MAX_SOURCE_ROWS


class NoorixSalesReporting(models.Model):
    _inherit = 'spreadsheet.dashboard'

    def _noorix_enabled(self):
        return self.env.context.get('baseer_include_noorix') is True

    def _baseer_unified_access(self):
        super()._baseer_unified_access()
        if self._noorix_enabled():
            self.env['baseer.noorix.sales.evidence'].check_access('read')

    def _noorix_check_unmapped_reversals(self, company, first, last, root_ids, budget):
        """A current-period reversal must not lose an unmapped older origin."""
        if not first or not last:
            return 0
        Move = self.env['account.move']
        domain = [('company_id', '=', company.id), ('state', '=', 'posted'),
                  ('date', '>=', first), ('date', '<=', last),
                  ('reversed_entry_id', '!=', False)]
        pending = Move.search(domain, limit=max(budget, 0) + 1)
        visited = set()
        count = 0
        while pending:
            pending.check_access('read')
            count += len(pending)
            if count > budget:
                raise ValidationError(_('Too many Noorix ancestry records. No records have been omitted.'))
            parents = pending.mapped('reversed_entry_id')
            parents.check_access('read')
            if any(parent.company_id != company for parent in parents):
                raise ValidationError(_('A Noorix reversal refers to another company.'))
            for parent in parents:
                if not parent.reversed_entry_id and 'NOORIX-SALES' in (parent.ref or '') and parent.id not in root_ids:
                    raise ValidationError(_('A Noorix reversal has an original entry without verified source evidence.'))
            visited.update(pending.ids)
            pending = parents.filtered(lambda parent: parent.id not in visited)
        return count

    def _noorix_events(self, company, first=None, last=None, budget=MAX_SOURCE_ROWS):
        """Resolve original entries and exact native reversal chains in batches.

        Evidence supplies identity and guests, not money. Period membership of
        an original is its verified business day; a reversal uses its own date.
        Ancestors outside the selected period remain validated for provenance.
        """
        Evidence = self.env['baseer.noorix.sales.evidence']
        Evidence.check_access('read')
        domain = [('company_id', '=', company.id)]
        if last:
            domain.append(('business_date', '<=', last))
        if Evidence.search_count(domain, limit=max(budget, 0) + 1) > budget:
            raise ValidationError(_('Too many Noorix source records. Choose a shorter reporting scope.'))
        evidence = Evidence.search(domain, order='business_date,id')
        roots = evidence.mapped('move_id')
        roots.check_access('read')
        # Budget ancestors as well as returned events, before loading lines.
        remaining = budget - len(evidence) - len(roots)
        line_count = self.env['account.move.line'].search_count(
            [('move_id', 'in', roots.ids), ('company_id', '=', company.id)],
            limit=max(remaining, 0) + 1) if roots else 0
        remaining -= line_count
        if remaining < 0:
            raise ValidationError(_('Too many Noorix source lines. No records have been omitted.'))
        roots.mapped('line_ids').check_access('read')
        unlinked = [('company_id', '=', company.id), ('state', '=', 'posted'),
                    ('move_type', '=', 'entry'), ('reversed_entry_id', '=', False),
                    ('ref', 'ilike', 'NOORIX-SALES'), ('id', 'not in', roots.ids)]
        if first:
            unlinked.append(('date', '>=', first))
        if last:
            unlinked.append(('date', '<=', last))
        if self.env['account.move'].search_count(unlinked, limit=1):
            raise ValidationError(_(
                'Noorix entries are missing verified source evidence. Import their customer and source metadata before combining sales.'
            ))
        remaining -= self._noorix_check_unmapped_reversals(company, first, last, set(roots.ids), remaining)
        rows = []
        seen = set()
        frontier = {}
        source_slots = defaultdict(set)
        amounts = evidence._validated_amounts()
        for item in evidence:
            amount = amounts[item.id]
            identity = (item.source_tenant, item.source_company_key, item.source_id)
            if identity in seen:
                raise ValidationError(_('A Noorix source identity is represented more than once.'))
            seen.add(identity)
            slots = covered_slots(item.period_scope)
            if source_slots[item.business_date] & slots:
                raise ValidationError(_('Noorix summaries overlap on the same business day. Review their source identities.'))
            source_slots[item.business_date].update(slots)
            row = {'evidence': item, 'move': item.move_id, 'day': item.business_date,
                   'amount': amount, 'original': True, 'scope': item.period_scope}
            frontier[item.move_id.id] = row
            if (not first or row['day'] >= first) and (not last or row['day'] <= last):
                rows.append(row)
        visited = set(frontier)
        Move = self.env['account.move']
        while frontier:
            visible = [('company_id', '=', company.id), ('state', '=', 'posted')]
            if last:
                visible.append(('date', '<=', last))
            # Existence-only diagnostic on already readable source parents.
            # any! examines the link, never reads a hidden child's amounts or
            # identity into the result. A hidden reversal refuses the report.
            hidden_child = visible + [('id', 'not in', Move._search(visible))]
            probe = Domain('id', 'in', list(frontier)) & Domain(
                'reversal_move_ids', 'any!', Domain(hidden_child))
            if Move.search_count(probe, limit=1):
                raise AccessError(_('A Noorix source has an inaccessible reversal; combined sales cannot be calculated.'))
            child_domain = [('company_id', '=', company.id), ('state', '=', 'posted'),
                            ('reversed_entry_id', 'in', list(frontier))]
            if last:
                child_domain.append(('date', '<=', last))
            children = Move.search(child_domain, limit=max(remaining, 0) + 1)
            remaining -= len(children)
            child_lines = self.env['account.move.line'].search_count(
                [('move_id', 'in', children.ids), ('company_id', '=', company.id)],
                limit=max(remaining, 0) + 1) if children else 0
            remaining -= child_lines
            if remaining < 0:
                raise ValidationError(_('Too many Noorix reversal records. No records have been omitted.'))
            children.check_access('read')
            children.mapped('line_ids').check_access('read')
            next_frontier = {}
            parent_seen = set()
            for child in children:
                parent = frontier[child.reversed_entry_id.id]
                if child.id in visited or child.reversed_entry_id.id in parent_seen:
                    raise ValidationError(_('A Noorix source has an ambiguous reversal chain.'))
                parent_seen.add(child.reversed_entry_id.id)
                if child.move_type != 'entry' or child.date < parent['day']:
                    raise ValidationError(_('A Noorix reversal has an invalid company, type or accounting date.'))
                # Exact account-level inversion; partial/changed reversals are
                # deliberately refused rather than assigned an invented value.
                def signature(move, sign=1):
                    values = defaultdict(lambda: ZERO)
                    for line in move.line_ids.filtered(lambda line: line.account_id):
                        if line.company_id != company or line.currency_id != company.currency_id:
                            raise ValidationError(_('A Noorix reversal uses another company or currency.'))
                        key = (line.account_id.id, line.partner_id.id, line.tax_line_id.id,
                               tuple(sorted(line.tax_tag_ids.ids)))
                        values[key] += money(line.balance) * sign
                    return {key: money(value) for key, value in values.items() if value}
                if signature(child) != signature(parent['move'], -1):
                    raise ValidationError(_('A Noorix reversal is partial or inconsistent. Review the original evidence.'))
                row = {'evidence': parent['evidence'], 'move': child, 'day': child.date,
                       'amount': -parent['amount'], 'original': False, 'scope': parent['scope']}
                next_frontier[child.id] = row
                visited.add(child.id)
                if not first or row['day'] >= first:
                    rows.append(row)
            frontier = next_frontier
        return rows

    def _baseer_source_bounds(self):
        first, last = super()._baseer_source_bounds()
        if not self._noorix_enabled():
            return first, last
        days = [day for day in (first, last) if day]
        days.extend(row['day'] for row in self._noorix_events(self.env.company))
        return (min(days), max(days)) if days else (None, None)

    def _baseer_check_capacity(self, company, periods):
        super()._baseer_check_capacity(company, periods)
        if not self._noorix_enabled():
            return
        # Include the existing sources plus evidence/financial lines in the
        # same bounded union budget, including comparison/history periods.
        remaining = MAX_SOURCE_ROWS
        valid_periods = [(first, last) for first, last in periods if first and last]
        for model, begin, end, current_only in (
            ('baseer.pos.summary', 'business_date', 'business_date', False),
            ('baseer.pos.closure', 'date_from', 'date_to', False),
            ('baseer.pos.summary.allocation', 'summary_id.business_date', 'summary_id.business_date', True),
        ):
            ranges = valid_periods[:1] if current_only else valid_periods
            if not ranges:
                continue
            domain = [('summary_id.company_id' if current_only else 'company_id', '=', company.id)]
            domain += ['|'] * (len(ranges) - 1)
            for first, last in ranges:
                domain += ['&', (begin, '<=', last), (end, '>=', first)]
            remaining -= self.env[model].search_count(domain, limit=max(remaining, 0) + 1)
            if remaining < 0:
                raise ValidationError(_('This report exceeds 100,000 source rows. No records have been omitted.'))
        for first, last in periods:
            if not first or not last:
                continue
            for name, domain in (
                ('pos.order', self._baseer_unified_pos_domain(company, first, last)),
                ('account.move', self._baseer_unified_invoice_domain(company, first, last)),
            ):
                remaining -= self.env[name].search_count(domain, limit=max(remaining, 0) + 1)
                if remaining < 0:
                    break
            if remaining < 0:
                raise ValidationError(_('This report exceeds 100,000 source rows. No records have been omitted.'))
        if valid_periods:
            self._noorix_events(company, min(first for first, _last in valid_periods),
                                max(last for _first, last in valid_periods), budget=remaining)

    def _baseer_unified_period(self, company, first, last):
        period = super()._baseer_unified_period(company, first, last)
        if not self._noorix_enabled():
            return period
        period['totals']['noorix'] = ZERO
        period['noorix_rows'] = self._noorix_events(company, first, last) if first and last else []
        period['noorix_incomplete_days'] = set()
        summary_slots = defaultdict(set)
        for summary in period['summaries']:
            summary_slots[summary.business_date].update(covered_slots(summary.period_scope))
        native_days = {
            fields.Datetime.context_timestamp(self.with_context(tz='Asia/Riyadh'), order.session_id.start_at).date()
            for order in period['orders']
        } | {invoice.invoice_date for invoice in period['invoices']}
        for row in period['noorix_rows']:
            day, amount, item = row['day'], row['amount'], row['evidence']
            if summary_slots[day] & covered_slots(row['scope']):
                raise ValidationError(_(
                    'Noorix evidence overlaps an approved summary. Resolve the source ownership before combining sales.'
                ))
            if row['scope'] == 'all' and day in native_days:
                raise ValidationError(_(
                    'Full-day Noorix sales overlap native sales without verified source ownership. Reconcile their identities before combining sales.'
                ))
            period['totals']['noorix'] += amount
            period['by_day'][day] += amount
            period['sale_days'].add(day)
            period['new_days'].add(day)
            period['new_count'] += 1
            if row['scope'] != 'all' or not row['original']:
                period['noorix_incomplete_days'].add(day)
            if not row['original']:
                # Customer counts describe original visits, not reversal
                # documents. A reversal-period customer ratio is unknown.
                period['guests']['missing_rows'] += 1
                period['guests']['by_day'][day]['missing_rows'] += 1
            elif amount > ZERO:
                guests = period['guests']
                guests['sale_days'].add(day)
                day_guests = guests['by_day'][day]
                if item.customer_count > 0:
                    guests['known_count'] += item.customer_count
                    guests['known_rows'] += 1
                    day_guests['known_count'] += item.customer_count
                    day_guests['known_rows'] += 1
                else:
                    guests['missing_rows'] += 1
                    day_guests['missing_rows'] += 1
        return period

    def _baseer_unified_action(self, company, first, last, key):
        if key != 'noorix':
            return super()._baseer_unified_action(company, first, last, key)
        ids = ([row['move'].id for row in self._noorix_events(company, first, last)]
               if self._noorix_enabled() and first and last else [])
        return self._noorix_source_action(company, ids)

    def _noorix_source_action(self, company, ids):
        return {'type': 'ir.actions.act_window', 'name': _('Noorix sales entries'),
                'res_model': 'account.move', 'view_mode': 'list,form',
                'views': [(False, 'list'), (False, 'form')],
                'domain': [('id', 'in', sorted(set(ids))), ('company_id', '=', company.id)],
                'context': {'allowed_company_ids': [company.id], 'create': False,
                            'edit': False, 'delete': False}}
