import base64
from io import BytesIO

from PIL import Image

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.baseer_dms_bill_link.tests.test_bill_link import BillFixtures


class DepartmentFixtures(BillFixtures):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner.group_ids |= (
            cls.env.ref('hr.group_hr_manager') | cls.env.ref('purchase.group_purchase_manager')
            | cls.env.ref('dms.group_dms_manager')
        )
        cls.hr_user = new_test_user(
            cls.env, login='department-hr', password='department-test',
            groups='dms.group_dms_manager,hr.group_hr_manager,purchase.group_purchase_manager',
            company_id=cls.company_a.id, company_ids=[(6, 0, cls.company_a.ids)],
        )
        cls.access_group.explicit_user_ids |= cls.hr_user
        cls.old_bill_link = cls.env['dms.file'].search([
            ('bill_attachment_id', '=', cls.attachment_a.id),
        ])
        cls.old_bill_id = cls.old_bill_link.id
        cls.old_bill_checksum = cls.attachment_a.checksum
        cls.old_bill_storage = cls.old_bill_link.storage_id
        for company in (cls.company_a, cls.company_b):
            company._setup_dms_departments(access_group=cls.access_group)
        cls.employees = cls.env['hr.employee']
        cls.orders = cls.env['purchase.order']
        vendor = cls.env['res.partner'].create({'name': 'Synthetic department supplier'})
        for company in (cls.company_a, cls.company_b):
            cls.employees |= cls.env['hr.employee'].with_company(company).create({
                'name': 'Private synthetic employee ' + company.name, 'company_id': company.id,
            })
            cls.orders |= cls.env['purchase.order'].with_company(company).create({
                'partner_id': vendor.id, 'company_id': company.id,
                'currency_id': company.currency_id.id,
            })
        cls.employee_a, cls.employee_b = cls.employees
        cls.order_a, cls.order_b = cls.orders
        cls.version_a = cls.employee_a.current_version_id
        cls.version_a.write({'contract_date_start': '2026-01-01'})
        cls.employee_dirs = {}
        for employee in cls.employees:
            cls.employee_dirs[employee.id] = employee.company_id._ensure_dms_employee_directories(employee)
        cls.sources = cls.env['ir.attachment']
        for record in (cls.employee_a, cls.version_a, cls.order_a, cls.employee_b, cls.order_b):
            cls.sources |= cls.env['ir.attachment'].create({
                'name': 'synthetic-' + record._name + '.txt', 'datas': cls.payload,
                'res_model': record._name, 'res_id': record.id,
                'company_id': record.company_id.id,
            })
        (cls.employee_source, cls.version_source, cls.order_source,
         cls.foreign_employee_source, cls.foreign_order_source) = cls.sources

    def private_directories(self, employee=None):
        return self.env['dms.directory'].search([
            ('managed_employee_id', '=', (employee or self.employee_a).id),
        ])

    def assert_hidden(self, record, user=None):
        user = user or self.hr_user
        model = self.actor(self.env[record._name], user)
        domain = [('id', 'in', record.ids)]
        self.assertFalse(model.search(domain))
        self.assertEqual(model.search_count(domain), 0)
        self.assertFalse(model.name_search('', domain))
        with self.assertRaises(AccessError):
            self.actor(record, user).read(['name'])


