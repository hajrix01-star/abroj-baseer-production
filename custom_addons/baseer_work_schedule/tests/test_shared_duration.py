from datetime import datetime, time, timedelta

import pytz

from odoo import Command, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.addons.baseer_work_schedule.models.schedule import _TOKEN


@tagged('post_install', '-at_install')
class TestSharedDurationSchedule(TransactionCase):
    """The shared schedule must not mix employees or public holidays across companies."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a, cls.company_b = cls.env['res.company'].create([
            {'name': 'Shared schedule test A'}, {'name': 'Shared schedule test B'},
        ])
        # Calendar comparisons require a consistent real-world time zone.
        for company in (cls.company_a, cls.company_b):
            company.resource_calendar_id.tz = 'Asia/Riyadh'
            cls.env.ref('baseer_payroll.work_schedule_60_company_%s' % company.id).tz = 'Asia/Riyadh'
        cls.today = fields.Date.context_today(cls.env.user)
        cls.future = (cls.today.replace(day=1) + timedelta(days=32)).replace(day=1)

    def _environment_for(self, company):
        return self.env(context=dict(self.env.context, allowed_company_ids=[company.id],
                                     tracking_disable=True))

    def _create_shared(self, company):
        env = self._environment_for(company)
        wizard = env['baseer.schedule.wizard'].create({
            'name': 'Shared 10 hours / 7 days', 'company_id': company.id,
            'shared_ten_hour': True,
        })
        wizard.action_apply()
        return wizard.applied_calendar_id

    def _employee(self, company):
        env = self._environment_for(company)
        employee = env['hr.employee'].create({'name': 'Shared schedule employee', 'company_id': company.id})
        old_calendar = env.ref('baseer_payroll.work_schedule_60_company_%s' % company.id)
        employee.version_id.write({
            'resource_calendar_id': old_calendar.id, 'wage': 5000,
            'baseer_salary_mode': 'inclusive', 'baseer_allowance_total': 0,
            'baseer_work_days': 26,
        })
        return employee

    def _assign(self, employee, calendar, date):
        env = self._environment_for(employee.company_id)
        wizard = env['baseer.schedule.wizard'].create({
            'name': calendar.name, 'company_id': employee.company_id.id,
            'employee_id': employee.id, 'source_calendar_id': calendar.id,
            'effective_date': date,
        })
        wizard.action_apply()
        return wizard

    def test_shared_calendar_is_one_record_and_has_duration_per_day(self):
        calendar = self._create_shared(self.company_a)
        self.assertEqual(calendar, self._create_shared(self.company_b))
        self.assertFalse(calendar.company_id)
        self.assertTrue(calendar.baseer_shared_duration)
        self.assertTrue(calendar.duration_based)
        self.assertEqual(calendar.tz, 'Asia/Riyadh')
        self.assertEqual(calendar.hours_per_day, 10)
        self.assertEqual(calendar.hours_per_week, 70)
        self.assertEqual(set(calendar.attendance_ids.mapped('dayofweek')), set(map(str, range(7))))
        self.assertTrue(all(row.duration_hours == 10 and row.day_period == 'full_day'
                            for row in calendar.attendance_ids))
        for company in (self.company_a, self.company_b):
            self.assertIn(calendar.id, self._environment_for(company)['resource.calendar'].search([
                ('id', '=', calendar.id)]).ids)

    def test_assignment_preserves_old_version_and_payroll(self):
        calendar = self._create_shared(self.company_a)
        for company in (self.company_a, self.company_b):
            employee = self._employee(company)
            old = employee.version_id
            signature = old.sudo()._baseer_schedule_payroll_signature()
            self._assign(employee, calendar, self.future)
            version = employee._get_version(self.future)
            self.assertEqual(version.resource_calendar_id.id, calendar.id)
            self.assertEqual(version.sudo()._baseer_schedule_payroll_signature(), signature)
            self.assertEqual(old.wage, 5000)
            self.assertNotEqual(old.resource_calendar_id.id, calendar.id)

    def test_historical_application_is_rejected(self):
        calendar = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        old_schedule = employee.version_id.resource_calendar_id
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(employee, calendar, self.today - timedelta(days=1))
        self.assertEqual(employee.version_id.resource_calendar_id, old_schedule)

    def test_direct_version_creation_cannot_assign_shared_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a).with_context(lang='en_US')
        original_versions = set(employee.version_ids.ids)
        model = self._environment_for(self.company_a)['hr.version'].with_context(lang='en_US')
        message = 'Assign or change shared schedules through Set working times'
        values = {'employee_id': employee.id, 'date_version': self.future,
                  'resource_calendar_id': shared.id}
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            model.create(values)
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            model.with_context(default_resource_calendar_id=shared.id).create({
                'employee_id': employee.id, 'date_version': self.future,
            })
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            employee.create_version({'date_version': self.future, 'resource_calendar_id': shared.id})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            employee.create_version({'date_version': self.today - timedelta(days=1),
                                     'resource_calendar_id': shared.id})
        employee.invalidate_recordset(['version_ids'])
        self.assertEqual(set(employee.version_ids.ids), original_versions)

    def test_direct_version_edits_cannot_enter_or_leave_shared_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a).with_context(lang='en_US')
        original = employee.version_id
        old_calendar = original.resource_calendar_id
        message = 'Assign or change shared schedules through Set working times'
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            original.write({'resource_calendar_id': shared.id})
        self.assertEqual(original.resource_calendar_id, old_calendar)
        # A trusted wizard remains the only successful path and preserves history.
        self._assign(employee, shared, self.future)
        shared_version = employee._get_version(self.future).with_context(lang='en_US')
        self.assertEqual(shared_version.resource_calendar_id.id, shared.id)
        self.assertEqual(original.resource_calendar_id, old_calendar)
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            original.write({'resource_calendar_id': shared.id})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            shared_version.write({'resource_calendar_id': old_calendar.id})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            shared_version.write({'date_version': self.future + timedelta(days=1)})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            employee.write({'resource_calendar_id': shared.id})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            employee.create_version({'date_version': self.future + timedelta(days=15),
                                     'resource_calendar_id': old_calendar.id})
        shared_version.write({'resource_calendar_id': shared.id, 'date_version': self.future})
        # A genuine future salary revision can inherit the same employee's
        # already-effective schedule without changing schedule membership.
        salary_version = employee.create_version({
            'date_version': self.future + timedelta(days=30), 'wage': 5100,
        })
        self.assertEqual(salary_version.resource_calendar_id.id, shared.id)
        self.assertEqual(salary_version.wage, 5100)
        self.assertEqual(shared_version.wage, 5000)
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            (shared_version | salary_version).unlink()
        self.assertTrue(shared_version.exists())
        self.assertTrue(salary_version.exists())
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            shared_version.unlink()
        self.assertTrue(shared_version.exists())
        salary_version.unlink()
        self.assertFalse(salary_version.exists())
        self.assertEqual(employee._get_version(self.future + timedelta(days=30)).id, shared_version.id)
        shared_version.write({'name': 'Allowed non-schedule update'})
        self.assertEqual(shared_version.name, 'Allowed non-schedule update')
        self.assertEqual(original.resource_calendar_id, old_calendar)
        self.assertEqual(shared_version.resource_calendar_id.id, shared.id)

    def test_salary_version_can_start_today_when_already_on_shared_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a).with_context(lang='en_US')
        initial = employee.version_id
        initial.date_version = self.today - timedelta(days=60)
        # Test-only fixture of an earlier authorized assignment, without
        # changing any production data or bypassing the tested public API.
        employee.with_context(_baseer_schedule_change=_TOKEN).create_version({
            'date_version': self.today - timedelta(days=30),
            'resource_calendar_id': shared.id,
        })
        earlier = employee._get_version(self.today - timedelta(days=1))
        self.assertEqual(earlier.resource_calendar_id.id, shared.id)
        new_version = employee.create_version({'date_version': self.today, 'wage': 5100})
        self.assertEqual(new_version.resource_calendar_id.id, shared.id)
        self.assertEqual(new_version.wage, 5100)
        self.assertEqual(earlier.wage, 5000)

    def test_employee_can_end_contract_and_be_archived_on_shared_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        employee.version_id.write({'contract_date_start': self.today - timedelta(days=60)})
        self._assign(employee, shared, self.today)
        version = employee.version_id
        end = self.today + timedelta(days=30)
        version.write({'contract_date_end': end})
        self.assertEqual(version.contract_date_end, end)
        employee.with_context(no_wizard=True).action_archive()
        self.assertFalse(employee.active)
        self.assertEqual(version.resource_calendar_id.id, shared.id)
        employee.with_context(active_test=False).action_unarchive()
        self.assertTrue(employee.active)
        self.assertEqual(employee.version_id.resource_calendar_id.id, shared.id)
        self.assertEqual(employee.version_id.wage, 5000)

    def test_contract_start_cannot_move_shared_schedule_into_past(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a).with_context(lang='en_US')
        self._assign(employee, shared, self.today)
        version = employee.version_id
        previous_date = version.date_version
        previous_start = version.contract_date_start
        message = 'Assign or change shared schedules through Set working times'
        # Odoo's unique-version contract sync also writes date_version, so a
        # changed start must not silently backdate the shared schedule.
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            version.write({'contract_date_start': self.today - timedelta(days=60)})
        self.assertEqual(version.date_version, previous_date)
        self.assertEqual(version.contract_date_start, previous_start)
        self.assertEqual(version.resource_calendar_id.id, shared.id)

    def test_non_shared_version_cannot_displace_shared_schedule_by_membership_edit(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a).with_context(lang='en_US')
        original = employee.version_id
        original_date = original.date_version
        # A pre-existing inactive non-shared future version can otherwise
        # displace the new shared schedule if it is reactivated.
        inactive = employee.create_version({'date_version': self.future + timedelta(days=15)})
        inactive.write({'active': False})
        self._assign(employee, shared, self.future)
        shared_version = employee._get_version(self.future)
        other_employee = self._employee(self.company_b).with_context(lang='en_US')
        other_version = other_employee.version_id
        other_version.date_version = self.future + timedelta(days=20)
        message = 'Assign or change shared schedules through Set working times'
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            original.write({'date_version': self.future + timedelta(days=1)})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            inactive.write({'active': True})
        with self.assertRaisesRegex(ValidationError, message), self.cr.savepoint():
            other_version.write({'employee_id': employee.id})
        self.assertEqual(original.date_version, original_date)
        self.assertFalse(inactive.active)
        self.assertEqual(other_version.employee_id, other_employee)
        self.assertEqual(employee._get_version(self.future).id, shared_version.id)

    def test_non_shared_calendar_change_before_shared_start_is_allowed(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        original = employee.version_id.resource_calendar_id
        day_before_shared = self.today + timedelta(days=1)
        shared_start = (self.future if self.future > day_before_shared else
                        (self.future + timedelta(days=32)).replace(day=1))
        previous_version = employee.create_version({'date_version': day_before_shared})
        replacement = original.copy({'name': 'Other non-shared 10-hour calendar'})
        self._assign(employee, shared, shared_start)
        shared_version = employee._get_version(shared_start)
        previous_version.write({'resource_calendar_id': replacement.id})
        self.assertEqual(previous_version.resource_calendar_id, replacement)
        self.assertEqual(employee._get_version(shared_start).id, shared_version.id)
        self.assertEqual(shared_version.resource_calendar_id.id, shared.id)

    def test_assignment_rejects_holidays_unique_to_employee_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        original = employee.version_id.resource_calendar_id
        original_versions = set(employee.version_ids.ids)
        day = self.future + timedelta(days=10)
        start = datetime.combine(day, time.min)
        self._environment_for(self.company_a)['resource.calendar.leaves'].create({
            'name': 'Only on employee previous calendar', 'calendar_id': original.id,
            'date_from': start, 'date_to': start + timedelta(hours=23),
        })
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self._assign(employee, shared, self.future)
        employee.invalidate_recordset(['version_ids'])
        self.assertEqual(set(employee.version_ids.ids), original_versions)
        self.assertEqual(employee._get_version(self.future).resource_calendar_id, original)

    def test_assignment_allows_calendar_holiday_covered_by_company_calendar(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        original = employee.version_id.resource_calendar_id
        day = self.future + timedelta(days=10)
        start = datetime.combine(day, time.min)
        values = {'date_from': start, 'date_to': start + timedelta(hours=23)}
        leaves = self._environment_for(self.company_a)['resource.calendar.leaves']
        leaves.create(dict(values, name='Previous schedule holiday', calendar_id=original.id))
        leaves.create(dict(values, name='Company holiday with another name',
                           calendar_id=self.company_a.resource_calendar_id.id))
        self._assign(employee, shared, self.future)
        self.assertEqual(employee._get_version(self.future).resource_calendar_id.id, shared.id)
        self.assertEqual(employee.version_id.resource_calendar_id, original)

    def test_approved_leave_is_preserved_when_change_starts_later(self):
        shared = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        initial = self.env['resource.calendar'].create({
            'name': 'Existing 10-hour seven-day schedule', 'company_id': self.company_a.id,
            'tz': 'Asia/Riyadh', 'schedule_type': 'fully_fixed', 'duration_based': True,
            'attendance_ids': [Command.clear()] + [Command.create({
                'name': '10 hours', 'dayofweek': str(day), 'day_period': 'full_day',
                'duration_hours': 10, 'sequence': day,
            }) for day in range(7)],
        })
        employee.version_id.resource_calendar_id = initial
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Annual test', 'requires_allocation': False,
            'leave_validation_type': 'no_validation',
            'include_public_holidays_in_duration': True,
        })
        start = self.today + timedelta(days=1)
        end = start + timedelta(days=35)
        leave = self._environment_for(self.company_a)['hr.leave'].create({
            'employee_id': employee.id, 'holiday_status_id': leave_type.id,
            'request_date_from': start, 'request_date_to': end,
        })
        self.assertEqual(leave.state, 'validate')
        self.assertEqual(leave.number_of_days, 36)
        signature = employee.version_id.sudo()._baseer_schedule_payroll_signature()
        effective = (end.replace(day=1) + timedelta(days=32)).replace(day=1)
        self._assign(employee, shared, effective)
        self.assertEqual(employee._get_version(effective).resource_calendar_id.id, shared.id)
        leave.invalidate_recordset()
        self.assertEqual((leave.state, leave.number_of_days), ('validate', 36))
        self.assertEqual(employee._get_version(effective).sudo()._baseer_schedule_payroll_signature(), signature)

    def test_non_manager_cannot_create_shared_calendar(self):
        calendar = self._create_shared(self.company_a)
        employee = self._employee(self.company_a)
        old_schedule = employee.version_id.resource_calendar_id
        user = self.env['res.users'].create({
            'name': 'Shared schedule restricted', 'login': 'shared-schedule-restricted',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, self.company_a.ids)],
            'group_ids': [(6, 0, self.env.ref('base.group_user').ids)],
        })
        wizard_model = self._environment_for(self.company_a)['baseer.schedule.wizard'].with_user(user)
        with self.assertRaises(AccessError), self.cr.savepoint():
            wizard = wizard_model.create({'name': 'No access', 'company_id': self.company_a.id,
                                          'shared_ten_hour': True})
            wizard.action_apply()
        with self.assertRaises(AccessError), self.cr.savepoint():
            wizard = wizard_model.create({
                'name': calendar.name, 'company_id': self.company_a.id,
                'employee_id': employee.id, 'source_calendar_id': calendar.id,
                'effective_date': self.future,
            })
            wizard.action_apply()
        self.assertEqual(employee.version_id.resource_calendar_id, old_schedule)

    def test_manager_of_one_company_cannot_assign_other_company_employee(self):
        calendar = self._create_shared(self.company_a)
        employee_b = self._employee(self.company_b)
        original = employee_b.version_id.resource_calendar_id
        user = self.env['res.users'].create({
            'name': 'Schedule manager only A', 'login': 'schedule-manager-only-a',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, self.company_a.ids)],
            'group_ids': [(6, 0, self.env.ref('hr.group_hr_manager').ids)],
        })
        model = self._environment_for(self.company_a)['baseer.schedule.wizard'].with_user(user)
        for requested_company in (self.company_a, self.company_b):
            with self.assertRaises(AccessError), self.cr.savepoint():
                wizard = model.create({
                    'name': calendar.name, 'company_id': requested_company.id,
                    'employee_id': employee_b.id, 'source_calendar_id': calendar.id,
                    'effective_date': self.future,
                })
                wizard.action_apply()
        self.assertEqual(employee_b.version_id.resource_calendar_id, original)

    def test_company_manager_can_create_and_assign_shared_schedule_without_sudo(self):
        employee = self._employee(self.company_a)
        manager = self.env['res.users'].create({
            'name': 'Shared schedule manager A', 'login': 'shared-schedule-manager-a',
            'company_id': self.company_a.id, 'company_ids': [(6, 0, self.company_a.ids)],
            'group_ids': [(6, 0, self.env.ref('hr.group_hr_manager').ids)],
        })
        wizard_model = self._environment_for(self.company_a)['baseer.schedule.wizard'].with_user(manager)
        self.assertFalse(wizard_model.env.su)
        creator = wizard_model.create({
            'name': 'Shared 10 hours / 7 days', 'company_id': self.company_a.id,
            'shared_ten_hour': True,
        })
        creator.action_apply()
        shared = creator.applied_calendar_id
        self.assertTrue(shared)
        self.assertFalse(shared.company_id)
        wizard = wizard_model.create({
            'name': shared.name, 'company_id': self.company_a.id,
            'employee_id': employee.id, 'source_calendar_id': shared.id,
            'effective_date': self.future,
        })
        wizard.action_apply()
        self.assertEqual(employee._get_version(self.future).resource_calendar_id.id, shared.id)

    def test_two_company_manager_sees_same_shared_schedule_in_both_contexts(self):
        # Only the first manager creates the shared record; the second user
        # exercises ordinary company-specific views and ACLs for that same ID.
        shared = self._create_shared(self.company_a)
        manager = self.env['res.users'].create({
            'name': 'Shared schedule manager AB', 'login': 'shared-schedule-manager-ab',
            'company_id': self.company_a.id,
            'company_ids': [(6, 0, (self.company_a | self.company_b).ids)],
            'group_ids': [(6, 0, (self.env.ref('hr.group_hr_manager') |
                                  self.env.ref('base.group_multi_company')).ids)],
        })
        for company in (self.company_a, self.company_b):
            env = self._environment_for(company)
            model = env['resource.calendar'].with_user(manager)
            self.assertFalse(model.env.su)
            visible = model.search([('id', '=', shared.id), '|',
                                    ('company_id', '=', False), ('company_id', '=', company.id)])
            self.assertEqual(visible.ids, shared.ids)
            wizard = env['baseer.schedule.wizard'].with_user(manager).create({
                'name': shared.name, 'company_id': company.id,
                'shared_ten_hour': True,
            })
            wizard.action_apply()
            self.assertEqual(wizard.applied_calendar_id.id, shared.id)

    def test_global_holiday_does_not_leak_between_companies(self):
        calendar = self._create_shared(self.company_a)
        employees = [self._employee(company) for company in (self.company_a, self.company_b)]
        start = datetime.combine(self.future, time.min).replace(tzinfo=pytz.utc)
        stop = start + timedelta(days=1)
        holiday = self._environment_for(self.company_a)['resource.calendar.leaves'].create({
            'name': 'Holiday only in A', 'company_id': self.company_a.id,
            'calendar_id': False, 'date_from': start.replace(tzinfo=None),
            'date_to': stop.replace(tzinfo=None),
        })
        # Odoo computes company_id from calendar or env.company; explicit input
        # alone is not sufficient when the holiday has no specific calendar.
        self.assertEqual(holiday.company_id, self.company_a)
        self.assertFalse(holiday.calendar_id)
        self.assertEqual(employees[0].resource_id.company_id, self.company_a)
        self.assertEqual(employees[1].resource_id.company_id, self.company_b)
        intervals = calendar.with_context(allowed_company_ids=[self.company_a.id, self.company_b.id])._leave_intervals_batch(
            start, stop, resources=employees[0].resource_id | employees[1].resource_id)
        self.assertTrue(intervals[employees[0].resource_id.id])
        self.assertFalse(intervals[employees[1].resource_id.id])

    def test_global_holidays_cannot_be_attached_or_edited_on_shared_calendar(self):
        shared = self._create_shared(self.company_a)
        leaves = self._environment_for(self.company_a)['resource.calendar.leaves']
        start = datetime.combine(self.future, time.min)
        values = {'name': 'Public holiday fixture', 'calendar_id': shared.id,
                  'date_from': start, 'date_to': start + timedelta(hours=23),
                  'resource_id': False}
        with self.assertRaises(ValidationError), self.cr.savepoint():
            leaves.create(values)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            shared.write({'global_leave_ids': [Command.create({
                'name': 'Public holiday through calendar', 'date_from': start,
                'date_to': start + timedelta(hours=23),
            })]})
        company_leave = leaves.create(dict(values, calendar_id=self.company_a.resource_calendar_id.id))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            company_leave.write({'calendar_id': shared.id})
        self.assertEqual(company_leave.calendar_id, self.company_a.resource_calendar_id)
        # A legacy invalid public holiday can exist from older versions. The
        # internal token creates that fixture only in this rollback test.
        legacy = leaves.with_context(_baseer_schedule_change=_TOKEN).create(values).with_context(
            _baseer_schedule_change=False)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            legacy.write({'name': 'Changed public holiday'})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            legacy.unlink()
        self.assertTrue(legacy.exists())

    def test_leave_days_respect_company_holiday_with_one_or_two_companies_selected(self):
        calendar = self._create_shared(self.company_a)
        employees = [self._employee(company) for company in (self.company_a, self.company_b)]
        for employee in employees:
            self._assign(employee, calendar, self.today)
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Company holiday test', 'company_id': False,
            'requires_allocation': False, 'leave_validation_type': 'no_validation',
            'include_public_holidays_in_duration': False,
        })
        local_tz = pytz.timezone('Asia/Riyadh')
        for both_companies, offset in ((False, 10), (True, 20)):
            start_date = self.today + timedelta(days=offset)
            holiday_date = start_date + timedelta(days=1)
            local_start = local_tz.localize(datetime.combine(holiday_date, time.min))
            local_end = local_tz.localize(datetime.combine(holiday_date, time.max.replace(microsecond=0)))
            holiday = self._environment_for(self.company_a)['resource.calendar.leaves'].create({
                'name': 'Holiday in A only', 'calendar_id': False,
                'date_from': local_start.astimezone(pytz.utc).replace(tzinfo=None),
                'date_to': local_end.astimezone(pytz.utc).replace(tzinfo=None),
            })
            self.assertEqual(holiday.company_id, self.company_a)
            for employee, expected in zip(employees, (2, 3)):
                company = employee.company_id
                other = self.company_b if company == self.company_a else self.company_a
                company_ids = [company.id, other.id] if both_companies else [company.id]
                env = self.env(context=dict(self.env.context, allowed_company_ids=company_ids,
                                            tracking_disable=True))
                leave = env['hr.leave'].create({
                    'employee_id': employee.id, 'holiday_status_id': leave_type.id,
                    'request_date_from': start_date,
                    'request_date_to': start_date + timedelta(days=2),
                })
                self.assertEqual(leave.state, 'validate')
                self.assertEqual(leave.number_of_days, expected,
                                 'Incorrect holiday effect for company %s (both selected: %s)' %
                                 (company.name, both_companies))

    def test_leave_days_respect_holiday_on_company_calendar(self):
        shared = self._create_shared(self.company_a)
        employees = [self._employee(company) for company in (self.company_a, self.company_b)]
        for employee in employees:
            self._assign(employee, shared, self.today)
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Company calendar holiday test', 'company_id': False,
            'requires_allocation': False, 'leave_validation_type': 'no_validation',
            'include_public_holidays_in_duration': False,
        })
        start_date = self.today + timedelta(days=10)
        holiday_date = start_date + timedelta(days=1)
        zone = pytz.timezone('Asia/Riyadh')
        local_start = zone.localize(datetime.combine(holiday_date, time.min))
        local_end = zone.localize(datetime.combine(holiday_date, time.max.replace(microsecond=0)))
        holiday = self._environment_for(self.company_a)['resource.calendar.leaves'].create({
            'name': 'Holiday on A calendar', 'calendar_id': self.company_a.resource_calendar_id.id,
            'date_from': local_start.astimezone(pytz.utc).replace(tzinfo=None),
            'date_to': local_end.astimezone(pytz.utc).replace(tzinfo=None),
        })
        self.assertEqual(holiday.company_id, self.company_a)
        self.assertEqual(holiday.calendar_id, self.company_a.resource_calendar_id)
        for employee, expected in zip(employees, (2, 3)):
            env = self._environment_for(employee.company_id)
            leave = env['hr.leave'].create({
                'employee_id': employee.id, 'holiday_status_id': leave_type.id,
                'request_date_from': start_date,
                'request_date_to': start_date + timedelta(days=2),
            })
            self.assertEqual(leave.state, 'validate')
            self.assertEqual(leave.number_of_days, expected,
                             'Incorrect company-calendar holiday effect for %s' % employee.company_id.name)

    def test_overlapping_holidays_and_include_holidays_option(self):
        shared = self._create_shared(self.company_a)
        employees = [self._employee(company) for company in (self.company_a, self.company_b)]
        for employee in employees:
            self._assign(employee, shared, self.today)
        zone = pytz.timezone('Asia/Riyadh')
        for include, offset in ((False, 10), (True, 20)):
            start_date = self.today + timedelta(days=offset)
            holiday_date = start_date + timedelta(days=1)
            local_start = zone.localize(datetime.combine(holiday_date, time.min))
            local_end = zone.localize(datetime.combine(holiday_date, time.max.replace(microsecond=0)))
            values = {
                'name': 'Company holiday overlap',
                'date_from': local_start.astimezone(pytz.utc).replace(tzinfo=None),
                'date_to': local_end.astimezone(pytz.utc).replace(tzinfo=None),
            }
            leaves = self._environment_for(self.company_a)['resource.calendar.leaves']
            first = leaves.create(dict(values, calendar_id=self.company_a.resource_calendar_id.id))
            self.assertEqual(first.company_id, self.company_a)
            # Native Odoo rejects overlapping public holidays for a company;
            # retain that protection and use the one existing holiday below.
            with self.assertRaises(ValidationError), self.cr.savepoint():
                leaves.create(dict(values, calendar_id=False))
            leave_type = self.env['hr.leave.type'].create({
                'name': 'Overlap holiday test %s' % include, 'company_id': False,
                'requires_allocation': False, 'leave_validation_type': 'no_validation',
                'include_public_holidays_in_duration': include,
            })
            for employee, expected in zip(employees, ((3 if include else 2), 3)):
                leave = self._environment_for(employee.company_id)['hr.leave'].create({
                    'employee_id': employee.id, 'holiday_status_id': leave_type.id,
                    'request_date_from': start_date,
                    'request_date_to': start_date + timedelta(days=2),
                })
                self.assertEqual(leave.number_of_days, expected)
