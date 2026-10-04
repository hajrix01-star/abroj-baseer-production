from copy import deepcopy

from lxml import etree

from odoo.tests.common import Form, TransactionCase, tagged


@tagged('post_install', '-at_install')
class CompanyDisplayLanguageCase(TransactionCase):
    """Company labels localize independently from the stored legal identity."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].with_context(no_vat_validation=True).create({
            'baseer_name_ar': 'شركة اختبار الاسم',
            'baseer_name_en': 'Company label fixture',
            'vat': '310000000000003',
            'company_registry': '1010999999',
        })
        cls.ancestor = cls.env['res.company'].create({
            'baseer_name_ar': 'الشركة الأم للاختبار',
            'baseer_name_en': 'Ancestor label fixture',
        })
        cls.unlisted = cls.env['res.company'].create({'name': 'Unlisted label fixture'})

    def _identity(self, company):
        return {
            'company': company.read([
                'name', 'baseer_name_ar', 'baseer_name_en', 'vat', 'company_registry'])[0],
            'partner': company.partner_id.read([
                'name', 'baseer_name_ar', 'baseer_name_en', 'vat'])[0],
        }

    def test_alternating_language_cache_fallbacks_preserve_native_identity_and_identifiers(self):
        before = self._identity(self.company)
        self.assertEqual(self.company.name, 'شركة اختبار الاسم | Company label fixture')
        arabic = self.company.with_context(lang='ar_001')
        english = self.company.with_context(lang='en_US')
        for record, expected in (
                (arabic, 'شركة اختبار الاسم'), (english, 'Company label fixture'),
                (arabic, 'شركة اختبار الاسم'), (english, 'Company label fixture')):
            self.assertEqual(record.baseer_display_name, expected)
            self.assertEqual(record.read(['baseer_display_name'])[0]['baseer_display_name'], expected)
            self.assertEqual(record.display_name, before['company']['name'])
            self.assertEqual(record.display_name, record.partner_id.name)
            self.assertEqual(record.read(['display_name'])[0]['display_name'], record.name)
        self.assertEqual(self._identity(self.company), before)
        self.assertEqual(self.company.export_data(['name'])['datas'], [[before['company']['name']]])
        arabic_only = self.env['res.company'].create({'baseer_name_ar': 'اسم عربي فقط'})
        english_only = self.env['res.company'].create({'baseer_name_en': 'English only'})
        # A virtual legacy record models the supported absence of both optional
        # partner components without editing persisted identity through SQL.
        legacy = self.env['res.company'].new({'name': 'Legacy canonical company'})
        for lang in ('ar_001', 'en_US'):
            self.assertEqual(arabic_only.with_context(lang=lang).baseer_display_name, 'اسم عربي فقط')
            self.assertEqual(english_only.with_context(lang=lang).baseer_display_name, 'English only')
            self.assertEqual(legacy.with_context(lang=lang).baseer_display_name, 'Legacy canonical company')

    def test_name_component_and_native_rename_invalidate_both_cached_labels(self):
        arabic = self.company.with_context(lang='ar_001')
        english = self.company.with_context(lang='en_US')
        self.assertEqual(arabic.baseer_display_name, 'شركة اختبار الاسم')
        self.assertEqual(english.baseer_display_name, 'Company label fixture')
        self.company.write({'baseer_name_en': 'Updated English label'})
        self.assertEqual(english.baseer_display_name, 'Updated English label')
        self.assertEqual(arabic.baseer_display_name, 'شركة اختبار الاسم')
        self.company.write({'baseer_name_ar': 'الاسم العربي المعدل'})
        self.assertEqual(arabic.baseer_display_name, 'الاسم العربي المعدل')
        self.assertEqual(english.baseer_display_name, 'Updated English label')
        self.assertEqual(arabic.display_name, self.company.name)
        self.assertEqual(english.display_name, self.company.name)
        self.company.write({'name': 'Native API rename'})
        self.assertEqual(self.company.name, 'Native API rename')
        self.assertEqual(arabic.baseer_display_name, 'Native API rename')
        self.assertEqual(english.baseer_display_name, 'Native API rename')
        self.assertEqual(arabic.display_name, 'Native API rename')
        self.assertEqual(english.display_name, 'Native API rename')

    def _session_payload(self):
        return {
            'bundle_params': {'lang': 'en_US', 'debug': False},
            'user_context': {'lang': 'ar_001', 'tz': 'Asia/Riyadh'},
            'uid': self.env.uid,
            'currencies': {1: {'symbol': 'SR', 'digits': [69, 2]}},
            'user_companies': {
                'current_company': self.company.id,
                'allowed_companies': {
                    self.company.id: {'id': self.company.id, 'name': self.company.name,
                                      'sequence': 4, 'currency_id': self.company.currency_id.id,
                                      'child_ids': []},
                },
                'disallowed_ancestor_companies': {
                    self.ancestor.id: {'id': self.ancestor.id, 'name': self.ancestor.name,
                                       'sequence': 2, 'parent_id': False},
                },
            },
        }

    def test_session_names_use_bundle_language_and_preserve_all_other_payload_values(self):
        payload = self._session_payload()
        expected = deepcopy(payload)
        expected['user_companies']['allowed_companies'][self.company.id]['name'] = 'Company label fixture'
        expected['user_companies']['disallowed_ancestor_companies'][self.ancestor.id]['name'] = 'Ancestor label fixture'
        before = self._identity(self.company)
        result = self.env['ir.http'].with_context(lang='ar_001')._baseer_localize_company_session_names(payload)
        self.assertIs(result, payload)
        self.assertEqual(result, expected)
        self.assertNotIn(self.unlisted.id, result['user_companies']['allowed_companies'])
        self.assertNotIn(self.unlisted.id, result['user_companies']['disallowed_ancestor_companies'])
        self.assertEqual(self._identity(self.company), before)

    def test_session_language_falls_back_to_user_context_then_environment_and_empty_is_safe(self):
        Http = self.env['ir.http'].with_context(lang='ar_001')
        payload = self._session_payload()
        payload['bundle_params'] = {}
        payload['user_context']['lang'] = 'en_US'
        result = Http._baseer_localize_company_session_names(payload)
        self.assertEqual(result['user_companies']['allowed_companies'][self.company.id]['name'], 'Company label fixture')
        payload = self._session_payload()
        payload.pop('bundle_params')
        payload.pop('user_context')
        result = Http._baseer_localize_company_session_names(payload)
        self.assertEqual(result['user_companies']['allowed_companies'][self.company.id]['name'], 'شركة اختبار الاسم')
        for payload in ({}, {'uid': self.env.uid}, {'user_companies': {}},
                        {'user_companies': {'allowed_companies': {}, 'current_company': False}}):
            expected = deepcopy(payload)
            self.assertIs(Http._baseer_localize_company_session_names(payload), payload)
            self.assertEqual(payload, expected)

    def test_native_company_views_use_localized_label_and_bilingual_form_still_creates_and_edits(self):
        Company = self.env['res.company'].with_context(lang='en_US')
        arch = etree.fromstring(Company.get_view(
            view_id=self.env.ref('base.view_company_form').id, view_type='form')['arch'].encode())
        self.assertTrue(arch.xpath('//h1/field[@name="baseer_display_name"]'))
        self.assertTrue(arch.xpath('//h1/field[@name="name" and @invisible="1"]'))
        self.assertTrue(arch.xpath('//field[@name="baseer_name_ar"]'))
        self.assertTrue(arch.xpath('//field[@name="baseer_name_en"]'))
        for xmlid, kind in (('base.view_company_tree', 'list'), ('base.view_res_company_kanban', 'kanban')):
            arch = etree.fromstring(Company.get_view(
                view_id=self.env.ref(xmlid).id, view_type=kind)['arch'].encode())
            self.assertTrue(arch.xpath('//field[@name="baseer_display_name"]'))
            self.assertFalse(arch.xpath('//field[@name="name"]'))
        form = Form(Company, view='base.view_company_form')
        form.baseer_name_ar = 'شركة من النموذج'
        form.baseer_name_en = 'Created through form'
        created = form.save()
        self.assertEqual(created.name, 'شركة من النموذج | Created through form')
        self.assertEqual(created.baseer_display_name, 'Created through form')
        self.assertEqual(created.display_name, created.name)
        form = Form(created, view='base.view_company_form')
        form.baseer_name_en = 'Edited through form'
        form.save()
        self.assertEqual(created.name, 'شركة من النموذج | Edited through form')
        self.assertEqual(created.baseer_display_name, 'Edited through form')
        self.assertEqual(created.display_name, created.name)

    def test_supplier_display_name_and_native_renames_keep_existing_partner_behavior(self):
        supplier = self.env['res.partner'].create({
            'is_company': True, 'supplier_rank': 1,
            'baseer_name_ar': 'مورد اختبار الاسم', 'baseer_name_en': 'Supplier label fixture',
        })
        canonical = 'مورد اختبار الاسم | Supplier label fixture'
        for lang in ('ar_001', 'en_US'):
            self.assertEqual(supplier.with_context(lang=lang).display_name, canonical)
        self.assertEqual(supplier.name, canonical)
        supplier.write({'name': 'Native supplier rename'})
        self.assertEqual(supplier.baseer_name_en, 'Native supplier rename')
        self.assertFalse(supplier.baseer_name_ar)
        for lang in ('ar_001', 'en_US'):
            self.assertEqual(supplier.with_context(lang=lang).display_name, 'Native supplier rename')
