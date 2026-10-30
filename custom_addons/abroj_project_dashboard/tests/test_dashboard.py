import json
from pathlib import Path
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

    def test_pwa_has_no_native_dialogs(self):
        js_dir = Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js'
        for path in js_dir.glob('*.js'):
            source = path.read_text(encoding='utf-8')
            self.assertNotIn('alert(', source, path.name)
            self.assertNotIn('confirm(', source, path.name)

    def test_voice_gesture_translations(self):
        source = (Path(__file__).resolve().parents[1] / 'static' / 'pwa' / 'js' / 'i18n.js').read_text(encoding='utf-8')
        self.assertIn("holdRecord:['اضغط مطوّلاً للتسجيل','Press and hold to record']", source)
        self.assertIn("slideCancel:['اسحب للإلغاء','Slide to cancel']", source)

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
        phase(public, 'Past', self.today - timedelta(days=2))
        phase(public, 'Future', self.today + timedelta(days=1))
        hidden = phase(private, 'Hidden', self.today)
        groups = self.env['project.project'].get_abroj_my_day()
        by_project = {g['id']: {p['id'] for p in g['phases']} for g in groups}
        self.assertEqual(by_project[public.id], {spanning.id, due.id})
        self.assertIn(other.id, by_project[self.project.id])
        self.assertIn(hidden.id, by_project[private.id])
        visible = self.env['project.project'].with_user(self.engineer).get_abroj_my_day()
        self.assertNotIn(private.id, {g['id'] for g in visible})
        self.assertEqual({p['id'] for g in visible if g['id'] == public.id for p in g['phases']}, {spanning.id, due.id})

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
        self.assertTrue(self.rpc('/abroj/app/language', {'lang': 'ar'})['ok'])
        arabic = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertEqual(arabic['type_label'], 'سكني / فلل')
        self.assertTrue(self.rpc('/abroj/app/language', {'lang': 'en'})['ok'])
        english = self.rpc('/abroj/app/data', {'project_id': project.id})
        self.assertEqual(english['type_label'], 'Residential / villas')
        self.assertEqual(english['status_label'], 'On track')
        self.assertEqual(self.rpc('/abroj/app/save', {'model': 'invalid', 'values': {}})['error'],
                         'Could not save. Check your permissions and input.')

    def test_language_rejects_unknown_code(self):
        self.authenticate('admin', 'admin')
        self.assertFalse(self.rpc('/abroj/app/language', {'lang': 'invalid'})['ok'])

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
        private = self.env['project.project'].create({'name': 'Private PDF', 'company_id': self.env.company.id, 'privacy_visibility': 'followers'})
        hidden = self.env['abroj.promissory.note'].create({'project_id': private.id, 'partner_id': partner.id, 'amount': 10, 'due_date': '2027-01-01'})
        self.env['res.users'].create({'name': 'PDF engineer', 'login': 'pdf_engineer', 'password': 'pdf_engineer', 'group_ids': [Command.set([self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id])]})
        self.authenticate('pdf_engineer', 'pdf_engineer')
        self.assertEqual(self.url_open('/abroj/app/pdf/promissory/%d' % hidden.id).status_code, 403)
