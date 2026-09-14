from datetime import date, timedelta
from unittest.mock import patch
from uuid import uuid4

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.baseer_sales_heat_calendar.models.occasion import (
    SAUDI_SOURCE_KEY_PREFIX,
    SOURCE_KEY_CONTEXT,
    SOURCE_KEY_TOKEN,
)


class HeatCalendarCase(TransactionCase):
    """Acceptance coverage for the G2 company and replay contracts."""

    def setUp(self):
        super().setUp()
        self.company_a = self.env.company
        self.company_b = self.env['res.company'].create({
            'name': 'HC isolated company B',
            'currency_id': self.company_a.currency_id.id,
        })
        self.pos_group = self.env.ref('point_of_sale.group_pos_user')
        self.manager_group = self.env.ref(
            'baseer_sales_heat_calendar.group_heat_calendar_manager'
        )
        self.system_group = self.env.ref('base.group_system')
        self.base_user_group = self.env.ref('base.group_user')
        self.Occasion = self.env['baseer.official.occasion']
        self.Target = self.env['baseer.heat.calendar.target']
        self.TargetBatch = self.env['baseer.heat.calendar.target.batch']
        self.TargetWizard = self.env['baseer.heat.calendar.target.wizard']
        self.pos_user = self._user('HC POS reader', [self.pos_group])
        self.manager_user = self._user(
            'HC calendar manager', [self.pos_group, self.manager_group]
        )
        self.system_user = self._user(
            'HC system manager', [self.pos_group, self.system_group]
        )
        self.dashboard = self.env['spreadsheet.dashboard'].sudo().create({
            'name': 'HC test dashboard',
            'dashboard_group_id': self.env.ref(
                'spreadsheet_dashboard.spreadsheet_dashboard_group_sales'
            ).id,
            'baseer_dashboard_kind': 'sales_heat_calendar',
            'is_published': True,
            'group_ids': [Command.set([self.pos_group.id])],
            'company_ids': [Command.set([self.company_a.id])],
        })

    def _user(self, name, groups):
        return self.env['res.users'].sudo().with_context(
            no_reset_password=True,
        ).create({
            'name': name,
            'login': name.lower().replace(' ', '_'),
            'email': f"{name.lower().replace(' ', '.')}@example.test",
            'company_id': self.company_a.id,
            'company_ids': [Command.set([self.company_a.id])],
            'group_ids': [Command.set([
                self.base_user_group.id,
                *(group.id for group in groups),
            ])],
        })

    def _occasion_values(self, *, company=None, name='HC test occasion'):
        values = {
            'name': name,
            'name_en': name,
            'code': 'HC_TEST',
            'date_from': date(2026, 9, 1),
            'date_to': date(2026, 9, 1),
            'occasion_type': 'official_holiday',
            'status': 'confirmed',
            'source_label': 'HC test source',
        }
        if company:
            values['company_ids'] = [Command.set([company.id])]
        return values

    def _target_values(self, company, *, weekday=1):
        return {
            'company_id': company.id,
            'year': 2026,
            'month': 9,
            'weekday': weekday,
            'target_amount': 100,
        }

    def _aggregate_rows(self, date_from, date_to):
        rows = []
        cursor = date_from
        while cursor <= date_to:
            status = 'missing'
            sales = customers = 0
            if cursor == date(2026, 9, 1):
                status, sales, customers = 'complete', 100, 4
            elif cursor == date(2026, 9, 8):
                status, sales, customers = 'incomplete', 900, 40
            elif cursor == date(2026, 9, 15):
                status, sales, customers = 'complete', 300, 12
            rows.append({
                'business_date': cursor,
                'status': status,
                'has_sales': bool(sales),
                'sales': sales,
                'customers': customers,
                'summary_ids': [],
                'closure_ids': [],
            })
            cursor += timedelta(days=1)
        return rows

    def _as_user(self, model, user):
        return model.with_user(user).with_context(
            allowed_company_ids=[self.company_a.id],
        )

    def _set_target(self, *, company=None, weekday='3', amount=100, active=True):
        company = company or self.company_a
        wizard = self.TargetWizard.with_user(self.manager_user).with_context(
            allowed_company_ids=[self.company_a.id],
        ).create({
            'company_id': company.id,
            'year': 2026,
            'month': '9',
            'weekday': weekday,
            'target_amount': amount,
            'active': active,
        })
        wizard.action_apply()

    def test_hc_t01_manager_and_system_company_rules_do_not_bypass(self):
        """System CRUD ACLs still have the same company rule as the manager."""
        occasion_b = self.Occasion.sudo().create(
            self._occasion_values(company=self.company_b, name='HC company B occasion')
        )
        target_b = self.Target.sudo().create(self._target_values(self.company_b))

        for user in (self.manager_user, self.system_user):
            with self.subTest(user=user.login, operation='read occasion'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Occasion, user).browse(occasion_b.id).read(['name'])
            with self.subTest(user=user.login, operation='read target'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Target, user).browse(target_b.id).read(['target_amount'])
            with self.subTest(user=user.login, operation='write occasion'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Occasion, user).browse(occasion_b.id).write({'name': 'blocked'})
            with self.subTest(user=user.login, operation='write target'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Target, user).browse(target_b.id).write({'target_amount': 200})
            with self.subTest(user=user.login, operation='create occasion'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Occasion, user).create(self._occasion_values(company=self.company_b))
            with self.subTest(user=user.login, operation='create target'):
                with self.assertRaises(AccessError):
                    self._as_user(self.Target, user).create(
                        self._target_values(self.company_b, weekday=2)
                    )

    def test_hc_t02_pos_reader_uses_aggregate_and_complete_weekday_average_only(self):
        """The monthly header is a backend aggregate of complete source days."""
        aggregate_calls = []

        def aggregate_days(report, company, date_from, date_to):
            aggregate_calls.append((company.id, date_from, date_to))
            return {'days': self._aggregate_rows(date_from, date_to)}

        report_model = type(self.env['baseer.pos.daily.report'])
        def untranslated(message, *args, **kwargs):
            return message % kwargs if kwargs else message

        with patch.object(report_model, '_aggregate_days', new=aggregate_days), patch(
            'odoo.addons.baseer_sales_heat_calendar.models.dashboard._', new=untranslated,
        ):
            payload = self.dashboard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).get_baseer_heat_calendar('2026-09')
            with self.assertRaises(AccessError):
                self.dashboard.with_user(self.pos_user).with_context(
                    allowed_company_ids=[self.company_b.id],
                ).with_company(self.company_b).get_baseer_heat_calendar('2026-09')

        self.assertEqual(aggregate_calls, [
            (self.company_a.id, date(2026, 7, 7), date(2026, 9, 30)),
        ])
        weekday_headers = {header['name']: header for header in payload['weekdays']}
        self.assertEqual(weekday_headers['Tuesday']['average_display'], '200.00')
        self.assertTrue(weekday_headers['Tuesday']['has_average'])
        self.assertFalse(weekday_headers['Monday']['has_average'])

    def test_hc_t03_feed_skips_hidden_archived_source_key_without_disclosure(self):
        """An archived seed key is a safe no-op, never a duplicate-key failure."""
        source_key = f'{SAUDI_SOURCE_KEY_PREFIX}TEST_ARCHIVED:{uuid4()}'
        existing = self.Occasion.sudo().with_context(**{
            SOURCE_KEY_CONTEXT: SOURCE_KEY_TOKEN,
        }).create({
            **self._occasion_values(name='HC archived authoritative occasion'),
            'source_key': source_key,
            'active': False,
        })
        manager_occasions = self._as_user(self.Occasion, self.manager_user)
        self.assertFalse(manager_occasions.search([('source_key', '=', source_key)]))

        created = manager_occasions._seed_if_missing({
            **self._occasion_values(name='must not overwrite archived record'),
            'source_key': source_key,
        })
        self.assertFalse(created)
        hidden = self.Occasion.sudo().with_context(active_test=False).search([
            ('source_key', '=', source_key),
        ])
        self.assertEqual(hidden, existing)
        self.assertEqual(hidden.name, 'HC archived authoritative occasion')

        manual = manager_occasions.create({
            **self._occasion_values(name='HC manual occasion'),
            'source_key': source_key,
        })
        self.assertTrue(manual.source_key.startswith('MANUAL:'))
        self.assertNotEqual(manual.source_key, source_key)

    def test_hc_t04_earliest_iso_month_is_a_safe_calendar_request(self):
        """A valid early ISO month must not underflow the baseline window."""
        report_model = type(self.env['baseer.pos.daily.report'])

        def aggregate_days(_report, _company, date_from, date_to):
            return {'days': self._aggregate_rows(date_from, date_to)}

        def untranslated(message, *args, **kwargs):
            return message % kwargs if kwargs else message

        with patch.object(report_model, '_aggregate_days', new=aggregate_days), patch(
            'odoo.addons.baseer_sales_heat_calendar.models.dashboard._',
            new=untranslated,
        ):
            payload = self.dashboard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).get_baseer_heat_calendar('0001-01')

        self.assertEqual(payload['month'], '0001-01')
        self.assertEqual(len(payload['weekdays']), 7)

    def test_hct_t01_exact_thursday_and_friday_targets_change_heat_not_sales(self):
        """Each named weekday has one independent target and fresh RPC result."""
        def aggregate_days(_report, _company, date_from, date_to):
            rows = self._aggregate_rows(date_from, date_to)
            for row in rows:
                if row['business_date'] == date(2026, 9, 3):  # Thursday
                    row.update(status='complete', has_sales=True, sales=100, customers=4)
                elif row['business_date'] == date(2026, 9, 4):  # Friday
                    row.update(status='complete', has_sales=True, sales=150, customers=6)
            return {'days': rows}

        def untranslated(message, *args, **kwargs):
            return message % kwargs if kwargs else message

        summaries_before = self.env['baseer.pos.summary'].search_count([])
        self._set_target(weekday='3', amount=200)
        self._set_target(weekday='4', amount=100)
        report_model = type(self.env['baseer.pos.daily.report'])
        with patch.object(report_model, '_aggregate_days', new=aggregate_days), patch(
            'odoo.addons.baseer_sales_heat_calendar.models.dashboard._', new=untranslated,
        ):
            payload = self.dashboard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).get_baseer_heat_calendar('2026-09')
            days = {
                day['date']: day
                for week in payload['weeks'] for day in week if day
            }
            self.assertEqual(days['2026-09-03']['basis_kind'], 'target')
            self.assertEqual(days['2026-09-03']['basis_display'], '200.00')
            self.assertEqual(days['2026-09-03']['ratio_display'], '50.0%')
            self.assertEqual(days['2026-09-03']['heat_level'], 'low')
            self.assertEqual(days['2026-09-04']['basis_display'], '100.00')
            self.assertEqual(days['2026-09-04']['ratio_display'], '150.0%')
            self.assertEqual(days['2026-09-04']['heat_level'], 'high')

            # Same exact scope is an upsert, not a duplicate. A fresh calendar
            # read therefore reflects the changed target without touching sales.
            self._set_target(weekday='3', amount=50)
            refreshed = self.dashboard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).get_baseer_heat_calendar('2026-09')
        refreshed_days = {
            day['date']: day
            for week in refreshed['weeks'] for day in week if day
        }
        self.assertEqual(refreshed_days['2026-09-03']['basis_display'], '50.00')
        self.assertEqual(refreshed_days['2026-09-03']['ratio_display'], '200.0%')
        self.assertEqual(refreshed_days['2026-09-03']['heat_level'], 'high')
        for weekday in (3, 4):
            self.assertEqual(self.Target.with_context(active_test=False).search_count([
                ('company_id', '=', self.company_a.id), ('year', '=', 2026),
                ('month', '=', 9), ('weekday', '=', weekday),
            ]), 1)
        self.assertEqual(self.env['baseer.pos.summary'].search_count([]), summaries_before)

    def test_hct_t02_target_scope_is_exact_unique_and_company_isolated(self):
        """Wildcards and duplicates cannot create overlapping day targets."""
        values = self._target_values(self.company_a, weekday=3)
        self.Target.sudo().create(values)
        with self.env.cr.savepoint(), self.assertRaises(IntegrityError):
            self.Target.sudo().create(values)
        for invalid in (
            {'year': 0}, {'month': 0}, {'weekday': -1},
            {'target_amount': float('nan')},
            {'target_amount': float('inf')},
            {'target_amount': float('-inf')},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                self.Target.sudo().create({**self._target_values(self.company_a, weekday=4), **invalid})

        with self.assertRaises(AccessError):
            self.TargetWizard.with_user(self.manager_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).create({
                'company_id': self.company_b.id,
                'year': 2026,
                'month': '9',
                'weekday': '3',
                'target_amount': 100,
            })

    def test_hct_t03_existing_named_scope_loads_before_manager_edits_it(self):
        """Changing a selected weekday never starts from a misleading zero."""
        self._set_target(weekday='3', amount=275, active=False)
        wizard = self.TargetWizard.with_user(self.manager_user).with_context(
            allowed_company_ids=[self.company_a.id],
        ).create({
            'company_id': self.company_a.id,
            'year': 2026,
            'month': '9',
            'weekday': '3',
            'target_amount': 1,
            'active': True,
        })
        wizard._onchange_scope()
        self.assertEqual(wizard.target_amount, 275)
        self.assertFalse(wizard.active)
        arabic_wizard = wizard.with_context(lang='ar_001')
        arabic_wizard._compute_scope_message()
        self.assertIn('الخميس', arabic_wizard.scope_message)
        self.assertIn('سبتمبر', arabic_wizard.scope_message)
        english_wizard = wizard.with_context(lang='en_US')
        english_wizard._compute_scope_message()
        self.assertIn('Thursday', english_wizard.scope_message)
        self.assertIn('September', english_wizard.scope_message)

    def test_hct_t04_pos_cannot_open_or_operate_target_setup(self):
        """The manager-only action and wizard do not become a POS write route."""
        with self.assertRaises(AccessError):
            self.TargetWizard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).default_get(['company_id', 'year', 'month', 'weekday'])
        with self.assertRaises(AccessError):
            self.TargetWizard.with_user(self.pos_user).with_context(
                allowed_company_ids=[self.company_a.id],
            ).create({
                'company_id': self.company_a.id,
                'year': 2026,
                'month': '9',
                'weekday': '3',
                'target_amount': 100,
            })

    def test_hctb_t01_batch_updates_cartesian_scopes_independently_and_idempotently(self):
        """One batch can set several month/day intersections without overlap."""
        Batch = self._as_user(self.TargetBatch, self.manager_user)
        baseline = Batch.get_target_batch(2026)
        self.assertEqual(baseline['company'], {
            'id': self.company_a.id,
            'name': self.company_a.display_name,
            'currency': self.company_a.currency_id.name,
        })
        entries = [
            # JSON-RPC delivers browser monetary inputs as strings.  The
            # backend accepts them only through Decimal validation.
            {'month': 9, 'weekday': 3, 'target_amount': '101.11', 'active': True},
            {'month': 9, 'weekday': 4, 'target_amount': 202.22, 'active': True},
            {'month': 10, 'weekday': 3, 'target_amount': 303.33, 'active': True},
            # An inactive cell keeps its amount for audit and can be enabled
            # later; it is not silently deleted by the batch editor.
            {'month': 10, 'weekday': 4, 'target_amount': 404.44, 'active': False},
        ]
        updated = Batch.apply_target_batch(2026, entries, baseline['version'])
        values = {
            (cell['month'], cell['weekday']): cell
            for cell in updated['cells']
        }
        for entry in entries:
            cell = values[(entry['month'], entry['weekday'])]
            self.assertTrue(cell['configured'])
            self.assertEqual(cell['active'], entry['active'])
            self.assertEqual(cell['target_amount'], float(entry['target_amount']))
            self.assertEqual(self.Target.with_context(active_test=False).search_count([
                ('company_id', '=', self.company_a.id), ('year', '=', 2026),
                ('month', '=', entry['month']), ('weekday', '=', entry['weekday']),
            ]), 1)

        # A replay of the same explicit cells is an update, never four new
        # scopes.  This is the controller contract used by the matrix UI.
        replayed = Batch.apply_target_batch(2026, entries, updated['version'])
        self.assertEqual(replayed['version'], updated['version'])
        self.assertEqual(self.Target.with_context(active_test=False).search_count([
            ('company_id', '=', self.company_a.id), ('year', '=', 2026),
            ('month', 'in', [9, 10]), ('weekday', 'in', [3, 4]),
        ]), 4)

    def test_hctb_t02_batch_validates_all_cells_before_any_write(self):
        """A bad later cell cannot leave an earlier target half-saved."""
        Batch = self._as_user(self.TargetBatch, self.manager_user)
        baseline = Batch.get_target_batch(2026)
        entries = [
            {'month': 9, 'weekday': 3, 'target_amount': 100.00, 'active': True},
            {'month': 9, 'weekday': 4, 'target_amount': 10.001, 'active': True},
        ]
        with self.assertRaises(ValidationError):
            Batch.apply_target_batch(2026, entries, baseline['version'])
        self.assertFalse(self.Target.search_count([
            ('company_id', '=', self.company_a.id), ('year', '=', 2026),
            ('month', '=', 9), ('weekday', 'in', [3, 4]),
        ]))

        for invalid_amount in (float('nan'), float('inf'), float('-inf'), True, 1.001):
            with self.subTest(invalid_amount=invalid_amount), self.assertRaises(ValidationError):
                self.Target.create({
                    **self._target_values(self.company_a, weekday=5),
                    'target_amount': invalid_amount,
                })

    def test_hctb_t03_stale_batch_is_rejected_without_mutation(self):
        """The opaque version blocks an old browser tab from overwriting a target."""
        Batch = self._as_user(self.TargetBatch, self.manager_user)
        stale = Batch.get_target_batch(2026)
        self.Target.with_user(self.manager_user).with_context(
            allowed_company_ids=[self.company_a.id],
        ).create({
            **self._target_values(self.company_a, weekday=3),
            'target_amount': 90,
        })
        with self.assertRaises(UserError):
            Batch.apply_target_batch(2026, [
                {'month': 9, 'weekday': 3, 'target_amount': 999, 'active': True},
            ], stale['version'])
        target = self.Target.search([
            ('company_id', '=', self.company_a.id), ('year', '=', 2026),
            ('month', '=', 9), ('weekday', '=', 3),
        ])
        self.assertEqual(len(target), 1)
        self.assertEqual(target.target_amount, 90)

    def test_hctb_t04_pos_cannot_read_or_apply_batch_and_sales_stay_untouched(self):
        """The batch RPC is manager-only and never writes source sales summaries."""
        pos_batch = self._as_user(self.TargetBatch, self.pos_user)
        with self.assertRaises(AccessError):
            pos_batch.get_target_batch(2026)
        with self.assertRaises(AccessError):
            pos_batch.apply_target_batch(2026, [
                {'month': 9, 'weekday': 3, 'target_amount': 100, 'active': True},
            ], 'not-a-manager-version')

        summaries_before = self.env['baseer.pos.summary'].search_count([])
        Batch = self._as_user(self.TargetBatch, self.manager_user)
        baseline = Batch.get_target_batch(2026)
        Batch.apply_target_batch(2026, [
            {'month': 9, 'weekday': 3, 'target_amount': 100, 'active': False},
        ], baseline['version'])
        self.assertEqual(self.env['baseer.pos.summary'].search_count([]), summaries_before)
