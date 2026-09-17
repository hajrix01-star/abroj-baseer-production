from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseBatchDraft(TransactionCase):
    def test_empty_draft_can_be_started_but_not_approved(self):
        """The Add invoice action may persist a new parent before adding its row."""
        batch = self.env['baseer.purchase.batch'].create({})

        self.assertEqual(batch.state, 'draft')
        self.assertFalse(batch.line_ids)
        with self.assertRaises(UserError):
            batch.action_approve()
