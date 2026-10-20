"""The invoice picker must stop before its sudo search after revocation."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_bwork_document_permission_guards')
class BWorkDocumentPermissionGuardsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BWork document guard user',
            'login': 'bwork-document-guard-%s' % uuid4().hex,
            'company_id': cls.env.company.id,
            'company_ids': [Command.set(cls.env.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })

    def test_invoice_picker_requires_chat_and_media(self):
        service = self.env['baseer.bwork.service'].with_user(self.user)
        self.user.write({'bwork_chat_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            service._v2_invoice_cases(2_000_000_000)
        self.user.write({'bwork_chat_view': True, 'bwork_media': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            service._v2_invoice_cases(2_000_000_000)
