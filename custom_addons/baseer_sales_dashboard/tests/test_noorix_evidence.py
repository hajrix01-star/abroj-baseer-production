"""Synthetic metadata imports against real isolated posted accounting entries."""
import hashlib
from decimal import Decimal, ROUND_HALF_UP

from odoo import Command
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import new_test_user, tagged


class NoorixEvidenceFixtures:
    """Reusable helpers only; this mixin contains no test methods."""

    @classmethod
    def _setup_noorix_evidence_fixtures(cls):
        company = cls.env.company
        sar = cls.env.ref('base.SAR')
        sar.active = True
        company.currency_id = sar
        cls.env.user.group_ids |= (
            cls.env.ref('account.group_account_manager')
            | cls.env.ref('point_of_sale.group_pos_manager')
        )
        cls.noorix_tax_account = cls.env['account.account'].create({
            'name': 'Synthetic Noorix output tax', 'code': 'NXRVAT',
            'account_type': 'liability_current', 'company_ids': [Command.set(company.ids)],
        })
        cls.noorix_tax_tag = cls.env['account.account.tag'].create({
            'name': '+Synthetic Noorix VAT', 'applicability': 'taxes',
            'country_id': company.account_fiscal_country_id.id,
        })
        cls.noorix_tax = cls.company_data['default_tax_sale'].copy({
            'name': 'Synthetic Noorix VAT 15%', 'amount': 15, 'amount_type': 'percent',
            'invoice_repartition_line_ids': [Command.clear(),
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'factor_percent': 100,
                                'account_id': cls.noorix_tax_account.id,
                                'tag_ids': [Command.set(cls.noorix_tax_tag.ids)]}),
            ],
            'refund_repartition_line_ids': [Command.clear(),
                Command.create({'repartition_type': 'base'}),
                Command.create({'repartition_type': 'tax', 'factor_percent': 100,
                                'account_id': cls.noorix_tax_account.id,
                                'tag_ids': [Command.set(cls.noorix_tax_tag.ids)]}),
            ],
        })
        cls.noorix_tax_repartition = cls.noorix_tax.invoice_repartition_line_ids.filtered(
            lambda line: line.repartition_type == 'tax')

    def _noorix_entry(self, source_id='test-origin-1', day='2026-11-01', gross='115.00',
                      tax_evidence='tags', agent_prefix=False):
        gross = Decimal(str(gross))
        net = (gross / Decimal('1.15')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        vat = gross - net
        tax_values = {}
        if tax_evidence in ('tags', 'official'):
            tax_values['tax_tag_ids'] = [Command.set(self.noorix_tax_tag.ids)]
        if tax_evidence == 'official':
            tax_values['tax_repartition_line_id'] = self.noorix_tax_repartition.id
        prefix = 'AGENT: المحاسب العام | ' if agent_prefix else ''
        move = self.env['account.move'].create({
            'move_type': 'entry', 'company_id': self.env.company.id,
            'journal_id': self.company_data['default_journal_misc'].id, 'date': day,
            'ref': f'{prefix}NOORIX-SALES SHAMI {day} | SYNTHETIC | src:{source_id}',
            'line_ids': [
                Command.create({'name': 'Synthetic funding',
                                'account_id': self.company_data['default_journal_bank'].default_account_id.id,
                                'debit': float(gross)}),
                Command.create({'name': 'Synthetic sales',
                                'account_id': self.company_data['default_account_revenue'].id,
                                'credit': float(net)}),
                Command.create({'name': 'Synthetic VAT', 'account_id': self.noorix_tax_account.id,
                                'credit': float(vat), **tax_values}),
            ],
        })
        move.action_post()
        return move

    def _noorix_row(self, move, source_id='test-origin-1', customers=3, scope='all'):
        return {
            'company_id': move.company_id.id, 'move_id': move.id,
            'source_tenant': 'hajrix.com', 'source_company_key': 'SHAMI', 'source_id': source_id,
            'business_date': move.date.isoformat(), 'period_scope': scope,
            'customer_count': customers,
            'source_gross': str(sum((Decimal(str(line.debit)) for line in move.line_ids), Decimal('0.00'))),
            'extracted_at': '2026-11-06 12:00:00',
            'source_digest': hashlib.sha256(f'synthetic-only:{source_id}'.encode()).hexdigest(),
        }


@tagged('post_install', '-at_install')
class TestNoorixEvidence(NoorixEvidenceFixtures, AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_noorix_evidence_fixtures()
        cls.Evidence = cls.env['baseer.noorix.sales.evidence']

    def test_import_is_metadata_only_and_exact_retry_is_noop(self):
        move = self._noorix_entry()
        row = self._noorix_row(move)
        models = ('account.move', 'account.move.line', 'pos.order', 'pos.session', 'baseer.pos.summary')
        before = {name: self.env[name].search_count([]) for name in models}
        move_before = self.Evidence._ledger_digest(move)
        ids = self.Evidence.import_evidence([row, dict(row)])
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.Evidence.import_evidence([row]), ids[:1])
        evidence = self.Evidence.browse(ids[0])
        self.assertEqual(evidence._validated_amount(), Decimal('115.00'))
        self.assertEqual(evidence.customer_count, 3)
        self.assertEqual(evidence.create_uid, self.env.user)
        self.assertEqual({name: self.env[name].search_count([]) for name in models}, before)
        self.assertEqual(self.Evidence._ledger_digest(move), move_before)

    def test_live_agent_prefix_and_true_source_id_are_supported(self):
        move = self._noorix_entry(source_id='test-origin-1', agent_prefix=True)
        ident = self.Evidence.import_evidence([self._noorix_row(move)])[0]
        self.assertEqual(self.Evidence.browse(ident)._validated_amount(), Decimal('115.00'))

    def test_official_tax_line_and_configured_tagged_tax_are_supported(self):
        moves = [self._noorix_entry(source_id=f'tax-{kind}', tax_evidence=kind)
                 for kind in ('official', 'tags')]
        self.assertTrue(moves[0].line_ids.tax_line_id)
        self.assertFalse(moves[1].line_ids.tax_line_id)
        ids = self.Evidence.import_evidence([
            self._noorix_row(move, source_id=f'tax-{kind}')
            for move, kind in zip(moves, ('official', 'tags'))])
        self.assertEqual(self.Evidence.browse(ids)._validated_amounts(),
                         {ident: Decimal('115.00') for ident in ids})

    def test_unclassified_vat_account_is_not_sufficient_evidence(self):
        move = self._noorix_entry(tax_evidence='none')
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([self._noorix_row(move)])
        self.assertFalse(self.Evidence.search([('move_id', '=', move.id)]))

    def test_conflicting_retry_and_late_bad_row_are_atomic(self):
        first = self._noorix_entry(source_id='original')
        row = self._noorix_row(first, source_id='original')
        ids = self.Evidence.import_evidence([row])
        second = self._noorix_entry(source_id='second')
        second_row = self._noorix_row(second, source_id='second')
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([second_row, dict(row, customer_count=4)])
        self.assertFalse(self.Evidence.search([('move_id', '=', second.id)]))
        self.assertEqual(self.Evidence.browse(ids).customer_count, 3)
        bad = self._noorix_entry(source_id='bad-vat', tax_evidence='none')
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([second_row, self._noorix_row(bad, source_id='bad-vat')])
        self.assertFalse(self.Evidence.search([('move_id', 'in', [second.id, bad.id])]))

    def test_same_source_or_move_cannot_be_reassigned(self):
        first = self._noorix_entry(source_id='original')
        row = self._noorix_row(first, source_id='original')
        self.Evidence.import_evidence([row])
        second = self._noorix_entry(source_id='other')
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([dict(row, move_id=second.id)])
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([dict(row, source_id='other')])

    def test_boolean_nonfinite_precision_and_forged_audit_values_rejected(self):
        row = self._noorix_row(self._noorix_entry())
        for changes in ({'customer_count': True}, {'customer_count': -1}, {'move_id': True},
                        {'source_gross': 'NaN'}, {'source_gross': 'Infinity'},
                        {'source_gross': '115.001'}, {'source_gross': -1},
                        {'source_digest': 'not-a-digest'}, {'source_id': 'wrong source'},
                        {'ledger_digest': '0' * 64}, {'create_uid': self.env.user.id}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.Evidence.import_evidence([dict(row, **changes)])
        with self.assertRaises(ValidationError):
            self.Evidence.import_evidence([row] * 10001)
        self.assertFalse(self.Evidence.search([('move_id', '=', row['move_id'])]))

    def test_mismatched_date_source_company_and_amount_are_rejected(self):
        row = self._noorix_row(self._noorix_entry())
        for changes in ({'business_date': '2026-11-02'}, {'source_company_key': 'SHAMITAX'},
                        {'source_id': 'another-event'}, {'source_gross': '116.00'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.Evidence.import_evidence([dict(row, **changes)])

    def test_direct_create_size_cap_rejects_before_any_write(self):
        row = self._noorix_row(self._noorix_entry())
        models = ('baseer.noorix.sales.evidence', 'account.move', 'account.move.line',
                  'pos.order', 'pos.session', 'baseer.pos.summary')
        before = {name: self.env[name].search_count([]) for name in models}
        with self.assertRaisesRegex(ValidationError, 'at most 10,000'):
            self.Evidence.create([dict(row) for _ in range(10001)])
        self.assertEqual({name: self.env[name].search_count([]) for name in models}, before)

    def test_source_drift_is_detected_without_rewriting_evidence(self):
        move = self._noorix_entry()
        evidence = self.Evidence.browse(self.Evidence.import_evidence([self._noorix_row(move)]))
        digest = evidence.ledger_digest
        move.ref += ' | changed-after-snapshot'
        with self.assertRaisesRegex(ValidationError, 'changed after evidence extraction'):
            evidence._validated_amount()
        self.assertEqual(evidence.ledger_digest, digest)
        with self.assertRaises(AccessError):
            evidence.write({'customer_count': 4})

    def test_ordinary_reader_cannot_import_change_or_remove_metadata(self):
        move = self._noorix_entry()
        row = self._noorix_row(move)
        evidence = self.Evidence.browse(self.Evidence.import_evidence([row]))
        reader = new_test_user(self.env, login='noorix_evidence_reader',
                               groups='base.group_user,account.group_account_readonly',
                               company_id=self.env.company.id,
                               company_ids=[Command.set(self.env.company.ids)])
        with self.assertRaises(AccessError):
            self.Evidence.with_user(reader).import_evidence([row])
        with self.assertRaises(AccessError):
            self.Evidence.with_user(reader).create(row)
        with self.assertRaises(AccessError):
            evidence.with_user(reader).write({'customer_count': 4})
        with self.assertRaises(AccessError):
            evidence.with_user(reader).unlink()

    def test_foreign_company_import_is_rejected_before_any_metadata_write(self):
        row = self._noorix_row(self._noorix_entry())
        foreign = self.env['res.company'].create({'name': 'Synthetic Noorix foreign company',
                                                 'currency_id': self.env.company.currency_id.id})
        with self.assertRaises(AccessError):
            self.Evidence.import_evidence([dict(row, company_id=foreign.id)])
        self.assertFalse(self.Evidence.search([('move_id', '=', row['move_id'])]))
