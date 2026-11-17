import json

from odoo import _, api, models
from odoo.exceptions import AccessError


class AccountingDashboard(models.AbstractModel):
    _name = 'baseer.accounting.dashboard'
    _description = 'Read-only accounting dashboard'

    @api.model
    def get_dashboard(self, options=None):
        if not any(self.env.user.has_group(group) for group in (
            'account.group_account_readonly', 'account.group_account_user', 'account.group_account_manager',
        )):
            raise AccessError(_('You cannot access the accounting dashboard.'))
        options = options or {}
        domain = [('company_id', 'in', self.env.companies.ids), ('active', '=', True)]
        if options.get('favorites_only', True):
            domain.append(('show_on_dashboard', '=', True))
        if options.get('search'):
            domain.append(('name', 'ilike', options['search']))
        journals = self.env['account.journal'].search(domain)
        # Access computed fields on the entire recordset to preserve Odoo's batching.
        journals.mapped('kanban_dashboard')
        journals.mapped('kanban_dashboard_graph')
        cards = []
        for journal in journals:
            dashboard = json.loads(journal.kanban_dashboard or '{}')
            dashboard.pop('onboarding', None)
            cards.append({
                'id': journal.id, 'name': journal.name, 'type': journal.type,
                'company_id': journal.company_id.id, 'company_name': journal.company_id.name,
                'show_company': len(self.env.companies) > 1, 'color': journal.color,
                'dashboard': dashboard, 'graph': json.loads(journal.kanban_dashboard_graph or 'null'),
                'is_empty': not journal.has_entries,
            })
        report_specs = [
            ('baseer_report_engine.action_balance_sheet', _('Balance Sheet')),
            ('baseer_report_engine.action_profit_and_loss', _('Profit and Loss')),
            ('baseer_report_engine.action_trial_balance', _('Trial Balance')),
            ('baseer_report_engine.action_general_ledger', _('General Ledger')),
            ('baseer_report_engine.action_partner_ledger', _('Partner Ledger')),
            ('baseer_report_engine.action_aged_receivable', _('Aged Receivable')),
            ('baseer_report_engine.action_aged_payable', _('Aged Payable')),
            ('baseer_report_engine.action_cash_flow', _('Cash Flow Statement')),
            ('baseer_report_engine_tobacco.action_tobacco', _('Tobacco Service Fee')),
            ('baseer_report_engine_vat.action_vat', _('Tax Report')),
        ]
        reports = []
        for xmlid, label in report_specs:
            action = self.env.ref(xmlid, raise_if_not_found=False)
            if action and action.has_access('read'):
                reports.append({'xmlid': xmlid, 'label': label})
        return {'journals': cards, 'reports': reports,
                'is_manager': self.env.user.has_group('account.group_account_manager'),
                'is_user': self.env.user.has_group('account.group_account_user')}
