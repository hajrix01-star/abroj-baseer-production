"""Shared fixtures for the report engine tests."""

from odoo import Command
from odoo.tests.common import TransactionCase


class EngineCase(TransactionCase):
    def _company(self, name, month='12', day=31):
        company = self.env['res.company'].create({
            'name': name,
            'fiscalyear_last_day': day,
            'fiscalyear_last_month': str(month),
            'currency_id': self.env.ref('base.USD').id,
        })
        self.env.user.write({'company_ids': [Command.link(company.id)]})
        return company

    def _engine(self, company):
        return self.env['baseer.report.engine'].with_company(company).with_context(
            allowed_company_ids=[company.id],
        )

    def _account(self, company, code, kind):
        return self.env['account.account'].with_company(company).create({
            'code': code,
            'name': f'{kind} {code}',
            'account_type': kind,
            'company_ids': [Command.set(company.ids)],
        })

    def _journal(self, company, code):
        return self.env['account.journal'].with_company(company).create({
            'name': f'Engine {code}',
            'code': code,
            'type': 'general',
            'company_id': company.id,
        })

    def _entry(self, company, journal, day, debit_account, credit_account, amount,
               posted=True, analytic=None):
        debit = {
            'name': 'Engine debit', 'company_id': company.id,
            'account_id': debit_account.id, 'debit': amount,
        }
        credit = {
            'name': 'Engine credit', 'company_id': company.id,
            'account_id': credit_account.id, 'credit': amount,
        }
        if analytic:
            debit['analytic_distribution'] = analytic
            credit['analytic_distribution'] = analytic
        move = self.env['account.move'].with_company(company).create({
            'company_id': company.id, 'date': day, 'journal_id': journal.id,
            'move_type': 'entry', 'line_ids': [Command.create(debit), Command.create(credit)],
        })
        if posted:
            move._post(soft=False)
        return move

    def _options(self, **extra):
        options = {
            'preset': 'custom',
            'as_of': '2041-06-30',
            'date_from': '2041-01-01',
            'date_to': '2041-06-30',
            'comparison': 0,
            'comparison_unit': 'month',
            'posted_only': True,
            'hide_zero': False,
            'journal_ids': [],
            'analytic_account_ids': [],
        }
        options.update(extra)
        return options

    def _value(self, payload, code, column='c0'):
        line = next(item for item in payload['lines'] if item['code'] == code)
        return next(amount['value'] for amount in line['amounts'] if amount['key'] == column)

    def _report(self, code, date_mode, lines):
        return self.env['baseer.report.definition'].create({
            'name': code, 'code': code, 'date_mode': date_mode, 'line_ids': lines,
        })
