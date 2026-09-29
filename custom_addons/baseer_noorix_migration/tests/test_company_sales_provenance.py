from psycopg2 import IntegrityError

from odoo import SUPERUSER_ID, api, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from ..models.migration_models import WRITER_CONTEXT


class NoorixCompanySalesProvenanceCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.writer = api.Environment(
            cls.env.cr, SUPERUSER_ID, {**cls.env.context, WRITER_CONTEXT: True},
        )
        cls.company = cls.env.company
        cls.env.user.group_ids |= cls.env.ref('point_of_sale.group_pos_manager')
        cls.summary_config = cls.env['pos.config'].search([
            ('company_id', '=', cls.company.id),
            ('baseer_summary_only', '=', True),
        ], limit=1)
        if not cls.summary_config:
            cls.summary_config = cls.env['pos.config'].create({
                'name': 'Noorix provenance summary POS',
                'company_id': cls.company.id,
                'baseer_summary_only': True,
            })
        cls.summary = cls.env['baseer.pos.summary'].create({
            'company_id': cls.company.id,
            'config_id': cls.summary_config.id,
            'business_date': fields.Date.to_date('2026-05-26'),
            'period_scope': 'all',
            'day_schedule': 'all',
            'zero_sales': True,
            'customer_count': 0,
        })

    def _run(self, scope, suffix):
        return self.writer['baseer.noorix.migration.run'].create({
            'name': 'NOORIX-%s-%s' % (scope, suffix),
            'source_archive_sha256': 'archive-' + suffix,
            'source_tenant_id': 'tenant-1',
            'payload_sha256': 'payload-' + suffix,
            'scope': scope,
        })

    def _company_values(self, run, source_company_id='company-1'):
        return {
            'source_tenant_id': 'tenant-1',
            'source_company_id': source_company_id,
            'source_row_sha256': 'row-' + source_company_id,
            'source_archive_sha256': run.source_archive_sha256,
            'canonical_key': 'company:' + source_company_id,
            'decision': 'reuse_existing_company',
            'company_id': self.company.id,
            'run_id': run.id,
        }

    def _sales_values(self, run, source_summary_id='summary-1', decision='create_summary'):
        return {
            'source_tenant_id': 'tenant-1',
            'source_company_id': 'company-1',
            'source_summary_id': source_summary_id,
            'source_row_sha256': 'row-' + source_summary_id,
            'source_archive_sha256': run.source_archive_sha256,
            'canonical_key': 'sales:company-1:2026-05-26:all',
            'source_gross': 125.50,
            'source_customers': 7,
            'business_date': fields.Date.to_date('2026-05-26'),
            'shift': 'all',
            'decision': decision,
            'summary_id': self.summary.id,
            'run_id': run.id,
        }

    def test_company_mapping_is_writer_only_write_once_and_append_only(self):
        run = self._run('company_master', 'company-guard')
        values = self._company_values(run)
        with self.assertRaises(AccessError):
            self.env['baseer.noorix.company.map'].create(values)
        mapping = self.writer['baseer.noorix.company.map'].create(values)
        self.assertEqual(mapping.company_id, self.company)
        self.assertEqual(mapping.run_id.scope, 'company_master')
        with self.assertRaises(UserError):
            mapping.write({'canonical_key': 'changed'})
        with self.assertRaises(AccessError):
            mapping.unlink()

    @mute_logger('odoo.sql_db')
    def test_company_source_is_unique_but_multiple_sources_may_share_target(self):
        run = self._run('company_master', 'company-unique')
        company_map = self.writer['baseer.noorix.company.map']
        first = company_map.create(self._company_values(run, 'company-a'))
        second = company_map.create({
            **self._company_values(run, 'company-b'),
            'decision': 'alias_archived_company',
        })
        self.assertEqual(first.company_id, second.company_id)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            company_map.create(self._company_values(run, 'company-a'))

    def test_sales_mapping_is_writer_only_write_once_and_append_only(self):
        run = self._run('sales_summary', 'sales-guard')
        values = self._sales_values(run)
        with self.assertRaises(AccessError):
            self.env['baseer.noorix.sales.summary.map'].create(values)
        mapping = self.writer['baseer.noorix.sales.summary.map'].create(values)
        self.assertEqual(mapping.summary_id, self.summary)
        self.assertEqual(mapping.run_id.scope, 'sales_summary')
        self.assertEqual(mapping.source_gross, 125.50)
        with self.assertRaises(UserError):
            mapping.write({'source_customers': 8})
        with self.assertRaises(AccessError):
            mapping.unlink()

    @mute_logger('odoo.sql_db')
    def test_sales_sources_are_unique_and_may_merge_into_one_summary(self):
        run = self._run('sales_summary', 'sales-merge')
        sales_map = self.writer['baseer.noorix.sales.summary.map']
        created = sales_map.create(self._sales_values(run, 'arz-2026-05-26-a'))
        merged = sales_map.create(self._sales_values(
            run, 'arz-2026-05-26-b', decision='merge_into_all_day',
        ))
        self.assertEqual(created.summary_id, merged.summary_id)
        self.assertEqual(sales_map.search_count([
            ('summary_id', '=', self.summary.id),
            ('run_id', '=', run.id),
        ]), 2)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            sales_map.create(self._sales_values(run, 'arz-2026-05-26-a'))
