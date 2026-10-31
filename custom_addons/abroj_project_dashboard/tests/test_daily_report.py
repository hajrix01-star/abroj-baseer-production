import json
from datetime import timedelta
from odoo import Command, fields
from odoo.tests import HttpCase, tagged


@tagged('-at_install', 'post_install')
class DailyReportHttpCase(HttpCase):
    def call(self, path, params=None):
        response = self.url_open(path, data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params or {}, 'id': 1}), headers={'Content-Type': 'application/json'})
        return response.json()

    def test_assignments_reports_and_cron(self):
        groups = [self.env.ref('base.group_user').id, self.env.ref('project.group_project_user').id]
        users = self.env['res.users'].create([{'name': name, 'login': login, 'password': login, 'group_ids': [Command.set(groups)]} for name, login in [('First engineer', 'report_first'), ('Second engineer', 'report_second')]])
        projects = self.env['project.project'].create([{'name': 'Scoped first', 'user_id': users[0].id}, {'name': 'Scoped second', 'user_id': users[1].id}])
        tasks = self.env['project.task'].create([{'name': 'First phase', 'project_id': projects[0].id, 'x_abroj_date_start': fields.Date.today() - timedelta(days=3)}, {'name': 'Second phase', 'project_id': projects[1].id, 'x_abroj_date_start': fields.Date.today() - timedelta(days=3)}])
        for i, login in enumerate(('report_first', 'report_second')):
            self.authenticate(login, login)
            result = self.call('/abroj/app/data')['result']
            ids = {p['id'] for p in result['projects']}
            self.assertIn(projects[i].id, ids)
            self.assertNotIn(projects[1-i].id, ids)
            self.assertNotIn(projects[1-i].id, {g['id'] for g in self.call('/abroj/app/my-day')['result']})
            self.assertIn('error', self.call('/abroj/app/data', {'project_id': projects[1-i].id}))
            for path, args in [('/abroj/app/documents', {'project_id': projects[1-i].id}), ('/abroj/app/library', {'project_id': projects[1-i].id}), ('/abroj/app/attachments', {'model': 'project.task', 'record_id': tasks[1-i].id}), ('/abroj/app/note', {'model': 'project.task', 'record_id': tasks[1-i].id, 'body': 'denied'}), ('/abroj/app/save', {'model': 'project.task', 'record_id': tasks[1-i].id, 'values': {'name': 'denied'}})]:
                self.assertIn('error', self.call(path, args).get('result', {}), path)
            self.assertIn('error', self.call('/abroj/app/project/set-manager', {'project_id': projects[i].id, 'manager_id': users[i].id}))
        self.authenticate('report_first', 'report_first')
        report = self.call('/abroj/app/report/generate')['result']
        self.assertEqual(report['state'], 'draft')
        self.assertEqual({line['project_id'] for line in report['lines']}, {projects[0].id})
        line = report['lines'][0]
        self.assertTrue(self.call('/abroj/app/report/edit', {'line_id': line['id'], 'tomorrow_plan': 'Continue'})['result']['ok'])
        self.assertEqual(self.call('/abroj/app/report/approve', {'report_id': report['id']})['result']['state'], 'approved')
        self.env['abroj.daily.report'].cron_auto_send()
        second = self.env['abroj.daily.report'].sudo().search([('engineer_id', '=', users[1].id)], limit=1)
        self.assertEqual(second.state, 'auto_sent')
        self.assertTrue(second.sent_at)
        self.authenticate('admin', 'admin')
        ids = {p['id'] for p in self.call('/abroj/app/data')['result']['projects']}
        self.assertTrue(set(projects.ids).issubset(ids))
        self.assertTrue(self.call('/abroj/app/project/set-manager', {'project_id': projects[0].id, 'manager_id': users[1].id})['result']['ok'])
        self.assertEqual(self.call('/abroj/app/data', {'project_id': projects[0].id})['result']['manager_id'], users[1].id)
