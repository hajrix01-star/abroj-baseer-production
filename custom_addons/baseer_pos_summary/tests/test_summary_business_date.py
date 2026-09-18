from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSummaryBusinessDate(TransactionCase):

    def test_future_sales_date_is_rejected_before_native_pos_posting(self):
        summaries = self.env['baseer.pos.summary']
        tomorrow = fields.Date.context_today(summaries) + timedelta(days=1)
        with self.assertRaisesRegex(ValidationError, 'cannot be in the future'):
            summaries._validate_values({'business_date': tomorrow})

    def test_today_sales_date_remains_allowed(self):
        summaries = self.env['baseer.pos.summary']
        summaries._validate_values({'business_date': fields.Date.context_today(summaries)})
