from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import inspect
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command, SUPERUSER_ID, api, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.baseer_noorix_migration import karak_purchase_writer as writer
from ..models.migration_models import WRITER_CONTEXT


CENT = Decimal('0.01')


@tagged('noorix_karak_purchase')
class NoorixKarakPurchaseMigrationCase(AccountTestInvoicingCommon):
    """Guard and accounting-contract coverage for NSM-KARAK-PURCHASE-1."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer = api.Environment(
            cls.env.cr,
            SUPERUSER_ID,
            {**cls.env.context, WRITER_CONTEXT: True},
        )
        cls.company = cls.env.company
        cls.purchase_journal = cls.company_data['default_journal_purchase']
        cls.payment_journal = cls.company_data['default_journal_bank']
        cls.expense_account = cls.company_data['default_account_expense']
        cls.product = cls.env['product.product'].create({
            'name': 'Karak historical purchase service',
            'company_id': cls.company.id,
            'type': 'service',
            'purchase_ok': True,
            'sale_ok': False,
        })
        tax_values = {
            'name': 'Karak test purchase VAT 15%',
            'amount': 15,
            'amount_type': 'percent',
            'type_tax_use': 'purchase',
        }
        if 'price_include_override' in cls.env['account.tax']._fields:
            tax_values['price_include_override'] = False
        cls.purchase_tax = cls.tax_purchase_a.copy(tax_values)
        cls.migration_run = cls.writer['baseer.noorix.migration.run'].create({
            'name': 'NOORIX-KARAK-PURCHASE-TEST',
            'source_archive_sha256': 'archive-karak-test',
            'source_tenant_id': 'tenant-karak',
            'payload_sha256': 'payload-karak-test',
            'scope': 'purchase_history',
        })

    def _category_values(self, mapping_key='category:food'):
        return {
            'source_tenant_id': 'tenant-karak',
            'source_company_id': 'karak-company',
            'source_mapping_key': mapping_key,
            'source_category_id': 'food',
            'source_category_name': 'مواد غذائية أخرى',
            'source_row_sha256': 'category-row-' + mapping_key,
            'source_archive_sha256': self.migration_run.source_archive_sha256,
            'canonical_key': 'karak-purchase:' + mapping_key,
            'decision': 'create_historical_service',
            'tax_policy': 'tax_when_source_positive',
            'product_id': self.product.id,
            'account_id': self.expense_account.id,
            'run_id': self.migration_run.id,
        }

    def _category(self, mapping_key='category:food'):
        return self.writer['baseer.noorix.purchase.category.map'].create(
            self._category_values(mapping_key)
        )

    def _accounting_targets(self, amount=Decimal('1322.50')):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': self.company.id,
            'journal_id': self.purchase_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.to_date('2026-03-23'),
            'invoice_line_ids': [Command.create({
                'name': 'Karak historical purchase test',
                'product_id': self.product.id,
                'account_id': self.expense_account.id,
                'quantity': 1,
                'price_unit': float(amount),
                'tax_ids': [Command.clear()],
            })],
        })
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'partner_id': self.partner_a.id,
            'amount': float(amount),
            'currency_id': self.company.currency_id.id,
            'date': fields.Date.to_date('2026-03-23'),
            'journal_id': self.payment_journal.id,
            'payment_method_line_id': self.payment_journal.outbound_payment_method_line_ids[:1].id,
        })
        payment.action_post()
        return bill, payment, payment.move_id

    def _invoice_values(
        self,
        category,
        source_invoice_id='karak-invoice-1',
        row_sha='invoice-row-1',
        amount=Decimal('1322.50'),
        targets=None,
    ):
        bill, payment, payment_move = targets or self._accounting_targets(amount)
        return {
            'source_tenant_id': 'tenant-karak',
            'source_company_id': 'karak-company',
            'source_invoice_id': source_invoice_id,
            'source_ledger_id': 'ledger-' + source_invoice_id,
            'source_allocation_id': 'allocation-' + source_invoice_id,
            'source_vault_id': 'vault-bank',
            'source_supplier_id': 'supplier-computer',
            'source_category_id': 'electronics',
            'source_invoice_number': '006390',
            'source_supplier_invoice_number': '006390',
            'source_document_kind': 'expense',
            'business_date': fields.Date.to_date('2026-03-23'),
            'source_net_raw': '1150.0000',
            'source_tax_raw': '172.5000',
            'source_total_raw': '1322.5000',
            'source_row_sha256': row_sha,
            'source_archive_sha256': self.migration_run.source_archive_sha256,
            'canonical_key': 'purchase:karak-company:' + source_invoice_id,
            'decision': 'create_paid_vendor_bill',
            'company_id': self.company.id,
            'category_map_id': category.id,
            'partner_id': self.partner_a.id,
            'purchase_journal_id': self.purchase_journal.id,
            'payment_journal_id': self.payment_journal.id,
            'bill_id': bill.id,
            'payment_id': payment.id,
            'payment_move_id': payment_move.id,
            'target_net': float(amount),
            'target_tax': 0,
            'target_total': float(amount),
            'run_id': self.migration_run.id,
        }

    def _valid_payload(self):
        """Small-valued but cardinality-exact payload for the pure validator."""
        category_rows = []
        for index in range(15):
            decision = 'create_historical_service'
            account_code = '400047'
            if index == 2:
                decision = 'document_expense_override'
                account_code = '400050'
            elif index == 3:
                decision = 'document_asset_override'
                account_code = '106003'
            small_cash = index in (1, 14)
            product_code = (
                'NOORIX-HIST-KARAK-SMALL-CASH'
                if small_cash else 'KARAK-TEST-%s' % index
            )
            category_rows.append({
                'source_system': 'noorix',
                'source_tenant_id': writer.SOURCE_TENANT_ID,
                'source_company_id': writer.SOURCE_COMPANY_ID,
                'source_mapping_key': 'category:%s' % index,
                'source_category_id': 'source-category-%s' % index,
                'source_category_name': 'Category %s' % index,
                'source_row_sha256': '%064x' % (index + 1),
                'source_archive_sha256': writer.ARCHIVE_SHA256,
                'canonical_key': 'karak-purchase:test-%s' % index,
                'decision': decision,
                'tax_policy': 'no_tax' if small_cash else 'tax_when_source_positive',
                'target_product_id': None,
                'target_product_code': product_code,
                'target_product_name': (
                    'Karak small-cash historical service'
                    if small_cash else 'Karak test service %s' % index
                ),
                'target_account_id': self.expense_account.id,
                'target_account_code': account_code,
            })

        month_counts = (('2026-03', 60), ('2026-04', 60), ('2026-05', 60),
                        ('2026-06', 60), ('2026-07', 66))
        month_by_index = []
        for month, count in month_counts:
            month_by_index.extend([month] * count)
        documents = []
        for index in range(306):
            taxable = index < 228
            gross = Decimal('1.15') if taxable else Decimal('1.00')
            net = Decimal('1.00')
            tax = Decimal('0.15') if taxable else Decimal('0.00')
            month = month_by_index[index]
            journal_id = 62 if index < 62 else 67
            if index == 0:
                journal_id = 67
            elif index == 62:
                journal_id = 62
            category_index = 0 if taxable else 1
            decision = 'create_paid_vendor_bill'
            source_asset_id = None
            source_asset_sha = None
            if index == 0:
                category_index = 2
                invoice_number = 'EXP-20260323-001'
            elif index == 1:
                category_index = 3
                invoice_number = 'EXP-20260323-002'
                decision = 'capitalize_cashier_computer'
                source_asset_id = 'karak-cashier-computer'
                source_asset_sha = 'f' * 64
            else:
                invoice_number = 'KARAK-%03d' % index
            if index < 3:
                document_kind = 'expense'
            elif index < 296:
                document_kind = 'purchase'
            else:
                document_kind = 'fixed_expense'
            category = category_rows[category_index]
            documents.append({
                'source_system': 'noorix',
                'source_tenant_id': writer.SOURCE_TENANT_ID,
                'source_company_id': writer.SOURCE_COMPANY_ID,
                'source_invoice_id': 'invoice-%03d' % index,
                'source_ledger_id': 'ledger-%03d' % index,
                'source_allocation_id': 'allocation-%03d' % index,
                'source_vault_id': 'vault-%03d' % index,
                'source_supplier_id': 'supplier-%02d' % (index % 23),
                'source_category_id': 'source-category-%s' % category_index,
                'source_invoice_number': invoice_number,
                'source_supplier_invoice_number': '',
                'source_document_kind': document_kind,
                'business_date': month + '-01',
                'month': month,
                'source_net_raw': format(net, '.4f'),
                'source_tax_raw': format(tax, '.4f'),
                'source_total_raw': format(gross, '.4f'),
                'source_row_sha256': '%064x' % (1000 + index),
                'source_archive_sha256': writer.ARCHIVE_SHA256,
                'canonical_key': 'purchase:test:%03d' % index,
                'source_asset_id': source_asset_id,
                'source_asset_row_sha256': source_asset_sha,
                'decision': decision,
                'category_mapping_key': 'category:%s' % category_index,
                'target_company_id': writer.TARGET_COMPANY_ID,
                'target_partner_id': index + 1,
                'target_tax_id': 139 if taxable else None,
                'target_purchase_journal_id': 58,
                'target_payment_journal_id': journal_id,
                'target_account_id': self.expense_account.id,
                'target_account_code': category['target_account_code'],
                'target_product_id': None,
                'target_product_code': category['target_product_code'],
                'target_product_name': category['target_product_name'],
                'price_unit': str(net),
                'target_net': format(net, '.2f'),
                'target_tax': format(tax, '.2f'),
                'target_total': format(gross, '.2f'),
            })
        months = {}
        for month, count in month_counts:
            rows = [row for row in documents if row['month'] == month]
            months[month] = {
                'documents': count,
                'gross': format(sum(Decimal(row['target_total']) for row in rows), '.2f'),
            }
        report = {
            'source_documents': 306,
            'taxable_documents': 228,
            'no_tax_documents': 78,
            'category_decisions': 15,
            'source_net': '306.0000',
            'source_tax': '34.2000',
            'source_gross': '340.2000',
            'target_net': '306.00',
            'target_tax': '34.20',
            'target_gross': '340.20',
            'months': months,
        }
        payload = {
            'target_database': writer.TARGET_DATABASE,
            'source_archive_sha256': writer.ARCHIVE_SHA256,
            'approved_policy': writer.APPROVED_POLICY,
            'report': report,
            'allowlist': {
                **deepcopy(writer.EXPECTED_ALLOWLIST),
                'vat_input_account_id': 12345,
            },
            'category_decisions': category_rows,
            'documents': documents,
        }
        return payload, report

    @staticmethod
    def _finite_policy_for(payload):
        return {
            row['target_product_code']: (
                row['target_account_code'],
                row['tax_policy'],
                row['decision'],
                row['target_product_id'],
            )
            for row in payload['category_decisions']
        }

    def test_purchase_category_map_is_writer_only_write_once_and_append_only(self):
        values = self._category_values()
        with self.assertRaises(AccessError):
            self.env['baseer.noorix.purchase.category.map'].create(values)

        mapping = self.writer['baseer.noorix.purchase.category.map'].create(values)
        self.assertEqual(mapping.run_id.scope, 'purchase_history')
        with self.assertRaises(UserError):
            mapping.write({'canonical_key': 'changed'})
        with self.assertRaises(AccessError):
            mapping.unlink()

    def test_purchase_invoice_map_is_writer_only_write_once_and_append_only(self):
        category = self._category()
        values = self._invoice_values(category)
        with self.assertRaises(AccessError):
            self.env['baseer.noorix.purchase.invoice.map'].create(values)

        mapping = self.writer['baseer.noorix.purchase.invoice.map'].create(values)
        self.assertEqual(mapping.source_total_raw, '1322.5000')
        with self.assertRaises(UserError):
            mapping.write({'source_row_sha256': 'changed'})
        with self.assertRaises(AccessError):
            mapping.unlink()

    @mute_logger('odoo.sql_db')
    def test_purchase_category_source_identity_is_unique(self):
        model = self.writer['baseer.noorix.purchase.category.map']
        values = self._category_values()
        original = model.create(values)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            model.create({**values, 'source_row_sha256': 'changed-category-hash'})
        self.assertEqual(original.source_row_sha256, values['source_row_sha256'])

    @mute_logger('odoo.sql_db')
    def test_replay_changed_hash_is_rejected_by_unique_source_identity(self):
        category = self._category()
        model = self.writer['baseer.noorix.purchase.invoice.map']
        original = model.create(self._invoice_values(category))
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            model.create(self._invoice_values(
                category,
                source_invoice_id=original.source_invoice_id,
                row_sha='changed-source-row-hash',
            ))
        self.assertEqual(original.source_row_sha256, 'invoice-row-1')
        self.assertEqual(model.search_count([
            ('source_system', '=', 'noorix'),
            ('source_tenant_id', '=', 'tenant-karak'),
            ('source_company_id', '=', 'karak-company'),
            ('source_invoice_id', '=', original.source_invoice_id),
        ]), 1)

    def test_writer_replay_reports_changed_source_hash_as_a_clear_user_error(self):
        category = self._category()
        mapping = self.writer['baseer.noorix.purchase.invoice.map'].create(
            self._invoice_values(category)
        )
        direct_fields = (
            'source_system', 'source_tenant_id', 'source_company_id', 'source_invoice_id',
            'source_ledger_id', 'source_allocation_id', 'source_vault_id', 'source_supplier_id',
            'source_invoice_number', 'source_supplier_invoice_number', 'source_document_kind',
            'source_row_sha256', 'source_archive_sha256', 'canonical_key', 'source_asset_id',
            'source_asset_row_sha256', 'decision',
        )
        replay_row = {field_name: mapping[field_name] or None for field_name in direct_fields}
        replay_row['source_row_sha256'] = 'changed-source-row-hash'
        with self.assertRaisesRegex(UserError, 'source_row_sha256'):
            writer._verify_invoice_mapping(mapping, replay_row, self.company)

    def test_equal_1322_50_documents_with_distinct_source_ids_remain_separate(self):
        category = self._category()
        model = self.writer['baseer.noorix.purchase.invoice.map']
        first = model.create(self._invoice_values(
            category,
            source_invoice_id='EXP-20260323-001',
            row_sha='cash-computer-row',
        ))
        second_values = self._invoice_values(
            category,
            source_invoice_id='EXP-20260323-002',
            row_sha='bank-computer-row',
        )
        second_values.update({
            'decision': 'capitalize_cashier_computer',
            'source_asset_id': 'cashier-computer',
            'source_asset_row_sha256': 'cashier-computer-row',
        })
        second = model.create(second_values)

        self.assertNotEqual(first.source_invoice_id, second.source_invoice_id)
        self.assertEqual(first.source_invoice_number, second.source_invoice_number)
        self.assertEqual(first.partner_id, second.partner_id)
        self.assertEqual(first.business_date, second.business_date)
        self.assertEqual(first.target_total, second.target_total)
        self.assertEqual(model.search_count([('id', 'in', (first + second).ids)]), 2)

    def test_high_precision_tax_input_reproduces_228_rounded_gross_values(self):
        # Frozen gross values of the 228 taxable source documents.  Repeated
        # values are intentional: source identity, not amount, defines a row.
        gross_values = (
            '306.03', '1322.50', '1322.50', '15.00', '70.00', '14.00', '15.00', '13.50',
            '15.00', '15.00', '31.00', '759.00', '950.00', '14.00', '10.20', '30.00',
            '100.00', '18.00', '30.00', '1103.00', '13.00', '15.00', '9.60', '13.50',
            '124.20', '489.00', '15.00', '719.00', '120.00', '15.00', '240.00', '15.00',
            '25.00', '12.50', '70.00', '15.00', '19.00', '35.00', '11.00', '15.00',
            '40.00', '420.00', '531.16', '687.47', '1337.00', '228.85', '554.70', '23.00',
            '138.00', '421.71', '30.00', '67.00', '15.50', '556.70', '80.00', '15.00',
            '25.00', '1092.68', '15.00', '30.00', '35.00', '36.00', '6.00', '969.80',
            '30.00', '34.00', '20.00', '4.00', '809.39', '795.83', '105.00', '37.00',
            '13.00', '67.00', '15.00', '130.00', '15.00', '80.00', '15.00', '30.50',
            '31.00', '24.00', '40.00', '15.00', '96.00', '90.00', '29.50', '34.50',
            '13.00', '28.00', '15.00', '15.00', '15.00', '15.00', '25.00', '37.00',
            '50.00', '4.00', '24.00', '155.00', '52.00', '129.00', '354.00', '551.00',
            '411.00', '1174.55', '1191.14', '678.16', '807.11', '15.00', '15.00', '15.00',
            '30.00', '5.00', '130.00', '13.00', '30.00', '29.00', '25.00', '15.00',
            '15.00', '72.00', '25.00', '15.00', '5.00', '30.00', '15.00', '420.00',
            '19.00', '15.00', '65.00', '13.00', '15.00', '80.00', '16.00', '29.00',
            '30.00', '10.00', '15.00', '17.00', '7.00', '4.00', '15.00', '25.00',
            '2122.08', '1154.30', '6.00', '12.00', '25.00', '468.00', '139.15', '88.00',
            '723.29', '801.19', '865.53', '574.45', '503.94', '540.50', '733.14', '299.77',
            '567.04', '807.70', '502.30', '636.70', '457.36', '695.00', '13.00', '99.00',
            '425.00', '8.50', '426.00', '19.00', '15.00', '938.00', '100.00', '23.00',
            '543.56', '60.00', '8.00', '5.00', '3.00', '644.00', '45.00', '34.00',
            '1318.00', '100.00', '24.00', '443.00', '35.00', '20.00', '10.00', '703.00',
            '10.00', '13.00', '15.00', '592.00', '15.00', '5.00', '21.00', '991.68',
            '828.21', '138.00', '345.00', '511.00', '100.00', '15.00', '671.00', '15.00',
            '390.00', '64.00', '15.00', '20.00', '631.00', '25.00', '20.00', '25.00',
            '314.00', '21.00', '15.00', '1130.00', '50.00', '100.00', '15.00', '50.00',
            '60.00', '5.00', '44.00', '100.00',
        )
        self.assertEqual(len(gross_values), 228)
        for raw_gross in gross_values:
            gross = Decimal(raw_gross)
            price_unit = writer.high_precision_price_unit(gross, True)
            target_net = writer.money(price_unit)
            target_tax = writer.money(price_unit * Decimal('0.15'))
            self.assertEqual(target_net + target_tax, gross)

    def test_raw_source_amounts_require_exact_nonnegative_four_decimal_strings(self):
        self.assertEqual(writer.source_decimal('1322.5000'), Decimal('1322.5000'))
        for invalid in (1322.5, '1322.50', '-1.0000', 'NaN', '1e3', None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                writer.source_decimal(invalid)

    def test_the_19_cent_edges_prove_net_must_not_be_rounded_first(self):
        edge_gross_values = (
            '240.00', '35.00', '11.00', '80.00', '35.00', '34.00', '80.00',
            '807.11', '80.00', '10.00', '12.00', '865.53', '425.00', '426.00',
            '34.00', '35.00', '10.00', '10.00', '631.00',
        )
        deltas = []
        for raw_gross in edge_gross_values:
            gross = Decimal(raw_gross)
            rounded_net = (gross / Decimal('1.15')).quantize(CENT, rounding=ROUND_HALF_UP)
            wrongly_recomputed_tax = (rounded_net * Decimal('0.15')).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            deltas.append(rounded_net + wrongly_recomputed_tax - gross)
        self.assertEqual(len(deltas), 19)
        self.assertTrue(all(abs(delta) == CENT for delta in deltas))
        self.assertEqual(sum(deltas), Decimal('0.05'))

    def test_pure_payload_validation_enforces_company_journal_account_and_tax_allowlists(self):
        payload, report = self._valid_payload()
        finite_policy = self._finite_policy_for(payload)
        with patch.object(writer, 'EXPECTED_REPORT', report), patch.object(
            writer, 'FINITE_PRODUCT_POLICY', finite_policy,
        ):
            grouped = writer.validate_payload(payload)
        self.assertEqual(sum(map(len, grouped.values())), 306)
        self.assertEqual(sum(
            row['target_tax_id'] is None for rows in grouped.values() for row in rows
        ), 78)

        mutations = (
            ('company', lambda candidate: candidate['documents'][0].update(
                target_company_id=writer.TARGET_COMPANY_ID + 1
            )),
            ('purchase journal', lambda candidate: candidate['documents'][0].update(
                target_purchase_journal_id=69
            )),
            ('payment journal', lambda candidate: candidate['documents'][0].update(
                target_payment_journal_id=69
            )),
            ('account', lambda candidate: candidate['documents'][0].update(
                target_account_code='999999'
            )),
            ('tax', lambda candidate: candidate['documents'][0].update(target_tax_id=None)),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                candidate = deepcopy(payload)
                mutate(candidate)
                with patch.object(writer, 'EXPECTED_REPORT', report), patch.object(
                    writer, 'FINITE_PRODUCT_POLICY', finite_policy,
                ), self.assertRaises(UserError):
                    writer.validate_payload(candidate)

    def test_asset_override_requires_asset_evidence_and_fixed_asset_account(self):
        payload, report = self._valid_payload()
        finite_policy = self._finite_policy_for(payload)
        with patch.object(writer, 'EXPECTED_REPORT', report), patch.object(
            writer, 'FINITE_PRODUCT_POLICY', finite_policy,
        ):
            writer.validate_payload(payload)

        missing_evidence = deepcopy(payload)
        asset_row = next(
            row for row in missing_evidence['documents']
            if row['source_invoice_number'] == 'EXP-20260323-002'
        )
        asset_row['source_asset_id'] = None
        asset_row['source_asset_row_sha256'] = None
        with patch.object(writer, 'EXPECTED_REPORT', report), patch.object(
            writer, 'FINITE_PRODUCT_POLICY', finite_policy,
        ), self.assertRaises(UserError):
            writer.validate_payload(missing_evidence)

        expense_account = deepcopy(payload)
        asset_row = next(
            row for row in expense_account['documents']
            if row['source_invoice_number'] == 'EXP-20260323-002'
        )
        category = next(
            row for row in expense_account['category_decisions']
            if row['source_mapping_key'] == asset_row['category_mapping_key']
        )
        asset_row['target_account_code'] = '400050'
        category['target_account_code'] = '400050'
        with patch.object(writer, 'EXPECTED_REPORT', report), patch.object(
            writer, 'FINITE_PRODUCT_POLICY', finite_policy,
        ), self.assertRaises(UserError):
            writer.validate_payload(expense_account)

    def test_native_taxed_bill_has_one_payment_full_reconciliation_and_no_stock(self):
        gross = Decimal('115.00')
        counts_before = {
            model: self.env[model].search_count([])
            for model in (
                'account.move', 'account.payment', 'stock.move', 'stock.picking', 'stock.quant',
            )
        }
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': self.company.id,
            'journal_id': self.purchase_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.to_date('2026-03-23'),
            'date': fields.Date.to_date('2026-03-23'),
            'invoice_line_ids': [Command.create({
                'name': 'Karak taxed historical purchase',
                'product_id': self.product.id,
                'account_id': self.expense_account.id,
                'quantity': 1,
                'price_unit': float(writer.high_precision_price_unit(gross, True)),
                'tax_ids': [Command.set(self.purchase_tax.ids)],
            })],
        })
        self.assertEqual(writer.money(bill.amount_untaxed), Decimal('100.00'))
        self.assertEqual(writer.money(bill.amount_tax), Decimal('15.00'))
        self.assertEqual(writer.money(bill.amount_total), gross)
        bill.action_post()
        payment = self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=bill.ids,
        ).create({
            'journal_id': self.payment_journal.id,
            'payment_method_line_id': self.payment_journal.outbound_payment_method_line_ids[:1].id,
            'amount': float(gross),
            'payment_date': fields.Date.to_date('2026-03-23'),
            'installments_mode': 'full',
            'payment_difference_handling': 'open',
        })._create_payments()
        bill.invalidate_recordset()

        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.move_id.state, 'posted')
        self.assertEqual(writer.money(bill.amount_residual), Decimal('0.00'))
        payable_lines = (bill.line_ids + payment.move_id.line_ids).filtered(
            lambda line: line.account_id.account_type == 'liability_payable'
        )
        self.assertTrue(payable_lines)
        self.assertTrue(all(payable_lines.mapped('reconciled')))
        self.assertTrue(payable_lines.full_reconcile_id)
        self.assertEqual(
            self.env['account.move'].search_count([]) - counts_before['account.move'], 2
        )
        self.assertEqual(
            self.env['account.payment'].search_count([]) - counts_before['account.payment'], 1
        )
        for model in ('stock.move', 'stock.picking', 'stock.quant'):
            self.assertEqual(self.env[model].search_count([]), counts_before[model])

    def test_no_tax_document_has_an_empty_tax_list_not_a_zero_percent_tax(self):
        bill = self.env['account.move'].create({
            'move_type': 'in_invoice',
            'company_id': self.company.id,
            'journal_id': self.purchase_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_date': fields.Date.to_date('2026-04-01'),
            'invoice_line_ids': [Command.create({
                'name': 'Karak no-tax historical purchase',
                'product_id': self.product.id,
                'account_id': self.expense_account.id,
                'quantity': 1,
                'price_unit': 19,
                'tax_ids': [Command.clear()],
            })],
        })
        self.assertFalse(bill.invoice_line_ids.tax_ids)
        self.assertEqual(writer.money(bill.amount_untaxed), Decimal('19.00'))
        self.assertEqual(writer.money(bill.amount_tax), Decimal('0.00'))
        self.assertEqual(writer.money(bill.amount_total), Decimal('19.00'))

    def test_month_writer_owns_no_commit_or_internal_savepoint(self):
        source = inspect.getsource(writer.apply_month)
        self.assertNotIn('.commit(', source)
        self.assertNotIn('.savepoint(', source)

    def test_month_failure_rolls_back_run_category_and_invoice_maps_together(self):
        Run = self.writer['baseer.noorix.migration.run']
        CategoryMap = self.writer['baseer.noorix.purchase.category.map']
        InvoiceMap = self.writer['baseer.noorix.purchase.invoice.map']
        tracked_models = (
            'baseer.noorix.migration.run',
            'baseer.noorix.purchase.category.map',
            'baseer.noorix.purchase.invoice.map',
            'account.move',
            'account.payment',
        )
        before = {
            model: (
                self.writer[model] if model.startswith('baseer.noorix.') else self.env[model]
            ).search_count([])
            for model in tracked_models
        }

        with self.assertRaisesRegex(RuntimeError, 'injected monthly failure'):
            with self.env.cr.savepoint():
                run = Run.create({
                    'name': 'NOORIX-KARAK-ATOMIC-MONTH',
                    'source_archive_sha256': 'atomic-archive',
                    'source_tenant_id': 'tenant-karak',
                    'payload_sha256': 'atomic-payload',
                    'scope': 'purchase_history',
                })
                category = CategoryMap.create({
                    **self._category_values('category:atomic'), 'run_id': run.id,
                })
                invoice_values = self._invoice_values(
                    category,
                    source_invoice_id='karak-atomic-invoice',
                    row_sha='karak-atomic-row',
                )
                invoice_values['run_id'] = run.id
                InvoiceMap.create(invoice_values)
                raise RuntimeError('injected monthly failure')

        for model in tracked_models:
            records = self.writer[model] if model.startswith('baseer.noorix.') else self.env[model]
            self.assertEqual(records.search_count([]), before[model])