@tagged('post_install', '-at_install', 'baseer_dms_departments')
class TestDepartments(DepartmentFixtures, TransactionCase):
    def test_setup_and_attachment_retry_keep_unique_hierarchy_and_original(self):
        before = self.env['dms.directory'].search([('managed_key', '!=', False)])
        for company in (self.company_a, self.company_b):
            company._setup_dms_departments(access_group=self.access_group)
        self.company_a._ensure_dms_employee_directories(self.employee_a)
        after = self.env['dms.directory'].search([('managed_key', '!=', False)])
        self.assertEqual(before, after)
        self.assertEqual(len(after.mapped('managed_key')), len(set(after.mapped('managed_key'))))
        for source in self.sources:
            source._sync_dms_bill_links()
            source._sync_dms_bill_links()
            link = self.index(source)
            self.assertEqual(len(link), 1)
            self.assertFalse(link.attachment_id)
            self.assertEqual(link.company_id, source.company_id)
            self.assertFalse(link.content_file)
            self.assertFalse(link.image_1920)
            self.assertFalse(self.env['ir.attachment'].search([
                ('res_model', '=', 'dms.file'), ('res_id', '=', link.id),
            ]))

    def test_department_ancestry_and_bill_rehome_preserve_ids_and_source(self):
        company = self.company_a
        self.assertEqual(company.dms_purchase_root_id.parent_id, company.dms_company_root_id)
        self.assertEqual(company.dms_bill_root_id.parent_id, company.dms_purchase_root_id)
        self.assertEqual(company.dms_purchase_order_root_id.parent_id, company.dms_purchase_root_id)
        self.assertEqual(company.dms_hr_root_id.parent_id, company.dms_company_root_id)
        self.assertEqual(company.dms_employee_root_id.parent_id, company.dms_hr_root_id)
        self.assertEqual(self.index(self.attachment_a).id, self.old_bill_id)
        self.assertEqual(self.index(self.attachment_a).storage_id, self.old_bill_storage)
        self.assertEqual(self.attachment_a.checksum, self.old_bill_checksum)
        self.assertEqual(self.attachment_a.datas, self.payload)
        self.assertEqual(self.attachment_a.res_id, self.bill_a.id)
        self.assertEqual(self.index(self.order_source).directory_id, company.dms_purchase_order_root_id)
        self.assertEqual(self.index(self.employee_source).directory_id,
                         self.employee_dirs[self.employee_a.id]['documents'])
        self.assertEqual(self.index(self.version_source).directory_id,
                         self.employee_dirs[self.employee_a.id]['contracts'])

    def test_failed_native_bill_attachment_write_restores_same_index(self):
        original_index_id = self.index(self.attachment_a).id
        with self.assertRaises(ValueError), self.cr.savepoint():
            self.attachment_a.write({'type': 'invalid-selection'})
        self.assertEqual(self.attachment_a.type, 'binary')
        self.assertEqual(self.index(self.attachment_a).id, original_index_id)

    def test_noop_bill_attachment_association_write_keeps_index_id(self):
        original_index_id = self.index(self.attachment_a).id
        self.attachment_a.write({
            'res_model': 'account.move', 'res_id': self.bill_a.id,
            'type': 'binary', 'res_field': False,
        })
        self.assertEqual(self.index(self.attachment_a).id, original_index_id)
        self.assertEqual(self.attachment_a.type, 'binary')

    def test_private_hr_metadata_denied_to_public_employee_reader_and_dms_manager(self):
        # Public employee directory access must not confer private HR access.
        self.actor(self.env['hr.employee.public'], self.nonaccount).search([
            ('id', '=', self.employee_a.id),
        ])
        for user in (self.nonaccount, self.accountant):
            for directory in self.private_directories() | self.company_a.dms_hr_root_id:
                self.assert_hidden(directory, user)
        for source in (self.employee_source, self.version_source):
            self.assert_hidden(self.index(source), self.nonaccount)

    def test_hr_and_purchase_company_scope_cannot_be_overridden_by_full_dms_group(self):
        self.assertEqual(self.actor(self.index(self.employee_source), self.hr_user).content, self.payload)
        self.assertEqual(self.actor(self.index(self.version_source), self.hr_user).content, self.payload)
        self.assertEqual(self.actor(self.index(self.order_source), self.hr_user).content, self.payload)
        for source in (self.foreign_employee_source, self.foreign_order_source):
            self.assert_hidden(self.index(source))
        for directory in self.private_directories(self.employee_b):
            self.assert_hidden(directory)
        self.assert_hidden(self.index(self.order_source), self.nonaccount)

    def test_employee_rule_constrains_directory_metadata_and_files(self):
        self.env['ir.rule'].create({
            'name': 'Synthetic private employee denied',
            'model_id': self.env['ir.model']._get_id('hr.employee'),
            'domain_force': repr([('id', '!=', self.employee_a.id)]),
        })
        for directory in self.private_directories():
            self.assert_hidden(directory)
        self.assert_hidden(self.index(self.employee_source))
        self.assert_hidden(self.index(self.version_source))

    def test_source_and_original_attachment_rules_both_constrain_files(self):
        for model, source, source_id in (
            ('purchase.order', self.order_source, self.order_a.id),
            ('hr.version', self.version_source, self.version_a.id),
            ('ir.attachment', self.employee_source, self.employee_source.id),
        ):
            rule = self.env['ir.rule'].create({
                'name': 'Synthetic original denied ' + model,
                'model_id': self.env['ir.model']._get_id(model),
                'domain_force': repr([('id', '!=', source_id)]),
            })
            self.assert_hidden(self.index(source))
            with self.assertRaises(AccessError):
                self.actor(self.index(source), self.hr_user).read(['content'])
            rule.unlink()

    def test_original_updates_visible_and_index_deletion_preserves_original(self):
        for source in (self.employee_source, self.version_source, self.order_source):
            link = self.index(source)
            self.assertEqual(self.actor(link, self.hr_user).content, self.payload)
            replacement = base64.b64encode(b'Synthetic updated department original.')
            source.write({'name': 'updated-source.txt', 'datas': replacement})
            self.assertEqual(self.actor(link, self.hr_user).content, replacement)
            self.assertEqual(source.name, 'updated-source.txt')
            self.assertEqual(len(self.index(source)), 1)
            self.actor(link, self.hr_user).unlink()
            self.assertTrue(source.exists())
            self.assertEqual(source.datas, replacement)

    def test_original_unlink_cascades_only_reference(self):
        for source in (self.employee_source, self.version_source, self.order_source):
            link = self.index(source)
            source.unlink()
            self.assertFalse(link.exists())

    def test_purchase_order_unlink_removes_reference(self):
        link = self.index(self.order_source)
        self.order_a.button_cancel()
        self.order_a.unlink()
        self.assertFalse(link.exists())

    def test_new_department_folder_labels_are_arabic_in_arabic_context(self):
        self.env['res.lang'].with_user(self.owner)._activate_lang('ar_001')
        self.env['ir.module.module']._load_module_terms(
            ['baseer_dms_departments'], ['ar_001'], overwrite=True,
        )
        company = self.env['res.company'].create({'name': 'شركة اختبار الأقسام'})
        self.owner.company_ids |= company
        company = company.with_context(lang='ar_001', allowed_company_ids=company.ids)
        self.assertEqual(company.env._('Purchases'), 'المشتريات')
        self.assertEqual(company.env._('Human Resources'), 'الموارد البشرية')
        folders = company._setup_dms_departments(access_group=self.access_group)[company.id]
        expected = {
            'purchases': 'المشتريات', 'bills': 'فواتير الموردين',
            'purchase_orders': 'أوامر الشراء', 'hr': 'الموارد البشرية',
            'employees': 'الموظفون', 'sales': 'المبيعات', 'administration': 'الإدارة',
        }
        directory = self.env['dms.directory'].with_context(
            lang='ar_001', allowed_company_ids=company.ids,
        )
        for key, label in expected.items():
            self.assertEqual(directory.browse(folders[key]).name, label)

    def test_new_source_reassociation_and_company_changes_rejected(self):
        for source, values in (
            (self.employee_source, {'res_id': self.employee_b.id}),
            (self.version_source, {'res_model': 'hr.employee', 'res_id': self.employee_a.id}),
            (self.order_source, {'res_id': self.order_b.id}),
            (self.employee_source, {'company_id': self.company_b.id}),
        ):
            with self.assertRaises(UserError), self.cr.savepoint():
                source.write(values)
        for record, values in (
            (self.employee_a, {'company_id': self.company_b.id}),
            (self.order_a, {'company_id': self.company_b.id}),
            (self.version_a, {'employee_id': self.employee_b.id}),
            (self.version_a, {'company_id': self.company_b.id}),
        ):
            with self.assertRaises(UserError), self.cr.savepoint():
                record.write(values)

    def test_native_links_moves_copy_migration_and_tokens_denied(self):
        for source in (self.employee_source, self.version_source, self.order_source):
            link = self.index(source)
            for values in ({'directory_id': self.company_b.dms_bill_root_id.id},
                           {'access_token': 'forbidden'}, {'content': self.payload}):
                with self.assertRaises(UserError), self.cr.savepoint():
                    link.write(values)
            with self.assertRaises(UserError), self.cr.savepoint():
                link.copy()
            with self.assertRaises(UserError), self.cr.savepoint():
                link.action_migrate()
            with self.assertRaises(ValidationError), self.cr.savepoint():
                self.env['dms.file'].create({
                    'name': 'native-' + str(source.id), 'directory_id': link.directory_id.id,
                    'attachment_id': source.id,
                })
        for root in (self.company_a.dms_company_root_id, self.company_a.dms_hr_root_id,
                     self.company_a.dms_purchase_root_id):
            with self.assertRaises(UserError), self.cr.savepoint():
                root.write({'access_token': 'forbidden'})
            with self.assertRaises(UserError), self.cr.savepoint():
                root.write({'parent_id': self.company_b.dms_company_root_id.id})

    def test_new_source_provenance_cannot_be_injected_by_context_or_create(self):
        values = {'name': 'ordinary-department.txt',
                  'directory_id': self.company_a.dms_bill_root_id.id, 'content': self.payload}
        defaults = {
            'default_source_purchase_order_id': self.order_a.id,
            'default_source_employee_id': self.employee_a.id,
            'default_source_version_id': self.version_a.id,
            'default_bill_attachment_id': self.employee_source.id,
        }
        ordinary = self.env['dms.file'].with_context(**defaults).create(values)
        for field in ('source_purchase_order_id', 'source_employee_id', 'source_version_id',
                      'bill_attachment_id'):
            self.assertFalse(ordinary[field])
        for field, source in (('source_purchase_order_id', self.order_a),
                              ('source_employee_id', self.employee_a),
                              ('source_version_id', self.version_a)):
            with self.assertRaises(UserError), self.cr.savepoint():
                self.env['dms.file'].create(dict(values, **{field: source.id}))

    def test_unassigned_version_url_and_internal_employee_image_not_indexed(self):
        template = self.env['hr.version'].with_company(self.company_a).create({
            'name': 'Synthetic unassigned contract template',
            'company_id': self.company_a.id, 'date_version': '2020-01-01',
        })
        excluded = self.env['ir.attachment'].create([
            {'name': 'unassigned.txt', 'datas': self.payload, 'res_model': 'hr.version',
             'res_id': template.id, 'company_id': self.company_a.id},
            {'name': 'internal-image.txt', 'datas': self.payload, 'res_model': 'hr.employee',
             'res_id': self.employee_a.id, 'res_field': 'image_1920',
             'company_id': self.company_a.id},
            {'name': 'external-url', 'type': 'url', 'url': 'https://example.invalid/synthetic',
             'res_model': 'purchase.order', 'res_id': self.order_a.id,
             'company_id': self.company_a.id},
        ])
        for source in excluded:
            self.assertFalse(self.index(source))


