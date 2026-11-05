from datetime import datetime
from types import SimpleNamespace

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_payroll.models.advance_snapshot import BaseerLoanSnapshot


@tagged('post_install', '-at_install')
class TestAdvanceSnapshot(TransactionCase):
    def test_snapshot_token_is_scoped_and_round_trips_without_secrets(self):
        payload = {
            'user_id': self.env.user.id, 'company_key': 'arz', 'cutoff': '2026-10-31',
            'employee_id': 0, 'max_loan_id': 12, 'max_line_id': 24, 'max_allocation_id': 36,
        }
        token = BaseerLoanSnapshot._encode_token(payload)
        self.assertEqual(BaseerLoanSnapshot._decode_token(token), payload)
        self.assertNotIn('password', token.lower())

    def test_invalid_snapshot_token_is_rejected(self):
        with self.assertRaises(ValidationError):
            BaseerLoanSnapshot._decode_token('not a token')

    def test_post_cutoff_change_is_not_silently_used_as_historic_balance(self):
        cutoff_end = datetime(2026, 10, 31, 20, 59, 59)
        before = SimpleNamespace(create_date=datetime(2026, 10, 1), write_date=datetime(2026, 10, 30))
        after = SimpleNamespace(create_date=datetime(2026, 10, 1), write_date=datetime(2026, 11, 1))
        self.assertEqual(BaseerLoanSnapshot._proof(before, cutoff_end), ('verified', False))
        self.assertEqual(
            BaseerLoanSnapshot._proof(after, cutoff_end),
            ('unverified', 'changed_after_cutoff'),
        )

    def test_reversal_is_unverified_even_when_dates_precede_cutoff(self):
        cutoff_end = datetime(2026, 10, 31, 20, 59, 59)
        record = SimpleNamespace(create_date=datetime(2026, 10, 1), write_date=datetime(2026, 10, 2))
        self.assertEqual(
            BaseerLoanSnapshot._proof(record, cutoff_end, reversal=True),
            ('unverified', 'reversal_requires_accounting_audit'),
        )
