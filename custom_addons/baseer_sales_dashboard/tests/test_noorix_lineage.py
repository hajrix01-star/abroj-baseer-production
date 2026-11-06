"""Actual record-rule proof for bounded, root-local reversal diagnostics."""
from unittest.mock import patch

from odoo import Command
from odoo.fields import Domain
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError
from odoo.tests.common import new_test_user, tagged

from .test_noorix_evidence import NoorixEvidenceFixtures


@tagged('post_install', '-at_install')
class TestNoorixLineage(NoorixEvidenceFixtures, AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_noorix_evidence_fixtures()
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.dashboard = cls.env.ref('baseer_sales_dashboard.dashboard_sales_summary')
        cls.Evidence = cls.env['baseer.noorix.sales.evidence']

    def _original(self):
        move = self._noorix_entry('lineage-original', '2026-11-01', '115.00')
        ident = self.Evidence.import_evidence([
            self._noorix_row(move, 'lineage-original', 3),
        ])[0]
        return move, self.Evidence.browse(ident)

    def _reader(self, extra_companies=None):
        companies = self.env.company | (extra_companies or self.env['res.company'])
        return new_test_user(
            self.env, login='noorix_lineage_reader',
            groups=('base.group_user,point_of_sale.group_pos_user,'
                    'sales_team.group_sale_salesman_all_leads,account.group_account_readonly'),
            company_id=self.env.company.id,
            company_ids=[Command.set(companies.ids)],
        )

    def _metrics(self, dashboard, include):
        return dashboard.get_baseer_sales_metrics(
            {'preset': 'custom', 'date_from': '2026-11-01', 'date_to': '2026-11-30'},
            include_noorix=include,
        )

    def test_hidden_posted_reversal_is_detected_by_root_local_existence_only(self):
        move, evidence = self._original()
        reversal = move._reverse_moves([{'date': '2026-11-03'}], cancel=False)
        reversal.action_post()
        reader = self._reader()
        self.env['ir.rule'].with_user(self.env.ref('base.user_admin')).create({
            'name': 'Noorix lineage: hide one posted reversal for the reader',
            'model_id': self.env['ir.model']._get_id('account.move'),
            'domain_force': repr([('id', '!=', reversal.id)]),
            'perm_read': True, 'perm_write': False,
            'perm_create': False, 'perm_unlink': False,
        })
        context = {'allowed_company_ids': self.env.company.ids, 'tz': 'Asia/Riyadh'}
        Move = self.env['account.move'].with_user(reader).with_context(context)
        dashboard = self.dashboard.with_user(reader).with_context(context)
        self.assertFalse(Move.env.su)
        Move.browse(move.id).check_access('read')
        evidence.with_user(reader).with_context(context).check_access('read')
        self.assertEqual(evidence.with_user(reader).with_context(context).customer_count, 3)
        with self.assertRaises(AccessError):
            Move.browse(reversal.id).check_access('read')
        # A normal descendant search silently omits the hidden reversal.
        self.assertFalse(Move.search([('reversed_entry_id', '=', move.id), ('state', '=', 'posted')]))
        visible_posted = Move._search([
            ('company_id', '=', self.env.company.id), ('state', '=', 'posted'),
            ('date', '<=', '2026-11-30'),
        ])
        # Only verified, readable roots are searched normally. any! bypasses
        # descendant record rules for this fixed existence diagnostic only;
        # the query returns a root count, never hidden IDs, dates or amounts.
        probe = Domain([('id', 'in', [move.id]), ('company_id', '=', self.env.company.id)]) & Domain(
            'reversal_move_ids', 'any!', Domain([
                ('company_id', '=', self.env.company.id), ('state', '=', 'posted'),
                ('date', '<=', '2026-11-30'), ('id', 'not in', visible_posted),
            ]))
        with patch.object(type(Move), 'read', side_effect=AssertionError('The existence probe must not read accounting records')):
            self.assertEqual(Move.search_count(probe, limit=1), 1)
        self.assertFalse(Move.env.su)
        # The optional reader must reject, rather than show the original 115
        # while another ordinary reader can see its offsetting reversal.
        with self.assertRaises(AccessError):
            self._metrics(dashboard, True)
        self.assertEqual(self._metrics(dashboard, False)['cards']['sales']['value'], '0.00')

    def test_other_allowed_company_and_forged_context_do_not_override_explicit_option(self):
        self._original()
        other = self.env['res.company'].create({
            'name': 'Synthetic Noorix second allowed company',
            'currency_id': self.env.company.currency_id.id,
        })
        reader = self._reader(other)
        dashboard = self.dashboard.with_user(reader).with_context(
            allowed_company_ids=[self.env.company.id, other.id],
            baseer_include_noorix=True,
        )
        self.assertEqual(dashboard.env.company, self.env.company)
        # Default/false must never consume evidence just because a JSON
        # context supplied an internal-looking flag or a second company.
        with patch.object(type(self.dashboard), '_noorix_events',
                          side_effect=AssertionError('False must not read Noorix evidence')):
            off = self._metrics(dashboard, False)
        self.assertEqual(off['cards']['sales']['value'], '0.00')
        self.assertFalse(off['include_noorix'])
        on = self._metrics(dashboard.with_context(baseer_include_noorix=False), True)
        self.assertEqual(on['company']['id'], self.env.company.id)
        self.assertEqual(on['cards']['sales']['value'], '115.00')
        source = next(row for row in on['source_breakdown'] if row['key'] == 'noorix')
        self.assertEqual(source['source_action']['context']['allowed_company_ids'], self.env.company.ids)
