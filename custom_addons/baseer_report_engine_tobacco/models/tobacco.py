"""Standalone tobacco register, using the native POS tax calculation."""
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

RIYADH = ZoneInfo('Asia/Riyadh')


class ReportDefinition(models.Model):
    _inherit = 'baseer.report.definition'

    report_kind = fields.Selection(selection_add=[('tobacco', 'Tobacco Service Fee')], ondelete={'tobacco': 'cascade'})


class TobaccoEngine(models.AbstractModel):
    _inherit = 'baseer.report.engine'

    @api.model
    def _tobacco_accounts(self, company):
        Tax = self.env['account.tax'].with_company(company).with_context(active_test=False)
        candidates = Tax.search([('company_id', '=', company.id), ('type_tax_use', '=', 'sale')])
        # Translatable names are stored per language. Looking only through the
        # current language misses a match saved in another translation.
        self.env.cr.execute("""
            SELECT t.id FROM account_tax t
            LEFT JOIN account_tax_group g ON g.id = t.tax_group_id
            WHERE t.id = ANY(%s) AND EXISTS (
                SELECT 1 FROM (
                    SELECT value FROM jsonb_each_text(COALESCE(t.name, '{}'::jsonb))
                    UNION ALL
                    SELECT value FROM jsonb_each_text(COALESCE(g.name, '{}'::jsonb))
                ) AS n
                WHERE n.value ILIKE %s OR n.value ILIKE %s
            )
        """, [candidates.ids, '%Tobacco service fee%', '%رسوم%التبغ%'])
        taxes = candidates.browse([row[0] for row in self.env.cr.fetchall()])
        reps = taxes.invoice_repartition_line_ids | taxes.refund_repartition_line_ids
        accounts = reps.filtered(lambda r: r.repartition_type == 'tax').account_id
        tokens = re.split(r'[,\s]+', self.env['ir.config_parameter'].sudo().get_param(
            'baseer_report_engine.tobacco_fee_accounts', '').strip())
        Account = self.env['account.account'].with_company(company).with_context(active_test=False)
        company_accounts = Account.search([('company_ids', 'in', company.id)])
        accounts |= company_accounts.filtered(lambda a: a.code == '201021' or a.code in tokens or str(a.id) in tokens)
        return accounts.filtered(lambda a: company in a.company_ids)

    @api.model
    def _tobacco_order_fees(self, order, account_ids):
        tax = self.env['account.tax'].with_company(order.company_id)
        bases = order.lines.sorted('id')._prepare_tax_base_line_values()
        tax._add_tax_details_in_base_lines(bases, order.company_id)
        tax._round_base_lines_tax_details(bases, order.company_id)
        tax._add_accounting_data_in_base_lines_tax_details(bases, order.company_id)
        factor = -1 if order.is_refund or order.amount_total < 0 else 1
        fees = defaultdict(float)
        for base in bases:
            for detail in base['tax_details']['taxes_data']:
                for rep in detail.get('tax_reps_data', []):
                    account = rep.get('account')
                    if account and account.id in account_ids:
                        fees[(account.id, base['record'].id)] += factor * rep['tax_amount_currency']
        rounding = order.config_id.rounding_method if order.config_id.cash_rounding and not order.config_id.only_round_cash_method else None
        summary = tax._get_tax_totals_summary(base_lines=bases, currency=order.currency_id,
                                               company=order.company_id, cash_rounding=rounding)
        return fees, factor * summary['total_amount_currency']

    @api.model
    def _tobacco_collect(self, options):
        start = fields.Date.to_date(options['date_from'])
        end = fields.Date.to_date(options['date_to'])
        utc_start = datetime.combine(start, time.min, tzinfo=RIYADH).astimezone(timezone.utc).replace(tzinfo=None)
        utc_end = datetime.combine(end + timedelta(days=1), time.min, tzinfo=RIYADH).astimezone(timezone.utc).replace(tzinfo=None)
        sections = []
        for company in self.env.companies:
            if company.currency_id.name != 'SAR' or company.currency_id.decimal_places != 2:
                raise ValidationError(_('This register requires a company currency of SAR with two decimal places.'))
            accounts = self._tobacco_accounts(company)
            if not accounts:
                continue
            domain = [('company_id', '=', company.id), ('account_id', 'in', accounts.ids),
                      ('parent_state', 'in', ['posted'] if options['posted_only'] else ['posted', 'draft'])]
            lines = self.env['account.move.line'].search(domain + [('date', '<=', end)])
            orders = self.env['pos.order'].search([('company_id', '=', company.id), ('source', '=', 'pos'),
                ('state', 'in', ('paid', 'done')), ('date_order', '>=', utc_start), ('date_order', '<', utc_end)], order='date_order,id')
            rows = defaultdict(list)
            exceptions = defaultdict(list)
            for order in orders:
                fees, calculated = self._tobacco_order_fees(order, set(accounts.ids))
                for (account_id, line_id), fee in fees.items():
                    line = self.env['pos.order.line'].browse(line_id)
                    rows[account_id].append({'date': fields.Datetime.to_datetime(order.date_order).replace(tzinfo=timezone.utc).astimezone(RIYADH).strftime('%Y-%m-%d %H:%M'),
                        'name': order.name, 'product': line.product_id.display_name, 'quantity': line.qty,
                        'type': _('Refund') if fee < 0 else _('Sale'), 'net': fee,
                        'model': 'pos.order', 'id': order.id, 'session_id': order.session_id.id,
                        'session_state': order.session_id.state})
                if fees and not company.currency_id.is_zero(calculated - order.amount_total):
                    for account_id in {key[0] for key in fees}:
                        exceptions[account_id].append({'id': order.id, 'name': order.name, 'computed': calculated, 'saved': order.amount_total})
            for account in accounts:
                account_lines = lines.filtered(lambda l: l.account_id == account)
                before = account_lines.filtered(lambda l: l.date < start)
                period = account_lines.filtered(lambda l: start <= l.date <= end)
                # POS invoices are already represented by their orders.
                invoice_lines = period.filtered(lambda l: l.parent_state == 'posted' and l.move_id.move_type in ('out_invoice', 'out_refund') and l.tax_line_id and not l.move_id.pos_order_ids)
                for line in invoice_lines:
                    rows[account.id].append({'date': str(line.date), 'name': line.move_id.name,
                        'product': '', 'quantity': 0, 'type': _('Credit Note') if line.move_id.move_type == 'out_refund' else _('Invoice'),
                        'net': line.credit - line.debit, 'model': 'account.move', 'id': line.move_id.id})
                ordered = sorted(rows[account.id], key=lambda x: (x['date'], x['id']))
                opening = sum(before.mapped('credit')) - sum(before.mapped('debit'))
                movement = sum(period.mapped('credit')) - sum(period.mapped('debit'))
                net = sum(r['net'] for r in ordered)
                manual = period.filtered(lambda l: l.move_id.move_type == 'entry' and not l.move_id.pos_session_ids)
                sections.append({'company_id': company.id, 'company': company.name, 'account_id': account.id,
                    'account': account.with_company(company).display_name, 'opening': opening, 'rows': ordered,
                    'debit': sum(max(-r['net'], 0) for r in ordered), 'credit': sum(max(r['net'], 0) for r in ordered),
                    'net': net, 'closing': opening + net, 'movement': movement, 'difference': net - movement,
                    'open_sessions': sorted({r['session_id'] for r in ordered if r.get('session_state') != 'closed' and r.get('session_id')}),
                    'manual_move_ids': manual.move_id.ids, 'exceptions': exceptions[account.id]})
        return sections

    @api.model
    def get_report(self, report_code, options=None, with_accounts=False):
        if report_code != 'tobacco_service_fee':
            return super().get_report(report_code, options, with_accounts=with_accounts)
        self._check_report_access()
        report = self._definition(report_code)
        raw = options if options is not None else self.env.context.get('baseer_options') or {}
        normalized = self._normalize_options(report, raw)
        sections = self._tobacco_collect(normalized)
        payload = self._build(report, normalized)
        payload['report']['report_kind'] = 'tobacco'
        payload['tobacco_sections'] = sections
        payload['has_draft_entries'] = bool(normalized['posted_only'] and self.env['account.move.line'].search_count(self._draft_domain(normalized), limit=1))
        # Generic statement rendering and exports remain usable until the dedicated register UI is available.
        result = []
        column = normalized['columns'][0]
        for index, section in enumerate(sections):
            def add(label, value, display='line', level=1):
                result.append({'code': 'TOBACCO_%s' % len(result), 'name': label, 'level': level, 'display': display,
                    'foldable': False, 'has_accounts': False, 'accounts': [],
                    'amounts': [self._serialize_amount(column, value, self.env.company.currency_id, False)]})
            add('%s — %s' % (section['company'], section['account']), 0, 'section', 0)
            add(_('Cumulative at start'), section['opening'])
            for row in section['rows']:
                add('%s · %s · %s' % (row['date'], row['name'], row['type']), row['net'])
            add(_('Total for period'), section['net'], 'total')
            add(_('Cumulative at end'), section['closing'], 'total')
            add(_('Register net for period'), section['net'])
            add(_('Fee account movement in the trial balance'), section['movement'])
            add(_('Difference'), section['difference'], 'total')
        payload['lines'] = result
        return payload

    @api.model
    def get_tobacco_source_action(self, options, model, record_id):
        """Only expose records actually present in the current report scope."""
        self._check_report_access()
        if model not in ('pos.order', 'account.move') or type(record_id) is not int or record_id <= 0:
            raise ValidationError(_('Choose a source from this report.'))
        normalized = self._normalize_options(self._definition('tobacco_service_fee'), options or {})
        sections = self._tobacco_collect(normalized)
        visible = any((r['model'], r['id']) == (model, record_id) for s in sections for r in s['rows'])
        if model == 'account.move':
            visible = visible or any(record_id in s['manual_move_ids'] for s in sections)
        if not visible:
            raise ValidationError(_('Choose a source from this report.'))
        record = self.env[model].browse(record_id).exists()
        record.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('Source Document'), 'res_model': model,
                'view_mode': 'form', 'views': [(False, 'form')], 'res_id': record.id, 'target': 'current'}

    @api.model
    def get_tobacco_ledger_action(self, options, account_id, company_id):
        self._check_report_access()
        normalized = self._normalize_options(self._definition('tobacco_service_fee'), options or {})
        if not any(s['account_id'] == account_id and s['company_id'] == company_id
                   for s in self._tobacco_collect(normalized)):
            raise ValidationError(_('Choose a fee account from this report.'))
        return self.get_general_ledger_action('general_ledger', options, account_id, company_id)
