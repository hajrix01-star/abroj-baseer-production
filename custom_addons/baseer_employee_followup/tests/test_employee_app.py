from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from ..controllers import employee_app
from ..controllers.employee_app import EmployeeFollowupApp


@tagged('post_install', '-at_install')
class TestEmployeeApp(TransactionCase):
    def test_daily_board_fallback_has_complete_followup_payload(self):
        """A manager without an active employee must not trigger a 500 page."""
        self.assertEqual(
            EmployeeFollowupApp._empty_followup_cards(),
            {'open_notes': [], 'resolved_notes': []},
        )

    def test_manager_app_access_requires_explicit_user_toggle(self):
        """System administrators must not bypass the Baseer Shift user toggle."""
        app = EmployeeFollowupApp()
        self.env.user.baseer_manager_app_access = False
        with patch.object(
            employee_app,
            'request',
            SimpleNamespace(env=SimpleNamespace(user=self.env.user)),
        ):
            self.assertFalse(app._has_manager_app_access())
            self.env.user.baseer_manager_app_access = True
            self.assertTrue(app._has_manager_app_access())
