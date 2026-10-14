"""The invoice picker must stop before its sudo search after revocation."""

from uuid import uuid4

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'baseer_bchat_document_permission_guards')
class BChatDocumentPermissionGuardsCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'BChat document guard user',
            'login': 'bchat-document-guard-%s' % uuid4().hex,
            'company_id': cls.env.company.id,
            'company_ids': [Command.set(cls.env.company.ids)],
            'group_ids': [Command.set([cls.env.ref('base.group_user').id])],
        })

    def test_invoice_picker_requires_chat_and_media(self):
        service = self.env['baseer.bchat.service'].with_user(self.user)
        self.user.write({'bchat_chat_view': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            service._v2_invoice_cases(2_000_000_000)
        self.user.write({'bchat_chat_view': True, 'bchat_media': False})
        with self.assertRaisesRegex(AccessError, 'not enabled'):
            service._v2_invoice_cases(2_000_000_000)
