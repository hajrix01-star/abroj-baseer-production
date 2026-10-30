import json
from datetime import timedelta
from urllib.parse import unquote

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.abroj_project_dashboard.hooks import backfill_duration
from odoo.tests import HttpCase, TransactionCase, tagged


class AbrojProjectDashboardCase(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.client = cls.env['res.partner'].create({'name': 'Dashboard client'})
        cls.manager = cls.env.user
        cls.project = cls.env['project.project'].create({
            'name': 'Dashboard fixture', 'company_id': cls.env.company.id,
            'partner_id': cls.client.id, 'user_id': cls.manager.id,
            'abroj_budget': 100, 'abroj_contract_value': 200,
            'abroj_type': 'residential', 'date_start': cls.today,
            'date': cls.today + timedelta(days=30),
        })
        cls.engineer = cls.env['res.users'].create({
            'name': 'Dashboard engineer', 'login': 'dashboard_engineer_test',
            'group_ids': [Command.set([cls.env.ref('base.group_user').id, cls.env.ref('project.group_project_user').id])],
        })

    def ids(self, filters):
        return [p['id'] for p in self.env['project.project'].get_abroj_dashboard_data(filters)['projects']]

    def test_duration_inclusive_and_recompute(self):
        task = self.env['project.task'].create({'name': 'Phase', 'project_id': self.project.id, 'x_abroj_date_start': '2026-11-01', 'x_abroj_duration_days': 3})
        self.assertEqual(fields.Date.to_date(task.date_deadline), fields.Date.to_date('2026-11-03'))
        task.write({'x_abroj_date_start': '2026-11-08'})
        self.assertEqual(fields.Date.to_date(task.date_deadline), fields.Date.to_date('2026-11-10'))
        task.write({'x_abroj_duration_days': 1})
        self.assertEqual(fields.Date.to_date(task.date_deadline), fields.Date.to_date('2026-11-08'))
        task.write({'date_deadline': '2027-01-01 00:00:00'})
        self.assertEqual(fields.Date.to_date(task.date_deadline), fields.Date.to_date('2026-11-08'))

    def test_duration_without_start_preserves_deadline(self):
        task = self.env['project.task'].create({'name': 'Unscheduled', 'project_id': self.project.id, 'date_deadline': '2026-11-03 12:00:00'})
        task.write({'x_abroj_duration_days': 3})
        self.assertEqual(fields.Datetime.to_string(task.date_deadline), '2026-11-03 12:00:00')

    def test_duration_validation(self):
        task = self.env['project.task'].create({'name': 'Phase', 'project_id': self.project.id})
        for duration in (0, -1):
            with self.assertRaises(ValidationError), self.env.cr.savepoint():
                task.write({'x_abroj_duration_days': duration})

    def test_duration_backfill(self):
        task = self.env['project.task'].create({'name': 'Legacy', 'project_id': self.project.id, 'x_abroj_date_start': '2026-11-01'})
        task.flush_recordset()
        self.env.cr.execute("UPDATE project_task SET date_deadline = '2026-11-03 12:00:00' WHERE id = %s", [task.id])
        backfill_duration(self.env.cr)
        task.invalidate_recordset(['x_abroj_duration_days', 'date_deadline'])
        self.assertEqual(task.x_abroj_duration_days, 3)
        self.assertEqual(fields.Datetime.to_string(task.date_deadline), '2026-11-03 12:00:00')

    def test_analytic_actual_cost(self):
        plan = self.env['account.analytic.plan'].create({'name': 'Dashboard plan'})
        account = self.env['account.analytic.account'].create({'name': 'Dashboard account', 'plan_id': plan.id, 'company_id': self.env.company.id})
        self.project.account_id = account
        line = self.env['abroj.project.budget.line'].create({'project_id': self.project.id, 'name': 'Cost', 'budget': 40, 'manual_actual': 5})
        for amount in (-50, 100):
            self.env['account.analytic.line'].create({'name': 'Entry', 'account_id': account.id, 'company_id': self.env.company.id, 'date': self.today, 'amount': amount, 'abroj_budget_line_id': line.id})
        self.assertEqual(self.project._abroj_data()['actual'], 55)
        self.assertEqual(line.actual, 55)
        engineer_data = self.project.with_user(self.engineer)._abroj_data()
        self.assertEqual(engineer_data['actual'], 5)
        self.assertEqual(engineer_data['categories'][0]['actual'], 5)

    def test_over_budget_positive(self):
        self.env['abroj.project.budget.line'].create({'project_id': self.project.id, 'name': 'Cost', 'manual_actual': 120})
        self.assertEqual(self.project._abroj_data()['over'], 20)

    def test_under_budget_with_over_category(self):
        self.env['abroj.project.budget.line'].create({'project_id': self.project.id, 'name': 'Cost', 'budget': 10, 'manual_actual': 20})
        data = self.project._abroj_data()
        self.assertEqual((data['over'], data['over_categories']), (0, 1))

    def test_manual_progress(self):
        self.project.write({'abroj_use_manual_progress': True, 'abroj_manual_progress': 75})
        self.assertEqual(self.project._abroj_data()['progress'], 75)

    def test_task_progress(self):
        self.env['project.task'].create([{'name': 'Done', 'project_id': self.project.id, 'state': '1_done'}, {'name': 'Open', 'project_id': self.project.id}])
        self.assertEqual(self.project._abroj_data()['progress'], 50)

    def test_liquidity(self):
        if 'abroj.contracting.voucher' in self.env:
            subcontract = self.env['abroj.contracting.subcontractor'].create({'project_id': self.project.id, 'partner_id': self.client.id, 'agreed_amount': 200})
            for kind, amount in [('receipt', 150), ('payment', 40)]:
                voucher = self.env['abroj.contracting.voucher'].create({'project_id': self.project.id, 'partner_id': self.client.id, 'kind': kind, 'amount': amount, 'subcontractor_id': subcontract.id if kind == 'payment' else False})
                voucher.action_issue()
            data = self.project._abroj_data()
            self.assertEqual((data['received'], data['paid'], data['liquidity']), (150, 40, 110))
            self.assertEqual(len(data['vouchers']), 2)
        else:
            self.assertEqual(self.project._abroj_data()['liquidity'], 0)

    def test_delayed_task(self):
        self.env['project.task'].create({'name': 'Late', 'project_id': self.project.id, 'date_deadline': fields.Datetime.now() - timedelta(days=2)})
        self.assertTrue(self.project._abroj_data()['delayed'])

    def test_delayed_project(self):
        self.project.date = self.today - timedelta(days=1)
        self.assertTrue(self.project._abroj_data()['delayed'])

    def test_stalled_status(self):
        self.project.last_update_status = 'off_track'
        self.assertTrue(self.project._abroj_data()['stalled'])

    def test_stalled_inactivity(self):
        self.env.cr.execute('UPDATE project_project SET write_date = %s WHERE id = %s', [fields.Datetime.now() - timedelta(days=40), self.project.id])
        self.project.invalidate_recordset(['write_date'])
        self.assertTrue(self.project._abroj_data()['stalled'])

    def test_completed_not_delayed_or_stalled(self):
        self.project.write({'last_update_status': 'done', 'date': self.today - timedelta(days=1)})
        data = self.project._abroj_data()
        self.assertTrue(data['completed'])
        self.assertFalse(data['delayed'] or data['stalled'])

    def test_dashboard_data(self):
        data = self.env['project.project'].get_abroj_dashboard_data()
        self.assertIn(self.project.id, [p['id'] for p in data['projects']])
        self.assertTrue(data['types'])

    def test_filter_type(self):
        self.assertIn(self.project.id, self.ids({'type': 'residential'}))
        self.assertNotIn(self.project.id, self.ids({'type': 'commercial'}))

    def test_filter_status(self):
        self.assertIn(self.project.id, self.ids({'status': 'ongoing'}))
        self.assertNotIn(self.project.id, self.ids({'status': 'completed'}))
        self.project.last_update_status = 'off_track'
        self.assertIn(self.project.id, self.ids({'status': 'stalled'}))
        self.assertIn(self.project.id, self.ids({'status': 'off_track'}))
        self.project.date = self.today - timedelta(days=1)
        self.assertIn(self.project.id, self.ids({'status': 'delayed'}))
        self.project.last_update_status = 'done'
        self.assertIn(self.project.id, self.ids({'status': 'completed'}))
        self.assertNotIn(self.project.id, self.ids({'status': 'ongoing'}))

    def test_filter_manager(self):
        self.assertIn(self.project.id, self.ids({'manager': self.manager.id}))
        self.assertNotIn(self.project.id, self.ids({'manager': self.engineer.id}))

    def test_filter_client(self):
        self.assertIn(self.project.id, self.ids({'client': self.client.id}))
        self.assertNotIn(self.project.id, self.ids({'client': self.engineer.partner_id.id}))

    def test_filter_search(self):
        self.assertIn(self.project.id, self.ids({'search': 'fixture'}))
        self.assertNotIn(self.project.id, self.ids({'search': 'unmatched'}))

    def test_filter_period(self):
        self.assertIn(self.project.id, self.ids({'from': str(self.today), 'to': str(self.today)}))
        self.assertNotIn(self.project.id, self.ids({'from': str(self.today + timedelta(days=31))}))
        self.assertNotIn(self.project.id, self.ids({'to': str(self.today - timedelta(days=1))}))

    def test_detail(self):
        data = self.env['project.project'].get_abroj_project_detail(self.project.id)
        self.assertEqual((data['id'], data['client'], data['contract']), (self.project.id, self.client.name, 200))
        self.assertFalse(self.env['project.project'].get_abroj_project_detail(999999999))

    def test_engineer_budget_permissions(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.engineer).write({'abroj_budget': 100})
        with self.assertRaises(AccessError):
            self.env['abroj.project.budget.line'].with_user(self.engineer).create({'project_id': self.project.id, 'name': 'Cost'})
        self.assertFalse(self.project.with_user(self.engineer)._abroj_data()['can_edit_budget'])


@tagged('-at_install', 'post_install')
class AbrojDashboardHttpCase(HttpCase):
    def rpc(self, path, params):
        response = self.url_open(path, data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}), headers={'Content-Type': 'application/json'})
        return response.json()['result']

    def test_login_redirect(self):
        response = self.url_open('/abroj/app', allow_redirects=False)
        self.assertIn('/web/login', response.headers['Location'])
        self.assertIn('/abroj/app', unquote(response.headers['Location']))

    def test_dashboard_json(self):
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/data', {'filters': {'search': 'no such project'}})
        self.assertEqual(result['projects'], [])
        self.assertTrue(result['types'])

    def test_detail_json(self):
        project = self.env['project.project'].create({'name': 'HTTP detail', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertEqual(result['name'], 'HTTP detail')
        self.assertTrue(result['can_edit_budget'])

    def test_save_json_rejects_forbidden_field(self):
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/save', {'model': 'project.project', 'values': {'name': 'forbidden'}})
        self.assertIn('error', result)

    def test_upload_and_gallery(self):
        import io
        import re
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (2200, 100), 'red').save(image, 'PNG')
        original = image.getvalue()
        project = self.env['project.project'].create({'name': 'Upload fixture', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        page = self.url_open('/abroj/app').text
        token = re.search(r'name="csrf-token" content="([^"]+)', page).group(1)
        response = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id)}, files={'file': ('original.png', original, 'image/png')})
        attachment_id = response.json()['id']
        attachment = self.env['ir.attachment'].browse(attachment_id)
        self.assertEqual(attachment.raw, original)
        gallery = self.rpc('/abroj/app/attachments', {'model': 'project.project', 'record_id': project.id})
        self.assertIn(attachment_id, [item['id'] for item in gallery])

    def test_create_phase_with_duration(self):
        project = self.env['project.project'].create({'name': 'Phase HTTP', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/save', {'model': 'project.task', 'values': {'name': 'Phase', 'project_id': project.id, 'x_abroj_date_start': '2026-11-01', 'x_abroj_duration_days': 3}})
        self.assertIn('id', result)
        detail = self.rpc('/abroj/app/data', {'project_id': project.id})
        phase = next(p for p in detail['phases'] if p['id'] == result['id'])
        self.assertEqual((phase['duration'], phase['end']), (3, '2026-11-03'))

    def test_engineer_permission_endpoints(self):
        project = self.env['project.project'].create({'name': 'Engineer fixture', 'company_id': self.env.company.id, 'privacy_visibility': 'employees'})
        self.env['res.users'].create({'name': 'Engineer HTTP', 'login': 'engineer_http', 'password': 'engineer_http', 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('engineer_http', 'engineer_http')
        detail = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertFalse(detail['can_edit_budget'])
        result = self.rpc('/abroj/app/save', {'model': 'project.project', 'record_id': project.id, 'values': {'abroj_budget': 999}})
        self.assertIn('error', result)
        result = self.rpc('/abroj/app/save', {'model': 'project.project', 'record_id': project.id, 'values': {'abroj_budget_line_ids': [[0, 0, {'name': 'Forbidden', 'budget': 99}]]}})
        self.assertIn('error', result)
        self.assertEqual(project.abroj_budget, 0)
        result = self.rpc('/abroj/app/attachments', {'model': 'res.users', 'record_id': 1})
        self.assertIn('error', result)
        task = self.rpc('/abroj/app/save', {'model': 'project.task', 'values': {'name': 'Engineer task', 'project_id': project.id, 'x_abroj_progress': 30}})
        self.assertIn('id', task)
        import re
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        uploaded = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.task', 'record_id': str(task['id'])}, files={'file': ('voice.webm', b'voice bytes', 'audio/webm')})
        self.assertIn('id', uploaded.json())
        denied = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'res.users', 'record_id': '1'}, files={'file': ('voice.webm', b'voice bytes', 'audio/webm')})
        self.assertEqual(denied.status_code, 403)
