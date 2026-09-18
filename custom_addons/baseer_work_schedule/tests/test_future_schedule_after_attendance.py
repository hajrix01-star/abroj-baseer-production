from datetime import datetime, time, timedelta

from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class FutureScheduleAfterAttendanceCase(TransactionCase):

    def _employee(self):
        return self.env['hr.employee'].create({
            'name': 'Schedule history %s' % self._testMethodName,
            'company_id': self.env.company.id,
        })

    def _wizard(self, employee, effective_date):
        days = self.env['baseer.schedule.day'].search([('weekday', 'in', [0, 1, 2, 3, 6])])
        return self.env['baseer.schedule.wizard'].create({
            'name': 'Future schedule %s' % self._testMethodName,
            'company_id': employee.company_id.id,
            'employee_id': employee.id,
            'effective_date': effective_date,
            'day_ids': [Command.set(days.ids)],
            'period_ids': [Command.create({'time_from': '09:00', 'time_to': '17:00'})],
        })

    def _attendance(self, employee, day):
        self.env['hr.attendance'].create({
            'employee_id': employee.id,
            'check_in': datetime.combine(day, time(9, 0)),
            'check_out': datetime.combine(day, time(17, 0)),
        })

    def test_future_schedule_allows_past_attendance(self):
        employee = self._employee()
        today = fields.Date.context_today(self.env.user)
        effective_date = today + timedelta(days=7)
        self._attendance(employee, today - timedelta(days=1))
        wizard = self._wizard(employee, effective_date)
        wizard.action_apply()
        self.assertTrue(employee.version_ids.filtered(lambda version: version.date_version == effective_date))

    def test_future_schedule_still_blocks_attendance_in_affected_period(self):
        employee = self._employee()
        today = fields.Date.context_today(self.env.user)
        effective_date = today + timedelta(days=7)
        self._attendance(employee, effective_date + timedelta(days=1))
        wizard = self._wizard(employee, effective_date)
        with self.assertRaises(ValidationError):
            wizard.action_apply()
