"""Private projection of the existing limited, proven outflow sources.

This adds current analytical labels, not a new cash-recognition policy. Missing
source coverage is retained; classification cannot turn incomplete cash into a
complete report. There is no public RPC or stored result.
"""

from collections import Counter
from decimal import Decimal, localcontext

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from odoo.addons.baseer_profit_loss_report.models.profit_loss import SECTION_KEYS


class OperationsOwnerCash(models.AbstractModel):
    _inherit = 'baseer.operations.report'

    def _owner_service_products(self, company, product_ids):
        """Resolve labels only for actual source products, not by their names."""
        if not product_ids or not hasattr(company, '_baseer_service_identity'):
            return {}
        try:
            from odoo.addons.baseer_service_seed.models.catalog import SERVICES
            from odoo.addons.baseer_service_seed.models.company import HR_SERVICE_ANALYTIC_MAP
        except ImportError:
            # A partially available optional catalog must not turn its service
            # products into ordinary purchases just because labels are absent.
            return {identity: {'classification': 'unclassified'} for identity in product_ids}
        arabic = (self.env.context.get('lang') or self.env.user.lang or '').startswith('ar')
        result = {}
        for key, english, arabic_name, _purpose in SERVICES:
            reference = self.env.ref(
                f'baseer_service_seed.product_{key}_company_{company.id}',
                raise_if_not_found=False,
            )
            if not reference or reference._name != 'product.product' or reference.id not in product_ids:
                continue
            product = self.env['product.product'].browse(reference.id).exists()
            product.check_access('read')
            template = product.product_tmpl_id
            template.check_access('read')
            if (not product or not template
                    or product.company_id not in (company, self.env['res.company'])
                    or template.company_id not in (company, self.env['res.company'])
                    or product.id in result):
                self._deny_incomplete_source()
            result[product.id] = ({'classification': 'unclassified'}
                                 if key in HR_SERVICE_ANALYTIC_MAP else {
                                     'classification': 'operating_services',
                                     'service_key': key,
                                     'service_name': arabic_name if arabic else english,
                                 })
        return result

    def _owner_cash_classification(self, line, company, service_products=None):
        """Label an already-proven allocation; never establish cash from a bill."""
        line = self.env['account.move.line'].browse(line.id).exists()
        line.ensure_one()
        line.check_access('read')
        move = line.move_id
        move.check_access('read')
        account = line.account_id
        account.check_access('read')
        if (line.company_id != company or move.company_id != company
                or move.state != 'posted' or company not in account.company_ids):
            self._deny_incomplete_source()
        if move.move_type == 'entry':
            return {'classification': 'operating_account',
                    'account_id': account.id, 'account_name': account.name}
        if move.move_type != 'in_invoice' or line.display_type != 'product':
            return {'classification': 'unclassified'}

        # The optional HR module owns this immutable relationship. Do not
        # classify an employee expense from its product name, type or seed ID.
        if 'baseer_hr_service_id' in move._fields and move.baseer_hr_service_id:
            service = self.env['baseer.hr.service'].browse(move.baseer_hr_service_id.id)
            service.check_access('read')
            service.flush_model(['bill_id'])
            self._assert_visible(service._table, 'bill_id=%s', [move.id], service)
            if (service.company_id != company or service.state != 'approved'
                    or service.bill_id != move or not service.service_type):
                self._deny_incomplete_source()
            labels = dict(service._fields['service_type']._description_selection(self.env))
            if service.service_type not in labels:
                self._deny_incomplete_source()
            return {'classification': 'employee_services',
                    'service_key': service.service_type,
                    'service_name': labels[service.service_type]}

        product = line.product_id
        if not product:
            return {'classification': 'unclassified'}
        product = self.env['product.product'].browse(product.id)
        product.check_access('read')
        template = product.product_tmpl_id
        template.check_access('read')
        if (not template or product.company_id not in (company, self.env['res.company'])
                or template.company_id not in (company, self.env['res.company'])):
            self._deny_incomplete_source()
        if service_products is None:
            service_products = self._owner_service_products(company, {product.id})
        if product.id in service_products:
            return service_products[product.id]
        # Current taxonomy is an analytical grouping explicitly approved by
        # the owner, not a historical category snapshot or a purchase flag.
        category = product.categ_id
        path, seen = [], set()
        while category:
            category.check_access('read')
            if category.id in seen or len(path) >= 64:
                self._deny_incomplete_source()
            if ('company_id' in category._fields
                    and category.company_id not in (company, self.env['res.company'])):
                self._deny_incomplete_source()
            seen.add(category.id)
            path.append((category.id, category.name))
            category = category.parent_id
        if len(path) < 2:
            return {'classification': 'unclassified'}
        return {'classification': 'purchase', 'category_path': list(reversed(path))}

    @api.model
    def _owner_cash(self, company, start, end, journal_ids):
        """Reuse source evidence and retain its unsupported/unknown coverage."""
        company.ensure_one()
        if (company.id != self.env.company.id or company.id not in {1, 2, 3, 56}
                or company.id not in self.env.user.company_ids.ids):
            raise AccessError(_('Only an authorized active company may be reported.'))
        company = self.env['res.company'].browse(company.id)
        company.check_access('read')
        company.currency_id.check_access('read')
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        if not start or not end or start > end:
            self._deny_incomplete_source()
        if (not isinstance(journal_ids, (list, tuple))
                or any(type(value) is not int or value <= 0 for value in journal_ids)):
            self._deny_incomplete_source()
        journals = self.env['account.journal'].browse(journal_ids).exists()
        journals.check_access('read')
        if set(journals.ids) != set(journal_ids) or any(row.company_id != company for row in journals):
            self._deny_incomplete_source()
        self._require_read(('account.move', 'account.move.line', 'account.account',
                            'account.bank.statement.line', 'account.payment',
                            'account.partial.reconcile'))
        with localcontext() as context:
            context.prec = 60
            excluded = Counter()
            # Read proofs are retained only while this one owner snapshot is
            # assembled.  They never cross Environment, request, or company.
            read_facts = {}
            hr = self._owner_hr_cash(
                company, start, end, journal_ids, read_facts=read_facts)
            originals, by_liquidity = [], {}

            def claim(events):
                """One source family owns each cash witness in this request."""
                current = {}
                for event in events:
                    if not event.get('payment_line_id') or event['line_model'] != 'account.move.line':
                        self._deny_incomplete_source()
                    current.setdefault(event['payment_line_id'], []).append(event)
                if set(current).intersection(by_liquidity):
                    self._deny_incomplete_source()
                for rows in current.values():
                    if len({(row['source_model'], row['source_id']) for row in rows}) != 1:
                        self._deny_incomplete_source()
                by_liquidity.update(current)
                originals.extend(events)

            claim(hr['events'])
            if (set(by_liquidity) != hr['claimed_liquidity_ids']
                    or {row['source_id'] for row in hr['events']
                        if row['source_model'] == 'account.payment'} != hr['claimed_payment_ids']
                    or {row['source_id'] for row in hr['events']
                        if row['source_model'] == 'account.bank.statement.line'} != hr['claimed_statement_ids']):
                self._deny_incomplete_source()
            excluded.update(hr['excluded'])
            for collector in (self._purchase_outflows, self._batch_purchase_outflows,
                              self._native_payment_outflows):
                sections = {key: {} for key in SECTION_KEYS}
                kwargs = ({'claimed_payment_ids': frozenset(hr['claimed_payment_ids'])}
                          if collector == self._native_payment_outflows else {})
                if collector == self._purchase_outflows:
                    kwargs = {'claimed_statement_ids': frozenset(hr['claimed_statement_ids'])}
                if collector == self._native_payment_outflows:
                    kwargs['read_facts'] = read_facts
                collector(company, start, end, list(journal_ids), sections, excluded, **kwargs)
                collected = []
                for section in sections.values():
                    for entry in section.values():
                        if (entry['count'] != len(entry['events']) or entry['raw'] != sum(
                                (event['amount'] for event in entry['events']), Decimal(0))):
                            self._deny_incomplete_source()
                        collected.extend(entry['events'])
                claim(collected)
            excluded.update(self._liquidity_outflow_exclusions(
                company, start, end, list(journal_ids), by_liquidity))

            liquidity = self.env['account.move.line'].browse(sorted(by_liquidity))
            liquidity.check_access('read')
            liquidity.move_id.check_access('read')
            if any(line.company_id != company or line.currency_id != company.currency_id
                   or line.move_id.company_id != company or line.move_id.state != 'posted'
                   or not start <= line.date <= end for line in liquidity):
                self._deny_incomplete_source()
            witnesses = {line.id: -self._owner_sales_money(line.balance, company.currency_id)
                         for line in liquidity}
            if any(value <= 0 for value in witnesses.values()):
                self._deny_incomplete_source()
            source_lines = self.env['account.move.line'].browse(sorted({
                event['line_id'] for event in originals}))
            source_lines.check_access('read')
            service_products = self._owner_service_products(
                company, set(source_lines.product_id.ids))
            events = []
            for original in originals:
                line = source_lines.browse(original['line_id'])
                if line.company_id != company:
                    self._deny_incomplete_source()
                if original.get('classification') in ('payroll', 'employee_advance'):
                    classification = {'classification': original['classification']}
                elif original.get('link_status') == 'unconfirmed':
                    classification = {'classification': 'unconfirmed_bill_classification'}
                else:
                    classification = self._owner_cash_classification(line, company, service_products)
                events.append({**original, **classification,
                               'company_id': company.id, 'direction': 'outgoing',
                               'amount': self._owner_sales_money(original['amount'], company.currency_id)})
            # The pure reducer performs a second, independent exact allocation
            # and identity check, including multiple categories per payment.
            from .owner_summary import build_owner_summary
            build_owner_summary(events, witnesses, company_id=company.id)
            return {'events': events, 'liquidity_totals': witnesses,
                    'excluded': dict(excluded),
                    'coverage_complete': self._coverage_complete(excluded)}
