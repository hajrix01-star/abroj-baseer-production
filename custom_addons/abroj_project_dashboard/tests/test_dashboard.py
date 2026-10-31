import base64
import io
import json
import re
import shutil
import subprocess
from pathlib import Path
from datetime import timedelta
from urllib.parse import unquote

from PIL import Image

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

    def test_shared_gallery_metadata(self):
        task = self.env['project.task'].create({'name': 'Gallery phase', 'project_id': self.project.id})
        other = self.env['project.project'].create({'name': 'Other gallery'})
        image = self.env['ir.attachment'].create({'name': 'image.png', 'mimetype': 'image/png', 'datas': 'eA==', 'res_model': 'project.task', 'res_id': task.id})
        self.env['ir.attachment'].create({'name': 'other.png', 'mimetype': 'image/png', 'datas': 'eA==', 'res_model': 'project.project', 'res_id': other.id})
        task.message_post(body='Gallery test note', message_type='comment', subtype_xmlid='mail.mt_note')
        gallery = self.env['abroj.gallery']
        rows = self.project.get_abroj_gallery()
        self.assertTrue(any(row['id'] == image.id and row['phase'] == task.name and row['type'] == 'image' for row in rows))
        self.assertTrue(any(row['type'] == 'note' and row['description'] == 'Gallery test note' for row in rows))
        self.assertEqual(rows, gallery.get_items('project.project', self.project.id))
        self.assertEqual([row['id'] for row in gallery.get_items('project.project', self.project.id, type='image')], [image.id])
        self.assertEqual(gallery.get_items('project.project', self.project.id, task_id=99999999), [])

    def test_project_navigation_includes_closed_and_inactive(self):
        closed = self.env['project.project'].create({'name': 'Closed navigation', 'last_update_status': 'done'})
        inactive = self.env['project.project'].create({'name': 'Inactive navigation', 'active': False})
        model = self.env['project.project']
        normal = model.get_abroj_dashboard_data()['projects']
        all_projects = model.get_abroj_dashboard_data(include_archived=True)['projects']
        self.assertNotIn(inactive.id, [p['id'] for p in normal])
        by_id = {p['id']: p for p in all_projects}
        self.assertFalse(by_id[self.project.id]['archived'])
        self.assertTrue(by_id[closed.id]['archived'])
        self.assertTrue(by_id[inactive.id]['archived'])
        self.assertEqual(model.get_abroj_project_detail(inactive.id)['id'], inactive.id)

    def test_close_summary_and_permissions(self):
        self.env['project.task'].create({'name': 'Outstanding', 'project_id': self.project.id})
        self.env['abroj.contracting.subcontractor'].create({'project_id': self.project.id, 'partner_id': self.client.id, 'agreed_amount': 80})
        voucher = self.env['abroj.contracting.voucher'].create({'project_id': self.project.id, 'partner_id': self.client.id, 'kind': 'receipt', 'amount': 50})
        voucher.action_issue()
        self.env['abroj.contracting.voucher'].create({'project_id': self.project.id, 'partner_id': self.client.id, 'kind': 'receipt', 'amount': 10})
        summary = self.project.abroj_close_summary()
        self.assertIn('Outstanding', summary['unfinished'])
        self.assertEqual(summary['receivable'], 150)
        self.assertEqual(summary['payable'], 80)
        self.assertEqual(len(summary['draft_vouchers']), 1)
        with self.assertRaises(AccessError):
            self.project.with_user(self.engineer).abroj_close_summary()
        with self.assertRaises(AccessError):
            self.project.with_user(self.engineer).abroj_set_closed(True)

    def test_close_reopen_and_active_views(self):
        owner = self.env['res.users'].create({'name': 'Close owner', 'login': 'close_owner_test', 'group_ids': [Command.set([self.env.ref('project.group_project_manager').id])]})
        self.env['project.project'].ensure_abroj_closed_stage()
        self.env['project.project.stage'].search([('fold', '=', False)], limit=1) or self.env['project.project.stage'].create({'name': 'Active'})
        self.env['project.task'].create({'name': 'Today', 'project_id': self.project.id, 'x_abroj_date_start': self.today, 'x_abroj_duration_days': 1})
        self.project.with_user(owner).abroj_set_closed(True, 'Finished')
        self.assertTrue(self.project.stage_id.fold)
        self.assertEqual(self.project.abroj_closed_date, self.today)
        self.assertNotIn(self.project.id, self.ids({}))
        self.assertNotIn(self.project.id, [p['id'] for p in self.env['project.project'].get_abroj_my_day()])
        archive = [p for p in self.env['project.project'].get_abroj_dashboard_data(include_archived=True)['projects'] if p['archived']]
        self.assertIn(self.project.id, [p['id'] for p in archive])
        self.project.with_user(owner).abroj_set_closed(False)
        self.assertFalse(self.project.abroj_closed_date)
        self.assertFalse(self.project.stage_id.fold)
        self.assertIn(self.project.id, self.ids({}))

    def test_pwa_has_no_native_dialogs(self):
        js_dir = Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js'
        for path in js_dir.glob('*.js'):
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('alert(', source, path.name)
            self.assertNotIn('confirm(', source, path.name)

    def test_drawer_open_in_odoo(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required to execute the drawer renderer')
        js_dir = Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js'
        source = (js_dir / 'screens.js').read_text(encoding='utf-8')
        translations = (js_dir / 'i18n.js').read_text(encoding='utf-8')
        self.assertIn('"openInOdoo": {"ar": "فتح في أودو", "en": "Open in Odoo"}', translations)
        renderer = source[source.index('function renderDrawer()'):source.index('function measureDrawer()')]
        script = "let currentProject, drawerExpanded=false; const drawer={}; const document={getElementById:()=>drawer}; const t=k=>k;\n" + renderer + """
            for (const [project, href] of [[null, '/odoo/project'], [{id: 42}, '/odoo/project/42']]) {
                currentProject = project; renderDrawer();
                if (!drawer.innerHTML.includes(`href="${href}" target="_blank" rel="noopener"`) ||
                    !drawer.innerHTML.includes('openInOdoo')) throw new Error('Incorrect drawer link');
            }
        """
        subprocess.run([node, '-e', script], check=True, capture_output=True, text=True)

    def test_pwa_gregorian_date_formatter(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required to execute the PWA formatter')
        source = (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js' / 'app.js').read_text(encoding='utf-8')
        formatter = next(line for line in source.splitlines() if line.startswith('const date='))
        number_formatter = next(line for line in source.splitlines() if line.startswith('const number='))
        money_formatter = next(line for line in source.splitlines() if line.startswith('const money='))
        locale_formatter = next(line for line in source.splitlines() if line.startswith('const locale='))
        for path in (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js').glob('*.js'):
            self.assertNotRegex(path.read_text(encoding='utf-8'), r'[٠-٩۰-۹]', path.name)
        script = "let lang;\n" + locale_formatter + "\n" + number_formatter + "\n" + money_formatter + "\n" + formatter + "\n" + """
            for (lang of ['ar', 'en']) {
                if (/[٠-٩۰-۹]/.test(number(1234.5) + money(1234))) throw new Error('Non-Latin digits');
                if (date('2026-10-30') !== '30/10/2026' ||
                    date('2024-02-29') !== '29/02/2024' ||
                    date('2026-02-29') !== '—' || date('') !== '—') {
                    throw new Error('Unexpected date format for ' + lang);
                }
            }
        """
        subprocess.run([node, '-e', script], check=True, capture_output=True, text=True)

    def test_voice_gesture_translations(self):
        source = (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js' / 'i18n.js').read_text(encoding='utf-8')
        self.assertIn("holdRecord:['اضغط مطوّلاً للتسجيل','Press and hold to record']", source)
        self.assertIn("slideCancel:['اسحب للإلغاء','Slide to cancel']", source)
        self.assertIn("invoiceCapture:['فاتورة','Invoice']", source)
        self.assertIn("invoiceChoice:['إضافة فاتورة','Add invoice']", source)
        self.assertIn("invoiceDraft:['فاتورة مورد مسودة','Draft vendor bill']", source)

    def test_my_day_grouping_dates_and_permissions(self):
        public = self.env['project.project'].create({'name': 'My Day public', 'company_id': self.env.company.id, 'privacy_visibility': 'employees'})
        private = self.env['project.project'].create({'name': 'My Day private', 'company_id': self.env.company.id, 'privacy_visibility': 'followers'})
        tasks = self.env['project.task']
        def phase(project, name, start=None, duration=1, deadline=None):
            values = {'project_id': project.id, 'name': name, 'x_abroj_duration_days': duration}
            if start:
                values['x_abroj_date_start'] = start
            if deadline:
                values['date_deadline'] = deadline
            return tasks.create(values)
        spanning = phase(public, 'Spanning', self.today - timedelta(days=1), 3)
        due = phase(public, 'Due', deadline=fields.Datetime.to_datetime(self.today))
        other = phase(self.project, 'Today', self.today)
        past = phase(public, 'Past', self.today - timedelta(days=2))
        phase(public, 'Future', self.today + timedelta(days=1))
        hidden = phase(private, 'Hidden', self.today)
        groups = self.env['project.project'].get_abroj_my_day()
        by_project = {g['id']: {p['id'] for p in g['phases']} for g in groups}
        self.assertEqual(by_project[public.id], {past.id, spanning.id, due.id})
        self.assertIn(other.id, by_project[self.project.id])
        self.assertIn(hidden.id, by_project[private.id])
        visible = self.env['project.project'].with_user(self.engineer).get_abroj_my_day()
        self.assertNotIn(private.id, {g['id'] for g in visible})
        self.assertEqual({p['id'] for g in visible if g['id'] == public.id for p in g['phases']}, {past.id, spanning.id, due.id})

    def test_my_day_priority_and_local_day(self):
        import pytz

        model = self.env['project.project'].with_context(tz='Pacific/Kiritimati')
        today = fields.Date.context_today(model)
        local_start = pytz.timezone('Pacific/Kiritimati').localize(fields.Datetime.to_datetime(today))
        utc_start = local_start.astimezone(pytz.UTC).replace(tzinfo=None)
        projects = self.env['project.project'].create([
            {'name': 'My Day rest first'}, {'name': 'My Day priority second'},
            {'name': 'My Day priority third'}, {'name': 'My Day rest last'},
        ])
        tasks = self.env['project.task']
        def phase(project, name, start, deadline, state='01_in_progress'):
            task = tasks.create({'project_id': project.id, 'name': name, 'x_abroj_date_start': start, 'state': state})
            # Set explicit datetime deadlines to exercise the local midnight boundary.
            self.env.cr.execute('UPDATE project_task SET date_deadline = %s WHERE id = %s', [deadline, task.id])
            task.invalidate_recordset(['date_deadline'])
            return task

        future = today + timedelta(days=1)
        rest1 = phase(projects[0], 'Rest first', future, utc_start + timedelta(hours=1))
        rest2 = phase(projects[1], 'Rest in priority group', future, utc_start + timedelta(hours=1))
        current = phase(projects[1], 'Today', today, utc_start + timedelta(hours=1))
        late1 = phase(projects[1], 'Overdue earlier', today - timedelta(days=3), utc_start - timedelta(minutes=1))
        late2 = phase(projects[1], 'Overdue later', today - timedelta(days=2), utc_start - timedelta(days=1))
        phase(projects[1], 'Done overdue', today - timedelta(days=2), utc_start - timedelta(days=1), '1_done')
        phase(projects[1], 'Canceled overdue', today - timedelta(days=2), utc_start - timedelta(days=1), '1_canceled')
        done = phase(projects[1], 'Done today', today, utc_start + timedelta(hours=1), '1_done')
        current2 = phase(projects[2], 'Another today', today, utc_start + timedelta(hours=1))
        rest3 = phase(projects[3], 'Rest last', future, utc_start + timedelta(hours=1))
        groups = [group for group in model.get_abroj_my_day() if group['id'] in projects.ids]
        self.assertEqual([group['id'] for group in groups], [projects[1].id, projects[2].id, projects[0].id, projects[3].id])
        self.assertEqual([p['id'] for p in groups[0]['phases']], [late1.id, late2.id, current.id, done.id, rest2.id])
        statuses = {p['id']: (p['status'], p['overdue_days']) for p in groups[0]['phases']}
        self.assertEqual(statuses[late1.id], ('overdue', 1))
        self.assertEqual(statuses[late2.id], ('overdue', 1))
        self.assertEqual(statuses[current.id], ('on_time', 0))
        self.assertEqual(statuses[done.id], ('done', 0))
        self.assertEqual([[p['id'] for p in group['phases']] for group in groups[1:]], [[current2.id], [rest1.id], [rest3.id]])

    def test_dashboard_labels_follow_language(self):
        from odoo.addons.abroj_project_dashboard.models.dashboard import STATUS, TYPES
        self.project.last_update_status = 'on_track'
        project = self.project.with_context(lang='en_US')
        detail = project._abroj_data()
        self.assertEqual(detail['type_label'], 'Residential / villas')
        self.assertEqual(detail['status_label'], 'On track')
        self.assertEqual(next(t['name'] for t in project.get_abroj_dashboard_data()['types'] if t['id'] == 'residential'), 'Residential / villas')
        self.assertEqual(dict(TYPES)['residential'], 'سكني / فلل')
        self.assertEqual(STATUS['on_track'], 'على المسار')

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
        self.project.date = self.today + timedelta(days=30)
        self.project.last_update_status = 'done'
        self.assertNotIn(self.project.id, self.ids({'status': 'completed'}))
        self.assertIn(self.project.id, [p['id'] for p in self.env['project.project'].get_abroj_dashboard_data({'status': 'completed'}, include_archived=True)['projects']])
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

    def test_gallery_metadata_filters_and_text_note(self):
        project = self.env['project.project'].create({'name': 'Gallery project', 'company_id': self.env.company.id})
        task = self.env['project.task'].create({'name': 'Gallery phase', 'project_id': project.id})
        png = io.BytesIO()
        Image.new('RGB', (2000, 1500), (0, 0, 255)).save(png, format='PNG')
        attachments = self.env['ir.attachment'].create([
            {'name': 'project.png', 'mimetype': 'image/png', 'datas': base64.b64encode(png.getvalue()), 'res_model': 'project.project', 'res_id': project.id, 'description': 'Project photo'},
            {'name': 'phase.webm', 'mimetype': 'audio/webm', 'datas': 'eA==', 'res_model': 'project.task', 'res_id': task.id},
        ])
        self.authenticate('admin', 'admin')
        note = self.rpc('/abroj/app/note', {'model': 'project.task', 'record_id': task.id, 'body': 'Phase progress'})
        self.assertIn('id', note)
        args = {'model': 'project.project', 'record_id': project.id}
        rows = self.rpc('/abroj/app/attachments', args)
        image = next(x for x in rows if x['type'] == 'image' and x['id'] == attachments[0].id)
        audio = next(x for x in rows if x['type'] == 'audio' and x['id'] == attachments[1].id)
        text = next(x for x in rows if x['type'] == 'note' and x['id'] == note['id'])
        self.assertTrue(image['create_uid'])
        self.assertRegex(image['create_date'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        self.assertRegex(text['create_date'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
        thumbnail = self.url_open('/web/image/%s/320x320' % attachments[0].id)
        self.assertEqual(thumbnail.status_code, 200)
        with Image.open(io.BytesIO(thumbnail.content)) as preview:
            self.assertLessEqual(max(preview.size), 320)
            self.assertEqual(preview.convert('RGB').getpixel((0, 0)), (0, 0, 255))
        self.assertEqual(image['description'], 'Project photo')
        self.assertIsNone(image['phase'])
        self.assertEqual(audio['phase'], 'Gallery phase')
        self.assertEqual(text['description'], 'Phase progress')
        self.assertTrue(all(x['type'] == 'audio' for x in self.rpc('/abroj/app/attachments', dict(args, type='audio'))))
        self.assertTrue(all(x['res_model'] == 'project.task' and x['res_id'] == task.id for x in self.rpc('/abroj/app/attachments', dict(args, task_id=task.id))))
        self.assertTrue(all(x['uploader_id'] == image['uploader_id'] for x in self.rpc('/abroj/app/attachments', dict(args, uploader_id=image['uploader_id']))))
        self.assertEqual(self.rpc('/abroj/app/attachments', dict(args, uploader_id=99999999)), [])
        asc = self.rpc('/abroj/app/attachments', dict(args, sort='asc'))
        self.assertEqual([(x['type'], x['id']) for x in asc], list(reversed([(x['type'], x['id']) for x in rows])))

    def test_gallery_private_project_access(self):
        project = self.env['project.project'].create({'name': 'Private gallery', 'company_id': self.env.company.id, 'privacy_visibility': 'followers'})
        self.env['ir.attachment'].create({'name': 'secret.jpg', 'datas': 'eA==', 'res_model': 'project.project', 'res_id': project.id})
        self.env['res.users'].create({'name': 'Gallery outsider', 'login': 'gallery_outsider', 'password': 'gallery_outsider', 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('gallery_outsider', 'gallery_outsider')
        self.assertIn('error', self.rpc('/abroj/app/attachments', {'model': 'project.project', 'record_id': project.id}))
        self.assertIn('error', self.rpc('/abroj/app/note', {'model': 'project.project', 'record_id': project.id, 'body': 'Denied'}))

    def test_account_avatar_and_system_identity(self):
        import base64
        from ..controllers.app import AbrojApp

        self.assertFalse(AbrojApp._real_image(False))
        self.assertFalse(AbrojApp._real_image(base64.b64encode(b'<svg></svg>')))
        self.assertTrue(AbrojApp._real_image(base64.b64encode(b'photo bytes')))
        self.authenticate('admin', 'admin')
        user = self.rpc('/abroj/app/data', {})['current_user']
        self.assertTrue(user['is_system'])
        self.assertIn('avatar_url', user)
        self.assertIn('department', user)

    def test_create_project_fields(self):
        self.authenticate('admin', 'admin')
        partner = self.env['res.partner'].create({'name': 'Creation customer'})
        result = self.rpc('/abroj/app/project/create', {'name': ' New project ', 'customer_id': partner.id,
            'location': 'Riyadh', 'budget': 1250.5, 'start': '2026-01-01', 'end': '2026-02-01',
            'manager_id': self.env.ref('base.user_admin').id, 'project_type': 'commercial'})
        project = self.env['project.project'].browse(result['id'])
        self.assertEqual((project.name, project.partner_id.id, project.abroj_location, project.abroj_budget, project.abroj_type),
                         ('New project', partner.id, 'Riyadh', 1250.5, 'commercial'))
        self.assertEqual(str(project.date_start), '2026-01-01')
        self.assertEqual(str(project.date), '2026-02-01')
        self.assertEqual(project.user_id, self.env.ref('base.user_admin'))
        self.env['res.users'].create({'name': 'Create owner', 'login': 'create_owner', 'password': 'create_owner',
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_manager').id])]})
        self.authenticate('create_owner', 'create_owner')
        result = self.rpc('/abroj/app/project/create', {'name': 'Customer creation', 'customer_name': 'New customer'})
        self.assertEqual(self.env['project.project'].browse(result['id']).partner_id.name, 'New customer')

    def test_create_project_validation(self):
        self.authenticate('admin', 'admin')
        self.assertEqual(self.rpc('/abroj/app/project/create', {'name': '  '})['field'], 'name')
        self.assertEqual(self.rpc('/abroj/app/project/create', {'name': 'Invalid dates', 'start': '2026-02-01', 'end': '2026-01-01'})['field'], 'end')
        self.assertIn('error', self.rpc('/abroj/app/project/create', {'name': 'Invalid budget', 'budget': -1}))

    def test_create_project_engineer_denied(self):
        self.env['res.users'].create({'name': 'Create engineer', 'login': 'create_engineer', 'password': 'create_engineer',
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('create_engineer', 'create_engineer')
        self.assertFalse(self.rpc('/abroj/app/data', {})['can_create_project'])
        self.assertIn('error', self.rpc('/abroj/app/project/options', {}))
        self.assertIn('error', self.rpc('/abroj/app/project/create', {'name': 'Denied', 'customer_name': 'Must not exist'}))
        self.assertFalse(self.env['res.partner'].search([('name', '=', 'Must not exist')]))

    def test_login_redirect(self):
        response = self.url_open('/abroj/app', allow_redirects=False)
        self.assertIn('/web/login', response.headers['Location'])
        self.assertIn('/abroj/app', unquote(response.headers['Location']))

    def test_pwa_cache_policy(self):
        response = self.url_open('/abroj/app/sw.js')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertIn('/web/', response.text)
        self.assertIn("request.mode === 'navigate'", response.text)
        self.assertIn("url.pathname !== '/abroj/app'", response.text)
        self.assertIn('ASSETS.includes(url.pathname)', response.text)
        self.assertIn("request.method !== 'GET'", response.text)
        self.assertIn("includes('json')", response.text)
        self.assertIn('self.skipWaiting()', response.text)
        self.assertIn('self.clients.claim()', response.text)
        self.assertIn('caches.delete(key)', response.text)
        self.assertIn('fetch(request).catch(', response.text)
        self.authenticate('admin', 'admin')
        self.assertIn('no-store', self.url_open('/abroj/app').headers['Cache-Control'])
        self.assertIn('no-cache', self.url_open('/abroj/app/manifest.webmanifest').headers['Cache-Control'])

    def test_pwa_asset_versions_match(self):
        self.authenticate('admin', 'admin')
        page = self.url_open('/abroj/app').text
        worker = self.url_open('/abroj/app/sw.js').text
        version = re.search(r"const VERSION = '([0-9a-f]{12})'", worker).group(1)
        self.assertNotIn('ASSET_VERSION_PLACEHOLDER', page)
        self.assertNotIn('ASSET_VERSION_PLACEHOLDER', worker)
        assets = re.findall(r'(?:src|href)="(/abroj_project_dashboard/static/pwa/[^"]+)"', page)
        self.assertTrue(assets)
        for asset in assets:
            self.assertTrue(asset.endswith('?v=' + version), asset)
        for icon in self.url_open('/abroj/app/manifest.webmanifest').json()['icons']:
            self.assertTrue(icon['src'].endswith('?v=' + version))
        self.assertIn("'abroj-v32-' + VERSION", worker)
        self.assertIn("cache: 'reload'", worker)
        self.assertIn("url.searchParams.get('v') !== VERSION", worker)
        self.assertNotIn('static/pwa/index.html', worker)

    def test_brand_assets_and_manifest(self):
        manifest = self.url_open('/abroj/app/manifest.webmanifest').json()
        icons = manifest['icons']
        self.assertEqual({icon['sizes'] for icon in icons}, {'192x192', '512x512'})
        self.assertTrue(any(icon.get('purpose') == 'maskable' for icon in icons))
        for icon in icons:
            response = self.url_open(icon['src'])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content[:8], b'\x89PNG\r\n\x1a\n')
        worker = self.url_open('/abroj/app/sw.js').text
        for asset in ('js/screens.js', 'css/tokens.css', 'logo-white.png'):
            self.assertIn(asset, worker)

    def test_unauthenticated_json_session_expired(self):
        response = self.url_open('/abroj/app/data', data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': {}, 'id': 1}), headers={'Content-Type': 'application/json'})
        self.assertEqual(response.json()['error']['code'], 100)

    def test_dashboard_json(self):
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/data', {'filters': {'search': 'no such project'}})
        self.assertEqual(result['projects'], [])
        self.assertTrue(result['types'])
        user = self.env.ref('base.user_admin')
        self.assertEqual(result['current_user']['id'], user.id)
        self.assertEqual(result['current_user']['name'], user.name)
        self.assertEqual(result['current_user']['email'], user.email or '')
        self.assertEqual(result['current_user']['phone'], user.phone or '')
        self.assertIn('job_title', result['current_user'])

    def test_language_preference(self):
        self.authenticate('admin', 'admin')
        self.assertTrue(self.rpc('/abroj/app/language', {'lang': 'en'})['ok'])
        self.env.user.invalidate_recordset(['lang'])
        self.assertEqual(self.env.ref('base.user_admin').lang, 'en_US')
        self.assertIn('name="user-lang" content="en"', self.url_open('/abroj/app').text)

    def test_language_switch_translates_dashboard_and_errors(self):
        self.env['res.lang']._activate_lang('ar_001')
        project = self.env['project.project'].create({
            'name': 'Language fixture', 'company_id': self.env.company.id,
            'abroj_type': 'residential', 'last_update_status': 'on_track',
        })
        self.authenticate('admin', 'admin')
        self.assertTrue(self.rpc('/abroj/app/language', {'lang': 'ar'})['server_synced'])
        self.env.ref('base.user_admin').invalidate_recordset(['lang'])
        self.assertEqual(self.env.ref('base.user_admin').lang, 'ar_001')
        arabic = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertEqual(arabic['type_label'], 'سكني / فلل')
        self.assertTrue(self.rpc('/abroj/app/language', {'lang': 'en'})['ok'])
        english = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertEqual(english['type_label'], 'Residential / villas')
        self.assertEqual(english['status_label'], 'On track')
        self.assertEqual(self.rpc('/abroj/app/save', {'model': 'invalid', 'values': {}})['error'],
                         'Could not save. Check your permissions and input.')

    def test_language_unavailable_falls_back_to_ui(self):
        self.env['res.lang'].search([('code', '=like', 'ar%')]).write({'active': False})
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/language', {'lang': 'ar'})
        self.assertEqual(result, {'ok': True, 'server_synced': False, 'ui_lang': 'ar'})
        self.assertEqual(self.rpc('/abroj/app/language', {'lang': 'invalid'}),
                         {'ok': True, 'server_synced': False, 'ui_lang': 'en'})

    def test_language_maps_to_active_arabic(self):
        self.env['res.lang'].search([('code', '=like', 'ar%')]).write({'active': False})
        self.env['res.lang']._activate_lang('ar_SY')
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/language', {'lang': 'ar'})
        self.assertEqual(result, {'ok': True, 'server_synced': True, 'ui_lang': 'ar'})
        admin = self.env.ref('base.user_admin')
        admin.invalidate_recordset(['lang'])
        self.assertEqual(admin.lang, 'ar_SY')

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

    def test_media_original_bytes_and_audio_mimes(self):
        import re
        project = self.env['project.project'].create({'name': 'Media quality', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        original = bytes(range(256)) * 4097
        for name, mime in [('original.jpg', 'image/jpeg'), ('voice.webm', 'audio/webm;codecs=opus'), ('voice.mp4', 'audio/mp4')]:
            response = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id)}, files={'file': (name, original, mime)})
            attachment = self.env['ir.attachment'].browse(response.json()['id'])
            self.assertEqual(attachment.raw, original)
            self.assertEqual(self.url_open('/web/content/%s' % attachment.id).content, original)
        too_large = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id)}, files={'file': ('large.bin', b'x' * (25 * 1024 * 1024 + 1), 'application/octet-stream')})
        self.assertIn('error', too_large.json())
        for name, mime in [('voice.webm', 'audio/webm;codecs=opus'), ('voice.mp4', 'audio/mp4')]:
            response = self.url_open('/abroj/app/voice', data={'csrf_token': token, 'project_id': str(project.id), 'body': 'Voice'}, files={'file': (name, original, mime)})
            self.assertIn('id', response.json())

    def test_upload_rejects_mismatched_owner(self):
        import re
        project = self.env['project.project'].create({'name': 'Owner mismatch', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        response = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id), 'owner_uid': str(self.env.ref('base.user_admin').id + 99999)}, files={'file': ('mismatch.jpg', b'photo', 'image/jpeg')})
        self.assertEqual(response.status_code, 403)
        self.assertIn('error', response.json())
        self.assertFalse(self.env['ir.attachment'].search([('res_model', '=', 'project.project'), ('res_id', '=', project.id), ('name', '=', 'mismatch.jpg')]))

    def test_camera_caption_and_translations(self):
        import re
        project = self.env['project.project'].create({'name': 'Captioned photo', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        original = b'original photo bytes\x00\xff'
        response = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id), 'description': 'Site progress'}, files={'file': ('photo.jpg', original, 'image/jpeg')})
        attachment = self.env['ir.attachment'].browse(response.json()['id'])
        self.assertEqual(attachment.raw, original)
        self.assertEqual(attachment.description, 'Site progress')
        source = (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js' / 'i18n.js').read_text(encoding='utf-8')
        for key in ('choosePhotos', 'photoPreview', 'addPhoto', 'caption', 'zoom'):
            self.assertRegex(source, rf"{key}:\['[^']+','[^']+'\]")

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

    def test_invoice_upload_requires_invoicing_rights(self):
        import re
        user = self.env['res.users'].create({'name': 'Invoice denied', 'login': 'invoice_denied', 'password': 'invoice_denied',
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_manager').id])]})
        project = self.env['project.project'].create({'name': 'Invoice denied fixture', 'company_id': self.env.company.id, 'user_id': user.id})
        self.authenticate('invoice_denied', 'invoice_denied')
        self.assertFalse(self.rpc('/abroj/app/data', {})['can_create_invoice'])
        detail = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertTrue(detail['can_write'])
        self.assertFalse(detail['can_create_invoice'])
        source = (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js' / 'screens.js').read_text(encoding='utf-8')
        self.assertIn('currentProject.can_write&&currentProject.can_create_invoice?`<button onclick="closeDrawer();invoiceChoice()"', source)
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        response = self.url_open('/abroj/app/invoice', data={'csrf_token': token, 'project_id': str(project.id)}, files={'file': ('invoice.pdf', b'invoice bytes', 'application/pdf')})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'You do not have permission to create vendor bills.')

    def test_invoice_upload_creates_draft_and_inbox(self):
        import re
        project = self.env['project.project'].create({'name': 'Invoice fixture', 'company_id': self.env.company.id})
        self.env['res.users'].create({'name': 'Invoice owner', 'login': 'invoice_owner', 'password': 'invoice_owner',
            'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_manager').id, self.env.ref('account.group_account_invoice').id])]})
        self.authenticate('invoice_owner', 'invoice_owner')
        self.assertTrue(self.rpc('/abroj/app/data', {})['can_create_invoice'])
        self.assertTrue(self.rpc('/abroj/app/data', {'project_id': project.id})['can_create_invoice'])
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        response = self.url_open('/abroj/app/invoice', data={'csrf_token': token, 'project_id': str(project.id)}, files={'file': ('invoice.pdf', b'invoice bytes', 'application/pdf')})
        result = response.json()
        self.assertEqual(response.status_code, 200, result)
        bill = self.env['account.move'].browse(result['id'])
        self.assertEqual((bill.move_type, bill.state, result['extraction']), ('in_invoice', 'draft', 'pending'))
        self.assertIn(str(project.id), bill.ref)
        invoice_attachment = self.env['ir.attachment'].search([('res_model', '=', 'account.move'), ('res_id', '=', bill.id)])
        self.assertEqual(invoice_attachment.raw, b'invoice bytes')
        self.assertTrue(invoice_attachment.abroj_is_invoice)
        inbox = self.env['abroj.contracting.inbox'].search([('abroj_invoice_bill_id', '=', bill.id)])
        self.assertEqual((inbox.project_id.id, inbox.state), (project.id, 'pending'))
        inbox_attachment = self.env['ir.attachment'].search([('res_model', '=', inbox._name), ('res_id', '=', inbox.id), ('res_field', '=', 'file')])
        self.assertTrue(inbox_attachment)
        self.assertFalse(inbox.project_note_ids)
        doc = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id)}, files={'file': ('site.jpg', b'photo', 'image/jpeg')}).json()['id']
        flagged = self.env['ir.attachment'].create({'name': 'flagged.pdf', 'datas': 'eA==', 'res_model': 'project.project', 'res_id': project.id, 'abroj_is_invoice': True})
        legacy = self.env['ir.attachment'].create({'name': 'invoice.pdf', 'raw': b'invoice bytes', 'res_model': 'project.project', 'res_id': project.id})
        task = self.env['project.task'].create({'name': 'Documentation task', 'project_id': project.id})
        task_doc = self.env['ir.attachment'].create({'name': 'invoice.pdf', 'raw': b'invoice bytes', 'res_model': 'project.task', 'res_id': task.id})
        result = self.rpc('/abroj/app/library', {'project_id': project.id})
        ids = {item['id'] for item in result}
        self.assertIn(doc, ids)
        self.assertIn(task_doc.id, ids)
        self.assertTrue(ids.isdisjoint(set(invoice_attachment.ids + inbox_attachment.ids + flagged.ids + legacy.ids)))

    def test_project_library_includes_task_files(self):
        project = self.env['project.project'].create({'name': 'Library', 'company_id': self.env.company.id})
        task = self.env['project.task'].create({'name': 'Phase', 'project_id': project.id})
        other = self.env['project.project'].create({'name': 'Other', 'company_id': self.env.company.id})
        attachments = self.env['ir.attachment'].create([{'name': name, 'type': 'binary', 'datas': 'eA==', 'res_model': model, 'res_id': record} for name, model, record in [('site.jpg', 'project.project', project.id), ('phase.pdf', 'project.task', task.id), ('other.jpg', 'project.project', other.id)]])
        self.authenticate('admin', 'admin')
        result = self.rpc('/abroj/app/library', {'project_id': project.id})
        ids = {item['id'] for item in result}
        self.assertTrue(set(attachments[:2].ids).issubset(ids))
        self.assertNotIn(attachments[2].id, ids)

    def test_document_upload_does_not_create_invoice_inbox(self):
        import re
        project = self.env['project.project'].create({'name': 'Documentation', 'company_id': self.env.company.id})
        self.authenticate('admin', 'admin')
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        response = self.url_open('/abroj/app/upload', data={'csrf_token': token, 'model': 'project.project', 'record_id': str(project.id)}, files={'file': ('wall.jpg', b'photo', 'image/jpeg')})
        self.assertIn('id', response.json())
        self.assertFalse(self.env['abroj.contracting.inbox'].search([('project_id', '=', project.id)]))
        self.assertFalse(self.env['account.move'].search([('ref', 'like', 'ID %s)' % project.id)]))

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
        self.assertFalse(detail['can_close'])
        self.assertIn('error', self.rpc('/abroj/app/project/close-summary', {'project_id': project.id}))
        self.assertIn('error', self.rpc('/abroj/app/project/set-closed', {'project_id': project.id, 'closed': True}))
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

    def test_documents_create_and_workflow(self):
        partner = self.env['res.partner'].create({'name': 'Document partner'})
        project = self.env['project.project'].create({'name': 'Documents HTTP', 'company_id': self.env.company.id, 'partner_id': partner.id})
        self.authenticate('admin', 'admin')
        def save(kind, values):
            result = self.rpc('/abroj/app/document/save', {'project_id': project.id, 'kind': kind, 'values': values})
            self.assertIn('id', result, result)
            return result['id']
        contract = save('contract', {'partner_id': partner.id, 'agreed_amount': 100})
        for kind in ('payment', 'receipt'):
            voucher = save(kind, {'partner_id': partner.id, 'amount': 10, **({'subcontractor_id': contract} if kind == 'payment' else {})})
            docs = self.rpc('/abroj/app/documents', {'project_id': project.id})
            self.assertEqual(docs['records'][kind][0]['name'], '')
            result = self.rpc('/abroj/app/document/action', {'project_id': project.id, 'kind': kind, 'record_id': voucher, 'action': 'issue'})
            self.assertTrue(result.get('ok'), result)
        save('note', {'body': 'Test note'})
        save('invoice', {'number': 'INV', 'subcontractor_id': contract, 'amount': 10})
        save('cost', {'name': 'Cost', 'amount': 10})
        note = save('promissory', {'partner_id': partner.id, 'amount': 25, 'issue_date': '2026-01-01', 'due_date': '2026-02-01'})
        self.assertTrue(self.rpc('/abroj/app/document/action', {'project_id': project.id, 'kind': 'promissory', 'record_id': note, 'action': 'issue'}).get('ok'))
        docs = self.rpc('/abroj/app/documents', {'project_id': project.id})
        self.assertEqual(docs['records']['promissory'][0]['state'], 'issued')
        self.assertNotIn('error', docs)

    def test_promissory_engineer_restriction(self):
        project = self.env['project.project'].create({'name': 'Promissory HTTP', 'company_id': self.env.company.id, 'privacy_visibility': 'employees'})
        partner = self.env['res.partner'].create({'name': 'Promissory partner'})
        self.env['res.users'].create({'name': 'Promissory engineer', 'login': 'promissory_engineer', 'password': 'promissory_engineer', 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('promissory_engineer', 'promissory_engineer')
        result = self.rpc('/abroj/app/document/save', {'project_id': project.id, 'kind': 'promissory', 'values': {'partner_id': partner.id, 'amount': 10, 'due_date': '2027-01-01'}})
        self.assertIn('id', result)
        action = self.rpc('/abroj/app/document/action', {'project_id': project.id, 'kind': 'promissory', 'record_id': result['id'], 'action': 'issue'})
        self.assertIn('error', action)

    def test_voice_and_pdf_access(self):
        from unittest.mock import patch
        import re
        partner = self.env['res.partner'].create({'name': 'PDF partner'})
        project = self.env['project.project'].create({'name': 'PDF project', 'company_id': self.env.company.id, 'privacy_visibility': 'employees'})
        note = self.env['abroj.promissory.note'].create({'project_id': project.id, 'partner_id': partner.id, 'amount': 10, 'due_date': '2027-01-01'})
        self.authenticate('admin', 'admin')
        token = re.search(r'name="csrf-token" content="([^"]+)', self.url_open('/abroj/app').text).group(1)
        voice = self.url_open('/abroj/app/voice', data={'csrf_token': token, 'project_id': str(project.id), 'body': 'Voice'}, files={'file': ('voice.webm', b'voice bytes', 'audio/webm')})
        self.assertIn('id', voice.json())
        report_class = type(self.env['ir.actions.report'])
        with patch.object(report_class, '_render_qweb_pdf', return_value=(b'%PDF-1.4\n', 'pdf')):
            response = self.url_open('/abroj/app/pdf/promissory/%d' % note.id)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content.startswith(b'%PDF'))
        from odoo.exceptions import AccessError, UserError
        with patch.object(report_class, '_render_qweb_pdf', side_effect=UserError('wkhtmltopdf failed')):
            response = self.url_open('/abroj/app/pdf/promissory/%d' % note.id)
            self.assertEqual(response.status_code, 500)
            self.assertIn('wkhtmltopdf failed', response.text)
        with patch.object(report_class, '_render_qweb_pdf', side_effect=AccessError('denied')):
            response = self.url_open('/abroj/app/pdf/promissory/%d' % note.id)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('denied', response.text)
        private = self.env['project.project'].create({'name': 'Private PDF', 'company_id': self.env.company.id, 'privacy_visibility': 'followers'})
        hidden = self.env['abroj.promissory.note'].create({'project_id': private.id, 'partner_id': partner.id, 'amount': 10, 'due_date': '2027-01-01'})
        self.env['res.users'].create({'name': 'PDF engineer', 'login': 'pdf_engineer', 'password': 'pdf_engineer', 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('pdf_engineer', 'pdf_engineer')
        self.assertEqual(self.url_open('/abroj/app/pdf/promissory/%d' % hidden.id).status_code, 403)
