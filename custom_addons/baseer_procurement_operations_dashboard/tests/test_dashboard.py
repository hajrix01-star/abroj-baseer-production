from datetime import date, datetime

from odoo import Command, api
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class ProcurementOperationsDashboardCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.company_a = self.env['res.company'].create({'name': 'Procurement dashboard A'})
        self.company_b = self.env['res.company'].create({'name': 'Procurement dashboard B'})
        self.warehouse_a = self.env['stock.warehouse'].create({
            'name': 'Procurement dashboard warehouse A', 'code': 'PDA', 'company_id': self.company_a.id,
        })
        self.warehouse_b = self.env['stock.warehouse'].create({
            'name': 'Procurement dashboard warehouse B', 'code': 'PDB', 'company_id': self.company_b.id,
        })
        self.manager_group = self.env.ref('baseer_procurement_requests.group_procurement_manager')
        self.cashier_group = self.env.ref('baseer_procurement_requests.group_procurement_cashier')
        self.requester_group = self.env.ref('baseer_procurement_requests.group_procurement_user')
        self.dashboard = self.env['spreadsheet.dashboard'].sudo().create({
            'name': 'Procurement dashboard test',
            'dashboard_group_id': self.env.ref(
                'baseer_procurement_operations_dashboard.dashboard_group_procurement'
            ).id,
            'baseer_dashboard_kind': 'procurement_operations',
            'is_published': True,
            'company_ids': [Command.set(self.company_a.ids)],
            'group_ids': [Command.set([self.manager_group.id, self.cashier_group.id])],
        })

    def _user(self, name, group, companies=None):
        companies = companies or self.company_a
        return self.env['res.users'].sudo().with_context(no_reset_password=True).create({
            'name': name,
            'login': name.lower().replace(' ', '_'),
            'company_id': self.company_a.id,
            'company_ids': [Command.set(companies.ids)],
            'group_ids': [Command.set([group.id])],
        })

    def _as_user(self, user, company=None):
        company = company or self.company_a
        return api.Environment(self.env.cr, user.id, {
            **self.env.context, 'allowed_company_ids': [company.id],
        })['spreadsheet.dashboard'].browse(self.dashboard.id)

    def _request(self, state, request_date, company=None, warehouse=None, actual_confirmed_at=False):
        company = company or self.company_a
        warehouse = warehouse or self.warehouse_a
        request = self.env['baseer.procurement.request'].sudo().with_company(company).with_context(
            allowed_company_ids=[company.id],
        ).create({
            'company_id': company.id,
            'warehouse_id': warehouse.id,
            'request_date': request_date,
            'purchase_route': 'cash',
        })
        # A dashboard fixture needs each immutable workflow outcome without
        # invoking the unrelated receipt/accounting paths.  Direct SQL is test
        # setup only; production dashboard code remains normal read-only ORM.
        request.flush_recordset(['state', 'actual_confirmed_at'])
        self.env.cr.execute(
            'UPDATE baseer_procurement_request SET state = %s, actual_confirmed_at = %s WHERE id = %s',
            [state, actual_confirmed_at or None, request.id],
        )
        request.invalidate_recordset(['state', 'actual_confirmed_at'])
        return request

    def test_pod_t01_payload_counts_pending_queue_and_completion_are_operational(self):
        draft = self._request('draft', datetime(2026, 11, 3, 8, 0))
        sent = self._request('sent', datetime(2026, 11, 2, 8, 0))
        received = self._request('received', datetime(2026, 11, 4, 8, 0))
        completed = self._request('purchased', datetime(2026, 11, 1, 8, 0), actual_confirmed_at=datetime(2026, 11, 5, 10, 0))
        self._request('cancel', datetime(2026, 11, 2, 8, 0))
        manager = self._user('Procurement dashboard manager', self.manager_group)

        payload = self._as_user(manager).get_baseer_procurement_operations_metrics({'native': {
            'type': 'range', 'from': '2026-11-01', 'to': '2026-11-05',
        }})

        self.assertEqual(payload['cards']['total']['value'], 4)
        for state in ('draft', 'sent', 'received', 'purchased'):
            self.assertEqual(payload['cards'][state]['value'], 1)
        self.assertEqual({row['id'] for row in payload['pending_queue']}, {draft.id, sent.id, received.id})
        self.assertNotIn(completed.id, {row['id'] for row in payload['pending_queue']})
        self.assertEqual(payload['completion_timeline'], [{'key': '2026-11-05', 'label': '2026-11-05', 'count': 1}])
        self.assertNotIn('account.move', str(payload))
        self.assertNotIn('amount_total', str(payload))
        self.assertIn(('company_id', '=', self.company_a.id), payload['source_action']['domain'])

    def test_pod_t02_company_isolation_and_no_write_side_effect(self):
        local = self._request('draft', datetime(2026, 11, 3, 8, 0))
        foreign = self._request('sent', datetime(2026, 11, 3, 8, 0), self.company_b, self.warehouse_b)
        manager = self._user('Procurement dashboard multico', self.manager_group, self.company_a | self.company_b)
        before = local.write_date

        payload = self._as_user(manager).get_baseer_procurement_operations_metrics({'native': {
            'type': 'range', 'from': '2026-11-01', 'to': '2026-11-06',
        }})

        self.assertEqual(payload['cards']['total']['value'], 1)
        self.assertNotIn(foreign.id, {row['id'] for row in payload['pending_queue']})
        local.invalidate_recordset(['write_date'])
        self.assertEqual(local.write_date, before)
        with self.assertRaises(AccessError):
            self._as_user(manager, self.company_b).get_baseer_procurement_operations_metrics({'native': None})

    def test_pod_t03_requester_and_invalid_filters_are_denied(self):
        requester = self._user('Procurement dashboard requester', self.requester_group)
        with self.assertRaises(AccessError):
            self._as_user(requester).get_baseer_procurement_operations_metrics({'native': None})
        manager = self._user('Procurement dashboard filter manager', self.manager_group)
        with self.assertRaises(ValidationError):
            self._as_user(manager).get_baseer_procurement_operations_metrics({'unsupported': None})
        with self.assertRaises(ValidationError):
            self._as_user(manager).get_baseer_procurement_operations_metrics({'native': {
                'type': 'range', 'from': '2025-01-01', 'to': '2026-01-02',
            }})

    def test_pod_t04_queue_and_breakdowns_are_bounded(self):
        for number in range(25):
            self._request('draft', datetime(2026, 11, 1, 8, 0))
        manager = self._user('Procurement dashboard cashier', self.cashier_group)
        payload = self._as_user(manager).get_baseer_procurement_operations_metrics({'native': {
            'type': 'range', 'from': '2026-11-01', 'to': '2026-11-01',
        }})
        self.assertEqual(len(payload['pending_queue']), 20)
        self.assertLessEqual(len(payload['cohort_timeline']), 366)
        self.assertLessEqual(len(payload['dimensions']['warehouses']), 7)
