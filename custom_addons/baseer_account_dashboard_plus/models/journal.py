from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.fields import Domain


REPORTS = {
    'profit': ('baseer_report_engine.action_profit_and_loss', 'Profit and Loss'),
    'balance': ('baseer_report_engine.action_balance_sheet', 'Balance Sheet'),
    'trial': ('baseer_report_engine.action_trial_balance', 'Trial Balance'),
    'ledger': ('baseer_report_engine.action_general_ledger', 'General Ledger'),
    'receivable': ('baseer_report_engine.action_aged_receivable', 'Aged Receivable'),
    'payable': ('baseer_report_engine.action_aged_payable', 'Aged Payable'),
    'cash_flow': ('baseer_report_engine.action_cash_flow', 'Cash Flow'),
    'vat': ('baseer_report_engine_vat.action_vat', 'VAT Report'),
    'tobacco': ('baseer_report_engine_tobacco.action_tobacco', 'Tobacco monthly report'),
}


def classify_journal(name, code, journal_type):
    text = (str(name or '') + ' ' + str(code or '')).casefold()
    if journal_type in ('bank', 'cash'):
        for app, patterns in [('Keeta', ('keeta', 'كيتا')), ('Jahez', ('jahez', 'جاهز')),
                              ('HungerStation', ('hungerstation', 'هنقرستيشن', 'هنقر'))]:
            if any(p in text for p in patterns):
                return 'delivery', app
    if journal_type == 'cash' and any(p in str(name or '').casefold() for p in ('عهدة', 'custody')):
        return 'custody', False
    return False, False


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    def _fill_bank_cash_dashboard_data(self, data):
        super()._fill_bank_cash_dashboard_data(data)
        journals = self.filtered(lambda j: j.type in ('bank', 'cash') and j.default_account_id)
        lines = self.env['account.move.line']._read_group(
            [('account_id', 'in', journals.default_account_id.ids), ('company_id', 'in', journals.company_id.ids),
             ('parent_state', '=', 'posted')], ['account_id', 'company_id', 'currency_id'], ['balance:sum', 'amount_currency:sum'])
        amounts = defaultdict(lambda: [0, 0])
        for account, company, currency, balance, foreign in lines:
            amounts[(account.id, company.id)][0] += balance
            amounts[(account.id, company.id, currency.id)][1] += foreign
        direct = journals._get_direct_bank_payments() if journals else {}
        for journal in journals:
            balance, foreign = amounts.get((journal.default_account_id.id, journal.company_id.id), (0, 0))
            currency = journal.currency_id or journal.company_id.currency_id
            ledger = amounts[(journal.default_account_id.id, journal.company_id.id, journal.currency_id.id)][1] if journal.currency_id and journal.currency_id != journal.company_id.currency_id else balance
            card = journal.current_statement_balance + direct[journal.id][1]
            kind, app = classify_journal(journal.name, journal.code, journal.type)
            data[journal.id].update(baseer_ledger_balance=currency.format(ledger),
                baseer_ledger_diff=currency.format(card - ledger), baseer_has_ledger_diff=abs(card - ledger) > 0.01,
                baseer_kind=kind, baseer_app=app)

    @api.model
    def _baseer_complete_action(self, action):
        """Return an action safe for the web client, or False if incomplete."""
        if not isinstance(action, dict):
            return False
        action = dict(action)
        if action.get('type') == 'ir.actions.act_window':
            if not action.get('res_model'):
                return False
            action['name'] = action.get('name') or _('Journal Items')
            action['view_mode'] = action.get('view_mode') or 'list,form'
            if not isinstance(action.get('views'), (list, tuple)) or not action['views']:
                action['views'] = [[False, mode.strip()] for mode in action['view_mode'].split(',') if mode.strip()]
            action['domain'] = action.get('domain') or []
            action['context'] = action.get('context') or {}
            action['target'] = action.get('target') or 'current'
        elif action.get('type') == 'ir.actions.client':
            if not action.get('tag'):
                return False
            action['context'] = action.get('context') or {}
            action['target'] = action.get('target') or 'current'
        else:
            return False
        return action

    def baseer_open_ledger(self):
        self.ensure_one()
        return self._baseer_complete_action({'type': 'ir.actions.act_window', 'name': _('Ledger balance'), 'res_model': 'account.move.line',
                'view_mode': 'list,form', 'domain': [('account_id', '=', self.default_account_id.id),
                ('company_id', '=', self.company_id.id), ('parent_state', '=', 'posted')]})

    def baseer_card_report_action(self):
        self.ensure_one()
        return self.baseer_report_action(self.env.context.get("baseer_report"))

    @api.model
    def baseer_report_action(self, key=None):
        key = key or self.env.context.get('baseer_report')
        item = REPORTS.get(key)
        action = self.env.ref(item[0], raise_if_not_found=False) if item else False
        return self._baseer_complete_action(action.read()[0]) if action else False

    @api.model
    def baseer_dashboard_summary(self):
        companies = self.env.companies
        journals = self.search([('company_id', 'in', companies.ids), ('type', 'in', ['bank', 'cash'])])
        grouped = self.env['account.move.line']._read_group(
            [('company_id', 'in', companies.ids), ('parent_state', '=', 'posted')],
            ['company_id', 'account_id'], ['balance:sum', 'amount_residual:sum'])
        by_account = {(c.id, a.id): (balance, residual) for c, a, balance, residual in grouped}
        today = fields.Date.context_today(self)
        start = today.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        taxes = self.env['account.move.line']._read_group(
            [('company_id', 'in', companies.ids), ('parent_state', '=', 'posted'),
             ('tax_line_id', '!=', False), ('date', '>=', start), ('date', '<', end)],
            ['company_id', 'tax_line_id'], ['balance:sum'])
        vat = defaultdict(float)
        for company, tax, balance in taxes:
            if tax.type_tax_use in ('sale', 'purchase'):
                vat[company.id] -= balance
        rows = []
        for company in companies:
            row = dict(id=company.id, name=company.name, currency=company.currency_id.name, currency_id=company.currency_id.id,
                       bank=0.0, cash=0.0, custody=0.0, delivery=0.0, receivable=0.0, payable=0.0, vat=vat[company.id], apps={})
            seen = set()
            for journal in journals.filtered(lambda j: j.company_id == company and j.default_account_id):
                account = journal.default_account_id
                if account.id in seen:
                    continue
                seen.add(account.id)
                amount = by_account.get((company.id, account.id), (0, 0))[0]
                kind, app = classify_journal(journal.name, journal.code, journal.type)
                row[journal.type] += amount
                if kind == 'custody': row['custody'] += amount
                if kind == 'delivery':
                    row['delivery'] += amount
                    row['apps'][app] = row['apps'].get(app, 0) + amount
            for c, account, balance, residual in grouped:
                if c != company: continue
                if account.account_type == 'asset_receivable': row['receivable'] += residual
                if account.account_type == 'liability_payable': row['payable'] -= residual
            rows.append(row)
        moves = self.env['account.move'].search([('company_id', 'in', companies.ids), ('state', '=', 'draft'), ('ref', 'ilike', 'AGENT:')])
        for row in rows:
            company_moves = moves.filtered(lambda m: m.company_id.id == row['id'])
            row['draft_count'] = len(company_moves)
            row['draft_amount'] = sum(move.currency_id._convert(abs(move.amount_total), move.company_id.currency_id, move.company_id, move.date or fields.Date.context_today(self)) for move in company_moves)
        reports = [{'key': key, 'name': _(label)} for key, (xmlid, label) in REPORTS.items() if self.env.ref(xmlid, raise_if_not_found=False)]
        return {'companies': rows, 'draft_count': len(moves), 'draft_amounts': {str(row['id']): row['draft_amount'] for row in rows}, 'reports': reports}

    @api.model
    def baseer_summary_action(self, kind):
        domain = [('company_id', 'in', self.env.companies.ids)]
        model = 'account.move.line'
        if kind == 'draft':
            model = 'account.move'
            domain += [('state', '=', 'draft'), ('ref', 'ilike', 'AGENT:')]
        else:
            domain += [('parent_state', '=', 'posted')]
            if kind == 'vat':
                today = fields.Date.context_today(self)
                start = today.replace(day=1)
                end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
                domain += [('tax_line_id', '!=', False), ('tax_line_id.type_tax_use', 'in', ['sale', 'purchase']), ('date', '>=', start), ('date', '<', end)]
            elif kind in ('receivable', 'payable'):
                domain += [('account_id.account_type', '=', 'asset_receivable' if kind == 'receivable' else 'liability_payable')]
            else:
                journals = self.search([('company_id', 'in', self.env.companies.ids), ('type', 'in', ['bank', 'cash'])])
                journals = journals.filtered(lambda j: (j.type == kind if kind in ('bank', 'cash') else classify_journal(j.name, j.code, j.type)[0] == kind))
                pairs = {(j.company_id.id, j.default_account_id.id) for j in journals if j.default_account_id}
                domain += list(Domain.OR([Domain('company_id', '=', company_id) & Domain('account_id', '=', account_id) for company_id, account_id in pairs])) if pairs else [('id', '=', False)]
        return self._baseer_complete_action({'type': 'ir.actions.act_window', 'name': _('Journal Items'), 'res_model': model, 'view_mode': 'list,form', 'domain': domain})