@tagged('post_install', '-at_install', 'baseer_dms_departments')
class TestDepartmentPreview(DepartmentFixtures, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        buffer = BytesIO()
        Image.new('RGB', (192, 192), (23, 147, 211)).save(buffer, format='PNG')
        cls.image_payload = base64.b64encode(buffer.getvalue())
        cls.image_sources = cls.env['ir.attachment'].create([
            {'name': 'synthetic-private.png', 'datas': cls.image_payload,
             'res_model': record._name, 'res_id': record.id, 'company_id': record.company_id.id}
            for record in (cls.employee_a, cls.order_a, cls.employee_b)
        ])
        cls.hr_image, cls.po_image, cls.foreign_image = cls.image_sources

    def paths(self, source):
        link = self.index(source)
        return (f'/web/image/dms.file/{link.id}/content/128x128',
                f'/web/content/dms.file/{link.id}/content?download=false',
                f'/my/dms/file/{link.id}/download')

    def assert_denied(self, source):
        for path in self.paths(source):
            response = self.url_open(path)
            self.assertNotEqual(response.content, base64.b64decode(source.datas))
            if path.startswith('/web/image') and response.headers.get('Content-Type', '').startswith('image/'):
                image = Image.open(BytesIO(response.content)).convert('RGB')
                pixel = image.getpixel((image.width // 2, image.height // 2))
                self.assertGreater(sum(abs(a - b) for a, b in zip(pixel, (23, 147, 211))), 12)

    def test_owner_hr_and_purchase_preview_allowed_without_blob_copy(self):
        self.owner.write({'password': 'department-test', 'company_id': self.company_a.id})
        self.authenticate(self.owner.login, 'department-test')
        for source in (self.hr_image, self.po_image):
            image_path, content_path, download_path = self.paths(source)
            response = self.url_open(image_path)
            self.assertEqual(response.status_code, 200)
            image = Image.open(BytesIO(response.content)).convert('RGB')
            self.assertEqual(image.getpixel((image.width // 2, image.height // 2)), (23, 147, 211))
            for path in (content_path, download_path):
                self.assertEqual(self.url_open(path).content, base64.b64decode(source.datas))
            self.assertFalse(self.env['ir.attachment'].search([
                ('res_model', '=', 'dms.file'), ('res_id', '=', self.index(source).id),
            ]))

    def test_private_preview_anonymous_role_company_source_rule_and_token_denial(self):
        self.assert_denied(self.hr_image)
        self.authenticate(self.nonaccount.login, 'bill-test')
        self.assert_denied(self.hr_image)
        self.assert_denied(self.po_image)
        self.authenticate(self.hr_user.login, 'department-test')
        self.assert_denied(self.foreign_image)
        rule = self.env['ir.rule'].create({
            'name': 'Synthetic HTTP source employee denied',
            'model_id': self.env['ir.model']._get_id('hr.employee'),
            'domain_force': repr([('id', '!=', self.employee_a.id)]),
        })
        self.assert_denied(self.hr_image)
        rule.unlink()
        self.cr.execute('UPDATE dms_directory SET access_token = %s WHERE id = %s',
                        ['unsafe-ancestor', self.company_a.dms_company_root_id.id])
        self.company_a.dms_company_root_id.invalidate_recordset(['access_token'])
        self.authenticate(self.nonaccount.login, 'bill-test')
        path = self.paths(self.hr_image)[2] + '?access_token=unsafe-ancestor'
        self.assertNotEqual(self.url_open(path).content, base64.b64decode(self.image_payload))
