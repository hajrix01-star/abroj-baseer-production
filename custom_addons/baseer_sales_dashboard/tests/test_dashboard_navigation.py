import hashlib

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.baseer_sales_dashboard.models.dashboard_navigation import OPERATIONS_DASHBOARDS


@tagged('post_install', '-at_install')
class TestDashboardNavigation(TransactionCase):
    def _binary_digest(self, dashboard):
        content = dashboard.with_context(bin_size=False).spreadsheet_binary_data or b''
        if isinstance(content, str):
            content = content.encode()
        return hashlib.sha256(content).hexdigest()

    def test_operation_dashboards_are_reorganized_without_sheet_writes(self):
        Dashboard = self.env['spreadsheet.dashboard']
        operations = self.env.ref('baseer_sales_dashboard.dashboard_group_sales_operations')
        sales = self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_group_sales')
        arabic_languages = self.env['res.lang'].search([
            ('code', 'in', ('ar', 'ar_001')),
        ])
        install_language = arabic_languages[:1].code if arabic_languages else 'en_US'
        operations_count = self.env['spreadsheet.dashboard.group'].search_count([
            ('name', '=', 'Sales operations'),
        ])
        before = {}
        found = []
        expected = []
        for xmlid, name, arabic_name, sequence in OPERATIONS_DASHBOARDS:
            module_name, _record_name = xmlid.split('.', 1)
            dashboard = self.env.ref(xmlid, raise_if_not_found=False)
            module = self.env['ir.module.module'].search([
                ('name', '=', module_name), ('state', '=', 'installed'),
            ], limit=1)
            if module:
                self.assertTrue(dashboard, 'Installed module must provide %s' % xmlid)
            if not dashboard:
                continue
            found.append(dashboard)
            expected.append((name, arabic_name, sequence))
            before[dashboard.id] = {
                'sample_dashboard_file_path': dashboard.sample_dashboard_file_path,
                'spreadsheet_binary_digest': self._binary_digest(dashboard),
                'is_published': dashboard.is_published,
                'group_ids': dashboard.group_ids.ids,
                'company_ids': dashboard.company_ids.ids,
                'favorite_user_ids': dashboard.favorite_user_ids.ids,
            }
            dashboard.write({'name': 'Previous name', 'dashboard_group_id': sales.id, 'sequence': 99})

        self.assertTrue(found, 'At least one installed operational dashboard is required')
        Dashboard.with_context(lang=install_language)._baseer_reorganize_dashboard_navigation()
        Dashboard.with_context(lang=install_language)._baseer_reorganize_dashboard_navigation()

        self.assertEqual(
            self.env['spreadsheet.dashboard.group'].search_count([('name', '=', 'Sales operations')]),
            operations_count,
        )
        for dashboard, (name, arabic_name, sequence) in zip(found, expected):
            self.assertEqual(dashboard.name, name)
            for language in arabic_languages:
                self.assertEqual(dashboard.with_context(lang=language.code).name, arabic_name)
            self.assertEqual(dashboard.dashboard_group_id, operations)
            self.assertEqual(dashboard.sequence, sequence)
            self.assertEqual(
                dashboard.sample_dashboard_file_path,
                before[dashboard.id]['sample_dashboard_file_path'],
            )
            self.assertEqual(
                self._binary_digest(dashboard),
                before[dashboard.id]['spreadsheet_binary_digest'],
            )
            self.assertEqual(dashboard.is_published, before[dashboard.id]['is_published'])
            self.assertEqual(dashboard.group_ids.ids, before[dashboard.id]['group_ids'])
            self.assertEqual(dashboard.company_ids.ids, before[dashboard.id]['company_ids'])
            self.assertEqual(
                dashboard.favorite_user_ids.ids,
                before[dashboard.id]['favorite_user_ids'],
            )

    def test_manager_dashboards_remain_in_the_sales_group(self):
        sales = self.env.ref('spreadsheet_dashboard.spreadsheet_dashboard_group_sales')
        for xmlid in (
            'baseer_sales_dashboard.dashboard_executive_center',
            'baseer_sales_dashboard.dashboard_sales_summary',
            'baseer_sales_heat_calendar.dashboard_sales_heat_calendar',
        ):
            dashboard = self.env.ref(xmlid, raise_if_not_found=False)
            if dashboard:
                self.assertEqual(dashboard.dashboard_group_id, sales)

    def test_archived_arabic_languages_are_skipped(self):
        Dashboard = self.env['spreadsheet.dashboard']
        languages = self.env['res.lang'].with_context(active_test=False).search([
            ('code', 'in', ('ar', 'ar_001')),
        ])
        if languages:
            self.env.cr.execute(
                'UPDATE res_lang SET active = FALSE WHERE id IN %s', [tuple(languages.ids)],
            )
            languages.invalidate_recordset(['active'])

        Dashboard.with_context(lang='en_US')._baseer_reorganize_dashboard_navigation()
