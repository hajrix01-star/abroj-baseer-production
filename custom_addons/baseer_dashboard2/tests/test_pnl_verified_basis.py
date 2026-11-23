from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user
from unittest.mock import patch
from decimal import Decimal
from datetime import date


@tagged('post_install', '-at_install')
class TestPnlVerifiedBasis(TransactionCase):
    def test_excluded_lines_check_linked_access_and_money_precision(self):
        company = self.env.company
        self.env['ir.config_parameter'].sudo().set_param('baseer_dashboard2.company_map', f'{company.id}:Test')
        Account = self.env['account.account'].with_company(company)
        accounts = [Account.create({'code': f'D2SEC{i}', 'name': f'Security {i}',
            'account_type': 'asset_current', 'company_ids': [Command.set(company.ids)]}) for i in (1, 2)]
        journal = self.env['account.journal'].create({'name': 'D2 security', 'code': 'D2SE',
                                                      'type': 'general', 'company_id': company.id})
        move = self.env['account.move'].create({'move_type': 'entry', 'date': '2026-10-05',
            'journal_id': journal.id, 'line_ids': [Command.create({'account_id': accounts[0].id, 'debit': 1}),
                                                   Command.create({'account_id': accounts[1].id, 'credit': 1})]})
        move.action_post()
        reader = new_test_user(self.env, login='d2_link_reader', groups='account.group_account_readonly',
                               company_id=company.id, company_ids=[Command.set(company.ids)])
        service = self.env['baseer.dashboard2.service'].with_user(reader)
        self.assertEqual(service._pnl_json_money(Decimal('123456789.01')), 123456789.01)
        with self.assertRaises(UserError):
            service._pnl_json_money(Decimal('90071992547409.91'))
        for model, record in (('account.move', move), ('account.journal', journal)):
            rule = self.env['ir.rule'].create({'name': f'D2 hide {model}',
                'model_id': self.env['ir.model']._get(model).id,
                'domain_force': f"[('id', '!=', {record.id})]"})
            visible = self.env['account.move.line'].with_user(reader).search([('id', 'in', move.line_ids.ids)])
            self.assertTrue(visible, 'The AML must remain visible to exercise linked-record security')
            with self.assertRaises(AccessError):
                service._accounting_pnl_verified([company.id], date(2026, 10, 1), date(2026, 10, 31), False)
            rule.unlink()

    def test_noorix_posted_summary_tax_basis(self):
        if 'baseer.noorix.sales.evidence' not in self.env:
            self.skipTest('Noorix evidence addon is not installed')
        company = self.env.company
        sar = self.env.ref('base.SAR')
        sar.active = True
        company.currency_id = sar
        self.env['ir.config_parameter'].sudo().set_param('baseer_dashboard2.company_map', f'{company.id}:Test')
        Account = self.env['account.account'].with_company(company)
        def account(code, kind):
            return Account.create({'code': code, 'name': code, 'account_type': kind,
                                   'company_ids': [Command.set(company.ids)]})
        income = account('D2NREV', 'income')
        funding = account('D2NCASH', 'asset_current')
        vat = account('D2NVAT', 'liability_current')
        journal = self.env['account.journal'].create({'name': 'D2 Noorix', 'code': 'D2NX',
                                                      'type': 'general', 'company_id': company.id})
        tag = self.env['account.account.tag'].create({'name': '+D2 Noorix VAT', 'applicability': 'taxes',
                                                      'country_id': company.account_fiscal_country_id.id})
        self.env['account.tax'].with_company(company).create({
            'name': 'D2 Noorix VAT', 'amount': 15, 'type_tax_use': 'sale', 'company_id': company.id,
            'invoice_repartition_line_ids': [Command.clear(), Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'account_id': vat.id, 'tag_ids': [Command.set(tag.ids)]})],
        })
        move = self.env['account.move'].with_company(company).create({
            'date': '2026-11-10', 'journal_id': journal.id, 'move_type': 'entry',
            'ref': 'NOORIX-SALES SHAMI 2026-11-10 | src:d2-synthetic',
            'line_ids': [Command.create({'name': 'Noorix sales cash 2026-11-10', 'account_id': funding.id, 'debit': 115}),
                         Command.create({'name': 'Noorix sales', 'account_id': income.id, 'credit': 100}),
                         Command.create({'name': 'Noorix VAT', 'account_id': vat.id, 'credit': 15,
                                         'tax_tag_ids': [Command.set(tag.ids)]})]})
        move.action_post()
        service = self.env['baseer.dashboard2.service']
        params = {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-11'}, 'pnl_view': 'month'}
        for inclusive, expected in ((False, '100.00'), (True, '115.00')):
            filters = {**params, 'tax_inclusive': inclusive}
            row = next(r for r in service.get_section('pnl', filters)['rows'] if r['key'] == 'revenue')
            self.assertEqual(f"{row['total']:.2f}", expected)
            descriptor = {**filters, 'section': 'pnl', 'key': 'revenue', 'column': 0, 'child': None}
            details = service.get_pnl_details(descriptor, {'kind': 'row'})
            self.assertEqual(details['value'], expected)
            selector = next(r['drill'] for r in details['rows'] if r['drill']['account_id'] == income.id)
            source = service.get_pnl_details(descriptor, selector)['rows'][0]['source']
            self.assertEqual(service.open_pnl_detail_source(descriptor, source)['res_id'], move.id)

    def test_multiple_companies_and_restricted_reader(self):
        first = self.env.company
        second = self.env['res.company'].create({'name': 'D2 isolated company', 'currency_id': first.currency_id.id})
        # IDs 1–3 are the deployment allowlist. PostgreSQL sequences do not roll
        # back between test runs, so emulate that allowlist for later fixture IDs.
        if second.id not in (2, 3):
            def fixture_companies(service):
                service._check_reader()
                return [(c.id, c.name, c.name) for c in (first | second) if c.id in service.env.user.company_ids.ids]
            allowlist = patch.object(type(self.env['baseer.dashboard2.service']), '_companies', fixture_companies)
            allowlist.start()
            self.addCleanup(allowlist.stop)
        self.env.user.company_ids = [Command.link(second.id)]
        self.env['ir.config_parameter'].sudo().set_param(
            'baseer_dashboard2.company_map', f'{first.id}:First,{second.id}:Second')
        for company, amount in ((first, 100.01), (second, 200.02)):
            Account = self.env['account.account'].with_company(company)
            revenue = Account.create({'code': 'D2MCREV', 'name': 'Sales', 'account_type': 'income',
                                      'company_ids': [Command.set(company.ids)]})
            funding = Account.create({'code': 'D2MCCSH', 'name': 'Cash', 'account_type': 'asset_current',
                                      'company_ids': [Command.set(company.ids)]})
            journal = self.env['account.journal'].with_company(company).create({
                'name': 'D2 multi journal', 'code': 'D2MC', 'type': 'general', 'company_id': company.id})
            move = self.env['account.move'].with_company(company).create({
                'move_type': 'entry', 'date': '2026-10-05', 'journal_id': journal.id,
                'line_ids': [Command.create({'account_id': funding.id, 'debit': amount}),
                             Command.create({'account_id': revenue.id, 'credit': amount})]})
            move.action_post()
        reader = new_test_user(self.env, login='d2_multi_reader', groups='account.group_account_readonly',
                               company_id=first.id, company_ids=[Command.set((first | second).ids)])
        service = self.env['baseer.dashboard2.service'].with_user(reader)
        params = {'company_key': 'all', 'period': {'mode': 'month', 'month': '2026-10'},
                  'pnl_view': 'month', 'tax_inclusive': True}
        row = next(row for row in service.get_section('pnl', params)['rows'] if row['key'] == 'revenue')
        self.assertEqual(f"{row['total']:.2f}", '300.03')
        descriptor = {**params, 'section': 'pnl', 'key': 'revenue', 'child': None, 'column': 0}
        details = service.get_pnl_details(descriptor, {'kind': 'row'})
        self.assertEqual(details['value'], '300.03')
        self.assertEqual({r['drill']['company_id'] for r in details['rows']}, {first.id, second.id})
        restricted = new_test_user(self.env, login='d2_one_company', groups='account.group_account_readonly',
                                   company_id=first.id, company_ids=[Command.set(first.ids)])
        with self.assertRaises(AccessError):
            service.with_user(restricted).get_pnl_details(descriptor, {'kind': 'row'})
        with self.assertRaises(AccessError):
            service.with_user(restricted).get_pnl_details({**descriptor, 'company_key': str(second.id)}, {'kind': 'row'})

    def test_tax_basis_account_detail_and_source(self):
        company = self.env.company
        self.env['ir.config_parameter'].sudo().set_param('baseer_dashboard2.company_map', '%s:Test' % company.id)
        Account = self.env['account.account'].with_company(company)
        def account(code, kind):
            return Account.create({'code': code, 'name': code, 'account_type': kind,
                                   'company_ids': [Command.set(company.ids)]})
        revenue = account('D2VREV', 'income')
        receivable = account('D2VREC', 'asset_receivable')
        vat = account('D2VVAT', 'liability_current')
        partner = self.env['res.partner'].create({'name': 'D2 verified customer', 'property_account_receivable_id': receivable.id})
        journal = self.env['account.journal'].create({'name': 'D2 verified sales', 'code': 'D2VS', 'type': 'sale', 'company_id': company.id})
        tax = self.env['account.tax'].with_company(company).create({'name': 'D2 verified 15%', 'type_tax_use': 'sale',
                            'amount_type': 'percent', 'amount': 15, 'company_id': company.id})
        (tax.invoice_repartition_line_ids | tax.refund_repartition_line_ids).filtered(
            lambda line: line.repartition_type == 'tax').write({'account_id': vat.id})
        move = self.env['account.move'].with_company(company).create({
            'move_type': 'out_invoice', 'journal_id': journal.id, 'partner_id': partner.id,
            'invoice_date': '2026-10-05', 'date': '2026-10-05',
            'invoice_line_ids': [Command.create({'name': 'taxed', 'account_id': revenue.id,
                                      'quantity': 1, 'price_unit': 100, 'tax_ids': [Command.set(tax.ids)]})],
        })
        move.action_post()
        service = self.env['baseer.dashboard2.service']
        params = {'company_key': str(company.id), 'period': {'mode': 'month', 'month': '2026-10'}, 'pnl_view': 'month'}
        descriptor = {**params, 'section': 'pnl', 'key': 'revenue', 'child': None, 'column': 0, 'pnl_range': None}
        for tax_mode, expected in ((False, '100.00'), (True, '115.00')):
            result = service.get_section('pnl', {**params, 'tax_inclusive': tax_mode})
            row = next(row for row in result['rows'] if row['key'] == 'revenue')
            self.assertEqual(f"{row['total']:.2f}", expected)
            descriptor['tax_inclusive'] = tax_mode
            summary = service.get_pnl_details(descriptor, {'kind': 'row'})
            self.assertEqual(summary['value'], expected)
            account_selector = next(row['drill'] for row in summary['rows'] if row['drill']['account_id'] == revenue.id)
            detail = service.get_pnl_details(descriptor, account_selector)
            self.assertEqual(detail['value'], expected)
            source = detail['rows'][0]['source']
            self.assertEqual(service.open_pnl_detail_source(descriptor, source)['res_id'], move.id)
            with self.assertRaises(AccessError):
                service.open_pnl_detail_source(descriptor, {**source, 'line_id': source['line_id'] + 1000000})
        self.assertEqual(service.get_section('pnl', params)['basis'], 'inclusive')
        with self.assertRaises(UserError):
            service.get_section('pnl', {**params, 'tax_inclusive': 'true'})

        reader = new_test_user(self.env, login='d2_verified_reader', groups='account.group_account_readonly',
                               company_id=company.id, company_ids=[Command.set(company.ids)])
        restricted = service.with_user(reader)
        descriptor['tax_inclusive'] = True
        reader_summary = restricted.get_pnl_details(descriptor, {'kind': 'row'})
        self.assertEqual(reader_summary['value'], '115.00')
        selector = next(row['drill'] for row in reader_summary['rows'] if row['drill']['account_id'] == revenue.id)
        reader_detail = restricted.get_pnl_details(descriptor, selector)
        reader_source = reader_detail['rows'][0]['source']
        self.assertEqual(restricted.open_pnl_detail_source(descriptor, reader_source)['res_id'], move.id)
        with self.assertRaises(AccessError):
            restricted.open_pnl_detail_source(descriptor, {**reader_source, 'company_id': company.id + 1000000})
        with self.assertRaises(AccessError):
            restricted.get_pnl_details({**descriptor, 'company_key': str(company.id + 1000000)}, {'kind': 'row'})
        with self.assertRaises(UserError):
            service.get_pnl_details({**descriptor, 'column': 99}, {'kind': 'row'})
        with self.assertRaises(UserError):
            service.get_pnl_details({**descriptor, 'column': None, 'pnl_view': 'range',
                'pnl_range': {'date_from': '2025-01-01', 'date_to': '2027-01-01'}}, {'kind': 'row'})

        for day, price in (('2025-10-01', 300), ('2025-10-05', 100)):
            prior = self.env['account.move'].with_company(company).create({
                'move_type': 'out_invoice', 'journal_id': journal.id, 'partner_id': partner.id,
                'invoice_date': day, 'date': day, 'invoice_line_ids': [Command.create({
                    'name': 'prior', 'account_id': revenue.id, 'quantity': 1,
                    'price_unit': price, 'tax_ids': [Command.set(tax.ids)]})]})
            prior.action_post()
        for tax_mode, expected in ((False, 100.0), (True, 115.0)):
            result = service.get_section('pnl', {**params, 'pnl_view': 'range', 'tax_inclusive': tax_mode,
                'pnl_range': {'date_from': '2026-10-05', 'date_to': '2026-11-03'}})
            revenue_row = next(row for row in result['rows'] if row['key'] == 'revenue')
            self.assertEqual(revenue_row['previous_year_months'][0], expected)
