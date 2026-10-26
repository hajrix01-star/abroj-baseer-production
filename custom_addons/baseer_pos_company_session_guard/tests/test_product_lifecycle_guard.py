from uuid import uuid4

from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductLifecycleGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env['res.company'].sudo().create({
            'name': 'POS lifecycle guard company B',
        })

    def _company_env(self, company):
        return self.env['pos.config'].sudo().with_context(
            allowed_company_ids=[company.id],
        ).with_company(company).env

    def _open_session(self, company):
        env = self._company_env(company)
        if not env['account.journal'].search([
            ('company_id', '=', company.id),
            ('type', '=', 'bank'),
        ], limit=1):
            env['account.journal'].create({
                'name': 'POS lifecycle guard bank',
                'code': ('PG' + uuid4().hex)[:5].upper(),
                'type': 'bank',
                'company_id': company.id,
            })
        config = env['pos.config'].create({
            'name': 'POS lifecycle guard ' + str(uuid4()),
            'company_id': company.id,
        })
        return env['pos.session'].create({
            'config_id': config.id,
            'user_id': env.user.id,
            'state': 'opened',
        })

    def _product(self, company=False, *, available_in_pos=True):
        env = self._company_env(company or self.company_a)
        return env['product.template'].create({
            'name': 'POS lifecycle guard ' + str(uuid4()),
            'available_in_pos': available_in_pos,
            'company_id': company.id if company else False,
        })

    def test_other_company_session_allows_archive_and_delete(self):
        self._open_session(self.company_b)

        archived = self._product(self.company_a)
        archived.action_archive()
        self.assertFalse(archived.active)

        deleted = self._product(self.company_a)
        deleted.unlink()
        self.assertFalse(deleted.exists())

    def test_own_company_session_blocks_archive_and_delete(self):
        self._open_session(self.company_a)

        archived = self._product(self.company_a)
        with self.assertRaises(UserError):
            archived.action_archive()
        self.assertTrue(archived.active)

        deleted = self._product(self.company_a)
        with self.assertRaises(UserError):
            deleted.unlink()
        self.assertTrue(deleted.exists())

    def test_shared_product_stays_globally_protected(self):
        self._open_session(self.company_b)
        shared = self._product()

        with self.assertRaises(UserError):
            shared.action_archive()
        with self.assertRaises(UserError):
            shared.unlink()

    def test_mixed_company_batch_checks_each_owned_company(self):
        self._open_session(self.company_b)
        product_a = self._product(self.company_a)
        product_b = self._product(self.company_b)

        with self.assertRaises(UserError):
            (product_a | product_b).action_archive()
        self.assertTrue(product_a.active)
        self.assertTrue(product_b.active)

    def test_mixed_batch_with_shared_product_keeps_global_guard(self):
        self._open_session(self.company_b)
        owned = self._product(self.company_a)
        shared = self._product()

        with self.assertRaises(UserError):
            (owned | shared).action_archive()
        self.assertTrue(owned.active)
        self.assertTrue(shared.active)

    def test_non_pos_product_is_not_blocked(self):
        self._open_session(self.company_a)

        archived = self._product(self.company_a, available_in_pos=False)
        archived.action_archive()
        self.assertFalse(archived.active)

        deleted = self._product(self.company_a, available_in_pos=False)
        deleted.unlink()
        self.assertFalse(deleted.exists())

    def test_archived_pos_product_is_still_checked_on_delete(self):
        product = self._product(self.company_a)
        product.action_archive()
        self.assertFalse(product.active)
        self._open_session(self.company_a)

        with self.assertRaises(UserError):
            product.unlink()
        self.assertTrue(product.exists())
