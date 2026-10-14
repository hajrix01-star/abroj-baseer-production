import base64
from io import BytesIO

from lxml import etree
from PIL import Image

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged


class BillFixtures:
    """Synthetic empty draft bills: no chart, posting or operational documents."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Private evaluation confinement remains enabled on QA. Disable it only
        # inside this rolled-back test fixture to exercise the underlying ACLs.
        cls.env['ir.rule'].browse([
            cls.env.ref('baseer_dms_trial.' + name).id
            for name in ('private_storage', 'private_directory', 'private_file',
                         'private_group', 'private_share', 'private_attachment')
        ]).write({'active': False})
        cls.company_a, cls.company_b = cls.env['res.company'].create([
            {'name': 'Synthetic bill company A'}, {'name': 'Synthetic bill company B'},
        ])
        cls.accountant = new_test_user(
            cls.env, login='bill-accountant', password='bill-test',
            groups='dms.group_dms_manager,account.group_account_manager',
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)],
        )
        cls.nonaccount = new_test_user(
            cls.env, login='bill-no-account', password='bill-test',
            groups='dms.group_dms_manager', company_id=cls.company_a.id,
            company_ids=[(6, 0, cls.company_a.ids)],
        )
        cls.owner = cls.env.ref('base.user_admin')
        cls.owner.write({'company_ids': [(4, cls.company_a.id), (4, cls.company_b.id)]})
        cls.env = cls.env(context=dict(
            cls.env.context, allowed_company_ids=(cls.company_a | cls.company_b).ids,
        ))
        cls.access_group = cls.env['dms.access.group'].create({
            'name': 'Synthetic full DMS access', 'perm_create': True,
            'perm_write': True, 'perm_unlink': True,
            'explicit_user_ids': [(6, 0, (cls.accountant | cls.nonaccount | cls.owner).ids)],
        })
        cls.payload = base64.b64encode(b'Synthetic bill bytes, no real invoice.')
        cls.bills = cls.env['account.move']
        cls.roots = cls.env['dms.directory']
        for company in (cls.company_a, cls.company_b):
            journal = cls.env['account.journal'].with_company(company).create({
                'name': 'Synthetic purchase', 'code': 'SBIL', 'type': 'purchase',
                'company_id': company.id,
            })
            cls.bills |= cls.env['account.move'].with_company(company).create({
                'move_type': 'in_invoice', 'company_id': company.id,
                'journal_id': journal.id,
            })
            storage = cls.env['dms.storage'].create({
                'name': company.name, 'company_id': company.id, 'save_type': 'database',
                'model_ids': [(5, 0, 0)], 'include_message_attachments': False,
                'inherit_access_from_parent_record': False,
            })
            root = cls.env['dms.directory'].create({
                'name': 'Synthetic vendor bills', 'storage_id': storage.id,
                'is_root_directory': True, 'group_ids': [(6, 0, cls.access_group.ids)],
            })
            company.dms_bill_root_id = root
            cls.roots |= root
        cls.bill_a, cls.bill_b = cls.bills
        cls.root_a, cls.root_b = cls.roots
        cls.attachments = cls.env['ir.attachment'].create([
            {'name': 'synthetic-bill.txt', 'type': 'binary', 'datas': cls.payload,
             'res_model': 'account.move', 'res_id': bill.id, 'company_id': bill.company_id.id}
            for bill in cls.bills
        ])
        cls.attachment_a, cls.attachment_b = cls.attachments

    def index(self, attachment):
        return self.env['dms.file'].search([('bill_attachment_id', '=', attachment.id)])

    def actor(self, record, user=None):
        return record.with_user(user or self.accountant).with_context(
            allowed_company_ids=self.company_a.ids,
        )


@tagged('post_install', '-at_install', 'baseer_dms_bill_link')
class TestBillLink(BillFixtures, TransactionCase):
    def test_preview_backend_assets_compile_and_register_templates(self):
        # Compile once in isolated CI: HTTP content checks cannot establish that
        # the new widget, XML templates and SCSS reach a usable backend bundle.
        bundle = self.env['ir.qweb']._get_asset_bundle(
            'web.assets_backend', css=True, js=True, debug_assets=False,
        )
        javascript = bundle.js()
        stylesheets = bundle.css()
        self.assertTrue(javascript)
        self.assertTrue(stylesheets)
        self.assertFalse(bundle.css_errors, '\n'.join(bundle.css_errors))
        compiled_js = javascript.raw.decode()
        self.assertIn('baseer_dms_bill_link.PreviewDialog', compiled_js)
        self.assertIn('baseer_dms_bill_preview', compiled_js)
        compiled_css = b'\n'.join(stylesheets.mapped('raw')).decode()
        self.assertIn('o_baseer_bill_preview_canvas', compiled_css)
        templates = bundle.generate_xml_bundle()
        self.assertIn('baseer_dms_bill_link.PreviewWidget', templates)
        self.assertNotIn('throw new Error(', templates)

    def test_native_views_use_linked_document_preview_widget(self):
        for view_type in ('form', 'kanban'):
            arch = self.actor(self.env['dms.file']).get_view(view_type=view_type)['arch']
            document = etree.fromstring(arch.encode())
            self.assertTrue(document.xpath("//widget[@name='baseer_dms_bill_preview']"))
            self.assertTrue(document.xpath("//field[@name='bill_attachment_id']"))

    def test_single_reference_and_repeated_event(self):
        self.attachment_a._sync_dms_bill_links()
        self.attachment_a._sync_dms_bill_links()
        link = self.index(self.attachment_a)
        self.assertEqual(len(link), 1)
        self.assertEqual(link.company_id, self.company_a)
        self.assertFalse(link.attachment_id)
        self.assertEqual(self.actor(link).content, self.payload)
        self.assertFalse(self.env['ir.attachment'].search([
            ('res_model', '=', 'dms.file'), ('res_id', '=', link.id),
        ]), 'Bridge must not create a second content blob')
        self.assertEqual(self.attachment_a.res_id, self.bill_a.id)

    def test_original_updates_are_visible(self):
        updated = base64.b64encode(b'Synthetic corrected source bytes.')
        link = self.index(self.attachment_a)
        self.assertEqual(self.actor(link).content, self.payload)
        self.attachment_a.write({'datas': updated})
        self.assertEqual(self.actor(link).content, updated)
        self.attachment_a.write({'name': 'source-renamed.txt', 'datas': updated})
        self.assertEqual(self.actor(link).content, updated)
        self.assertEqual(self.attachment_a.name, 'source-renamed.txt')
        self.assertEqual(len(self.index(self.attachment_a)), 1)

    def test_staged_upload_gets_index_when_attached(self):
        staged = self.env['ir.attachment'].create({
            'name': 'staged.txt', 'datas': self.payload, 'res_model': 'account.move',
            'res_id': 0, 'company_id': self.company_a.id,
        })
        self.assertFalse(self.index(staged))
        staged.write({'res_id': self.bill_a.id})
        self.assertEqual(len(self.index(staged)), 1)

    def test_source_reference_does_not_apply_dms_upload_policy(self):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('dms.forbidden_extensions', 'txt')
        params.set_param('dms.binary_max_size', '0')
        source = self.env['ir.attachment'].create({
            'name': 'synthetic-policy.txt', 'datas': self.payload,
            'res_model': 'account.move', 'res_id': self.bill_a.id,
            'company_id': self.company_a.id,
        })
        link = self.index(source)
        self.assertEqual(len(link), 1)
        self.assertEqual(self.actor(link).content, self.payload)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['dms.file'].create({
                'name': 'ordinary-policy.txt', 'directory_id': self.root_a.id,
                'content': self.payload,
            })

    def test_source_reassociation_cleans_old_company_index(self):
        old = self.index(self.attachment_a)
        self.attachment_a.write({'res_id': self.bill_b.id, 'company_id': self.company_b.id})
        self.assertFalse(old.exists())
        fresh = self.index(self.attachment_a)
        self.assertEqual(len(fresh), 1)
        self.assertEqual(fresh.company_id, self.company_b)
        self.assertEqual(fresh.directory_id, self.root_b)
        self.attachment_a.write({'res_model': 'res.partner', 'res_id': self.env.user.partner_id.id})
        self.assertFalse(self.index(self.attachment_a))

    def test_dms_delete_preserves_original(self):
        self.actor(self.index(self.attachment_a)).unlink()
        self.assertTrue(self.attachment_a.exists())
        self.assertEqual(self.attachment_a.datas, self.payload)
        self.assertEqual(self.attachment_a.res_id, self.bill_a.id)

    def test_source_delete_removes_index(self):
        link = self.index(self.attachment_a)
        self.attachment_a.unlink()
        self.assertFalse(link.exists())

    def test_linked_mutations_and_copy_denied(self):
        link = self.actor(self.index(self.attachment_a))
        for values in ({'content': self.payload}, {'content_file': self.payload},
                       {'name': 'changed.txt'}, {'directory_id': self.root_b.id},
                       {'bill_attachment_id': self.attachment_b.id},
                       {'attachment_id': self.attachment_b.id}, {'access_token': 'share'}):
            with self.assertRaises(UserError), self.cr.savepoint():
                link.write(values)
        with self.assertRaises(UserError), self.cr.savepoint():
            link.copy()
        self.assertEqual(self.attachment_a.datas, self.payload)

    def test_create_cannot_forge_reference_or_use_destructive_native_link(self):
        values = {'name': 'ordinary.txt', 'directory_id': self.root_a.id,
                  'content': self.payload}
        ordinary = self.env['dms.file'].with_context(
            default_bill_attachment_id=self.attachment_a.id,
            default_bill_move_id=self.bill_a.id,
        ).create(values)
        self.assertFalse(ordinary.bill_attachment_id)
        self.assertFalse(ordinary.bill_move_id)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.env['dms.file'].create(dict(
                values, name='forged.txt', bill_attachment_id=self.attachment_a.id,
                bill_move_id=self.bill_a.id,
            ))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env['dms.file'].create({
                'name': 'native-link.txt', 'directory_id': self.root_a.id,
                'attachment_id': self.attachment_a.id,
            })

    def test_full_dms_group_cannot_override_source_acl_or_company(self):
        own, foreign = self.index(self.attachment_a), self.index(self.attachment_b)
        self.assertEqual(self.actor(own).content, self.payload)
        for record, user in ((own, self.nonaccount), (foreign, self.accountant)):
            model = self.actor(self.env['dms.file'], user)
            self.assertFalse(model.search([('id', '=', record.id)]))
            with self.assertRaises(AccessError):
                self.actor(record, user).read(['name', 'content'])

    def test_same_company_source_record_rule_denies_dms(self):
        self.env['ir.rule'].create({
            'name': 'Synthetic source denied',
            'model_id': self.env['ir.model']._get_id('account.move'),
            'domain_force': repr([('id', '!=', self.bill_a.id)]),
        })
        link = self.index(self.attachment_a)
        self.assertFalse(self.actor(self.env['dms.file']).search([('id', '=', link.id)]))
        with self.assertRaises(AccessError):
            self.actor(link).read(['name', 'content'])

    def test_original_attachment_rule_is_required_in_addition_to_move(self):
        self.actor(self.bill_a).check_access('read')
        self.env['ir.rule'].create({
            'name': 'Synthetic original attachment denied',
            'model_id': self.env['ir.model']._get_id('ir.attachment'),
            'domain_force': repr([('id', '!=', self.attachment_a.id)]),
        })
        link = self.index(self.attachment_a)
        self.assertFalse(self.actor(self.env['dms.file']).search([('id', '=', link.id)]))
        with self.assertRaises(AccessError):
            self.actor(link).read(['name', 'content'])

    def test_company_root_validation(self):
        company = self.env['res.company'].create({'name': 'Synthetic invalid root owner'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            company.dms_bill_root_id = self.root_b

    def test_configured_root_and_storage_association_are_frozen(self):
        for values in ({'parent_id': self.root_b.id},
                       {'storage_id': self.root_b.storage_id.id},
                       {'res_model': 'account.move'}, {'access_token': 'forbidden-token'}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.root_a.write(values)
        move_model = self.env['ir.model']._get('account.move')
        for values in ({'company_id': self.company_b.id}, {'save_type': 'file'},
                       {'model_ids': [(6, 0, move_model.ids)]},
                       {'inherit_access_from_parent_record': True}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.root_a.storage_id.write(values)
        unconfigured = self.env['dms.storage'].create({
            'name': 'Synthetic unconfigured storage', 'company_id': self.company_a.id,
            'save_type': 'database', 'model_ids': [(5, 0, 0)],
            'include_message_attachments': False, 'inherit_access_from_parent_record': False,
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            unconfigured.write({'model_ids': [(6, 0, move_model.ids)]})

    def test_bill_company_and_type_mutation_rejected(self):
        for values in ({'company_id': self.company_b.id}, {'move_type': 'in_refund'}):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.bill_a.write(values)
        self.assertEqual(self.bill_a.company_id, self.company_a)
        self.assertEqual(self.bill_a.move_type, 'in_invoice')

    def test_disabled_company_not_indexed(self):
        self.index(self.attachment_a).unlink()
        self.company_a.dms_bill_root_id = False
        attachment = self.env['ir.attachment'].create({
            'name': 'disabled.txt', 'datas': self.payload,
            'res_model': 'account.move', 'res_id': self.bill_a.id,
        })
        self.assertFalse(self.index(attachment))

    def test_refund_indexes_and_customer_or_url_documents_do_not(self):
        refund = self.env['account.move'].with_company(self.company_a).create({
            'move_type': 'in_refund', 'company_id': self.company_a.id,
            'journal_id': self.bill_a.journal_id.id,
        })
        refund_attachment = self.env['ir.attachment'].create({
            'name': 'refund.txt', 'datas': self.payload, 'res_model': 'account.move',
            'res_id': refund.id, 'company_id': self.company_a.id,
        })
        self.assertEqual(len(self.index(refund_attachment)), 1)
        sale_journal = self.env['account.journal'].with_company(self.company_a).create({
            'name': 'Synthetic sale', 'code': 'SSAL', 'type': 'sale',
            'company_id': self.company_a.id,
        })
        customer = self.env['account.move'].with_company(self.company_a).create({
            'move_type': 'out_invoice', 'company_id': self.company_a.id,
            'journal_id': sale_journal.id,
        })
        customer_attachment = self.env['ir.attachment'].create({
            'name': 'customer.txt', 'datas': self.payload,
            'res_model': 'account.move', 'res_id': customer.id,
        })
        url_attachment = self.env['ir.attachment'].create({
            'name': 'url-document', 'type': 'url', 'url': 'https://example.invalid/synthetic',
            'res_model': 'account.move', 'res_id': self.bill_a.id,
        })
        self.assertFalse(self.index(customer_attachment))
        self.assertFalse(self.index(url_attachment))


@tagged('post_install', '-at_install', 'baseer_dms_bill_link')
class TestBillDownload(BillFixtures, HttpCase):
    def test_owner_download_and_nonaccount_denial(self):
        link = self.index(self.attachment_a)
        path = f'/my/dms/file/{link.id}/download'
        self.owner.write({'password': 'bill-test', 'company_id': self.company_a.id})
        self.authenticate(self.owner.login, 'bill-test')
        self.assertEqual(self.url_open(path).content, base64.b64decode(self.payload))
        self.authenticate(self.nonaccount.login, 'bill-test')
        for suffix in ('', '?access_token=invalid'):
            response = self.url_open(path + suffix)
            self.assertNotIn(base64.b64decode(self.payload), response.content)
        direct = self.url_open(f'/web/content/dms.file/{link.id}/content?download=true')
        self.assertNotIn(base64.b64decode(self.payload), direct.content)

    def test_public_ancestor_token_cannot_download_original(self):
        link = self.index(self.attachment_a)
        with self.assertRaises(UserError), self.cr.savepoint():
            self.root_a.write({'access_token': 'synthetic-ancestor-token'})
        # Adversarial preexisting token: bypass only the token write guard in
        # this rollback-only synthetic fixture to prove the read guard itself.
        self.cr.execute('UPDATE dms_directory SET access_token = %s WHERE id = %s',
                        ['synthetic-ancestor-token', self.root_a.id])
        self.root_a.invalidate_recordset(['access_token'])
        self.assertFalse(link.check_access_token('synthetic-ancestor-token'))
        response = self.url_open(
            f'/my/dms/file/{link.id}/download?access_token=synthetic-ancestor-token'
        )
        self.assertNotIn(base64.b64decode(self.payload), response.content)
        self.assertNotIn('attachment;', response.headers.get('Content-Disposition', ''))


@tagged('post_install', '-at_install', 'baseer_dms_bill_link')
class TestBillPreview(BillFixtures, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.preview_sources = cls.env['ir.attachment']
        for image_format in ('PNG', 'JPEG'):
            buffer = BytesIO()
            Image.new('RGB', (256, 192), (23, 147, 211)).save(buffer, format=image_format)
            cls.preview_sources |= cls.env['ir.attachment'].create({
                'name': 'synthetic-preview.' + ('png' if image_format == 'PNG' else 'jpg'),
                'datas': base64.b64encode(buffer.getvalue()), 'res_model': 'account.move',
                'res_id': cls.bill_a.id, 'company_id': cls.company_a.id,
            })
        cls.png_source, cls.jpg_source = cls.preview_sources
        # Minimal synthetic one-page PDF; no library, real invoice or extraction.
        objects = [
            b'<< /Type /Catalog /Pages 2 0 R >>',
            b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
            b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] /Contents 4 0 R >>',
            b'<< /Length 0 >>\nstream\n\nendstream',
        ]
        pdf = b'%PDF-1.4\n'
        offsets = [0]
        for number, body in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf += str(number).encode() + b' 0 obj\n' + body + b'\nendobj\n'
        xref = len(pdf)
        pdf += b'xref\n0 5\n0000000000 65535 f \n'
        pdf += b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets[1:])
        pdf += f'trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
        cls.pdf_source = cls.env['ir.attachment'].create({
            'name': 'synthetic-preview.pdf', 'datas': base64.b64encode(pdf),
            'res_model': 'account.move', 'res_id': cls.bill_a.id,
            'company_id': cls.company_a.id, 'mimetype': 'application/pdf',
        })
        cls.foreign_source = cls.env['ir.attachment'].create({
            'name': 'foreign-preview.png', 'datas': cls.png_source.datas,
            'res_model': 'account.move', 'res_id': cls.bill_b.id,
            'company_id': cls.company_b.id,
        })

    def preview_paths(self, source):
        link = self.index(source)
        return (
            f'/web/image/dms.file/{link.id}/content/128x128',
            f'/web/content?model=dms.file&id={link.id}&field=content&filename_field=name&download=false',
        )

    def assert_preview_denied(self, source):
        thumbnail, content = self.preview_paths(source)
        image_response = self.url_open(thumbnail)
        self.assertNotEqual(image_response.content, base64.b64decode(source.datas))
        if image_response.headers.get('Content-Type', '').startswith('image/'):
            # /web/image may serve a public placeholder after denial. Prove the
            # synthetic source's identifying pixels do not occur in that image.
            image = Image.open(BytesIO(image_response.content)).convert('RGB')
            pixel = image.getpixel((image.width // 2, image.height // 2))
            self.assertGreater(sum(abs(a - b) for a, b in zip(pixel, (23, 147, 211))), 12)
        response = self.url_open(content)
        self.assertNotEqual(response.content, base64.b64decode(source.datas))
        self.assertNotIn(base64.b64decode(source.datas), response.content)

    def test_owner_raster_thumbnail_and_inline_original_pdf_without_derivatives(self):
        self.owner.write({'password': 'bill-test', 'company_id': self.company_a.id})
        self.authenticate(self.owner.login, 'bill-test')
        for source in self.preview_sources:
            thumbnail, content = self.preview_paths(source)
            response = self.url_open(thumbnail)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.headers.get('Content-Type', '').startswith('image/'))
            image = Image.open(BytesIO(response.content))
            self.assertLessEqual(max(image.size), 128)
            pixel = image.convert('RGB').getpixel((image.width // 2, image.height // 2))
            self.assertLessEqual(sum(abs(a - b) for a, b in zip(pixel, (23, 147, 211))), 12)
            self.assertEqual(self.url_open(content).content, base64.b64decode(source.datas))
        response = self.url_open(self.preview_paths(self.pdf_source)[1])
        self.assertEqual(response.content, base64.b64decode(self.pdf_source.datas))
        self.assertTrue(response.headers.get('Content-Type', '').startswith('application/pdf'))
        self.assertNotIn('attachment;', response.headers.get('Content-Disposition', ''))
        all_sources = self.preview_sources | self.pdf_source
        links = self.env['dms.file'].search([('bill_attachment_id', 'in', all_sources.ids)])
        self.assertEqual(len(links), len(all_sources))
        self.assertFalse(self.env['ir.attachment'].search([
            ('res_model', '=', 'dms.file'), ('res_id', 'in', links.ids),
        ]))
        self.assertFalse(any(links.mapped('image_1920')))
        self.assertFalse(any(links.mapped('content_file')))

    def test_anonymous_and_nonaccount_cannot_preview_original(self):
        self.assert_preview_denied(self.png_source)
        self.authenticate(self.nonaccount.login, 'bill-test')
        self.assert_preview_denied(self.png_source)
        response = self.url_open(self.preview_paths(self.pdf_source)[1])
        self.assertNotEqual(response.content, base64.b64decode(self.pdf_source.datas))

    def test_other_company_cannot_preview_original(self):
        self.authenticate(self.accountant.login, 'bill-test')
        self.assert_preview_denied(self.foreign_source)

    def test_source_rules_deny_preview_even_with_full_dms_access(self):
        self.authenticate(self.accountant.login, 'bill-test')
        for model, source_id in (('account.move', self.bill_a.id),
                                 ('ir.attachment', self.png_source.id)):
            rule = self.env['ir.rule'].create({
                'name': 'Preview original denied: ' + model,
                'model_id': self.env['ir.model']._get_id(model),
                'domain_force': repr([('id', '!=', source_id)]),
            })
            self.assert_preview_denied(self.png_source)
            rule.unlink()
