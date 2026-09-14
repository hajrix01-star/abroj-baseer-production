from datetime import date
from uuid import uuid4

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


OFFICIAL_HOLIDAYS_SOURCE = 'https://www.hrsd.gov.sa/en/knowledge-centre/articles/322'
HEAT_CALENDAR_MANAGER_GROUP = 'baseer_sales_heat_calendar.group_heat_calendar_manager'
SOURCE_KEY_CONTEXT = '_baseer_heat_calendar_source_key_token'
SOURCE_KEY_TOKEN = object()
MANUAL_SOURCE_KEY_PREFIX = 'MANUAL:'
SAUDI_SOURCE_KEY_PREFIX = 'SAUDI:'


class OfficialOccasion(models.Model):
    _name = 'baseer.official.occasion'
    _description = 'Official occasion for sales analysis'
    _order = 'date_from, date_to, id'

    name = fields.Char(required=True, translate=True)
    name_en = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True, copy=False)
    source_key = fields.Char(
        required=True,
        index=True,
        copy=False,
        readonly=True,
        default=lambda self: self._new_manual_source_key(),
    )
    date_from = fields.Date(required=True, index=True)
    date_to = fields.Date(required=True, index=True)
    occasion_type = fields.Selection([
        ('official_holiday', 'Official holiday'),
        ('national_occasion', 'National occasion'),
        ('commercial_season', 'Commercial season'),
    ], required=True, default='official_holiday')
    status = fields.Selection([
        ('estimated', 'Estimated'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], required=True, default='estimated')
    company_ids = fields.Many2many('res.company', string='Companies', help='Leave empty for all companies.')
    source_label = fields.Char(required=True)
    source_url = fields.Char()
    reviewed_on = fields.Date()
    active = fields.Boolean(default=True)

    _source_key_unique = models.Constraint(
        'unique(source_key)', 'The source key must be unique.'
    )

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for record in self:
            if record.date_from and record.date_to and record.date_from > record.date_to:
                raise ValidationError(_('The occasion end date must not be before its start date.'))

    @api.constrains('source_key')
    def _check_source_key(self):
        for record in self:
            if not record.source_key or not record.source_key.strip():
                raise ValidationError(_('A non-empty source key is required.'))

    @api.model
    def _new_manual_source_key(self):
        """Keep user-created rows outside the reserved Saudi replay namespace."""
        return f'{MANUAL_SOURCE_KEY_PREFIX}{uuid4()}'

    @api.model
    def _is_saudi_feed_context(self):
        return self.env.context.get(SOURCE_KEY_CONTEXT) is SOURCE_KEY_TOKEN

    @api.model_create_multi
    def create(self, values_list):
        is_saudi_feed = self._is_saudi_feed_context()
        prepared_values = []
        for values in values_list:
            values = dict(values)
            if is_saudi_feed:
                source_key = values.get('source_key')
                if not isinstance(source_key, str) or not source_key.strip().startswith(SAUDI_SOURCE_KEY_PREFIX):
                    raise ValidationError(_('Only the Saudi occasion feed can define a source key.'))
                values['source_key'] = source_key.strip()
            else:
                # Never accept a browser/RPC-supplied key.  In particular, a
                # manually added record cannot accidentally block SAUDI: replay.
                values['source_key'] = self._new_manual_source_key()
            prepared_values.append(values)
        return super().create(prepared_values)

    def write(self, values):
        if 'source_key' in values:
            raise AccessError(_('The source key is managed by the server.'))
        return super().write(values)

    @api.model
    def _heat_calendar_manager(self):
        return (self.env.user.has_group('base.group_system')
                or self.env.user.has_group(HEAT_CALENDAR_MANAGER_GROUP))

    @api.model
    def _seed_if_missing(self, values):
        """Create one immutable seed record, safely treating a race as a skip.

        Refeeding must never overwrite a manager's date, status or source.
        The unique source key is both the replay identity and the database
        concurrency guard.
        """
        source_key = values['source_key']
        if self._source_key_exists_internally(source_key):
            return False
        try:
            with self.env.cr.savepoint():
                self.with_context(**{SOURCE_KEY_CONTEXT: SOURCE_KEY_TOKEN}).create(values)
            return True
        except IntegrityError:
            # A concurrent feed won.  Do not mutate the record it created.
            if self._source_key_exists_internally(source_key):
                return False
            raise

    @api.model
    def _source_key_exists_internally(self, source_key):
        """Existence-only replay probe, including archived or inaccessible rows.

        The sudo lookup is deliberately confined to a boolean.  It prevents a
        hidden/archived record from causing a duplicate-key exception, while
        never returning its id, name, company, or any other field to the caller.
        """
        return bool(self.sudo().with_context(active_test=False).search_count(
            [('source_key', '=', source_key)], limit=1,
        ))

    @api.model
    def action_seed_saudi_fixed_holidays(self):
        """Idempotently seed fixed holidays and visibly estimated Eid ranges.

        The Eid records are normal, reviewable occasion records rather than
        implicit dates.  A manager replaces their dates/status/source whenever
        an official announcement is published.  This action has no HR,
        calendar, payroll or sales side effects.
        """
        if not self._heat_calendar_manager():
            raise AccessError(_('Only a heat calendar manager can feed official occasions.'))
        self.check_access('create')
        created = skipped = 0
        templates = (
            ('FOUNDING_DAY', 'يوم التأسيس', 'Founding Day', 2, 22),
            ('NATIONAL_DAY', 'اليوم الوطني', 'National Day', 9, 23),
        )
        for year in range(2025, 2031):
            for code, name, name_en, month, day in templates:
                key = f'SAUDI:{code}:{year}'
                values = {
                    'name': name,
                    'name_en': name_en,
                    'code': code,
                    'date_from': date(year, month, day),
                    'date_to': date(year, month, day),
                    'occasion_type': 'official_holiday',
                    'status': 'confirmed',
                    'source_label': _('Saudi official public holidays policy'),
                    'source_url': OFFICIAL_HOLIDAYS_SOURCE,
                    'reviewed_on': fields.Date.context_today(self),
                    'active': True,
                }
                if self._seed_if_missing(dict(values, source_key=key)):
                    created += 1
                else:
                    skipped += 1
        # These are deliberately labelled estimated.  The four-day ranges
        # reflect the HRSD holiday policy; a manager must replace them with
        # the announced dates and a source link when official confirmation is
        # published.  Keeping the estimate as a normal record makes the later
        # correction auditable and prevents a future date from being presented
        # as a legal confirmation.
        estimated_eids = (
            ('EID_FITR', 'إجازة عيد الفطر', 'Eid al-Fitr holiday', {
                2025: (date(2025, 3, 30), date(2025, 4, 2)),
                2026: (date(2026, 3, 19), date(2026, 3, 22)),
                2027: (date(2027, 3, 9), date(2027, 3, 12)),
                2028: (date(2028, 2, 25), date(2028, 2, 28)),
                2029: (date(2029, 2, 13), date(2029, 2, 16)),
                2030: (date(2030, 2, 3), date(2030, 2, 6)),
            }),
            ('EID_ADHA', 'إجازة عيد الأضحى', 'Eid al-Adha holiday', {
                2025: (date(2025, 6, 5), date(2025, 6, 8)),
                2026: (date(2026, 5, 26), date(2026, 5, 29)),
                2027: (date(2027, 5, 15), date(2027, 5, 18)),
                2028: (date(2028, 5, 4), date(2028, 5, 7)),
                2029: (date(2029, 4, 23), date(2029, 4, 26)),
                2030: (date(2030, 4, 13), date(2030, 4, 16)),
            }),
        )
        for code, name, name_en, ranges in estimated_eids:
            for year, (date_from, date_to) in ranges.items():
                key = f'SAUDI:{code}:ESTIMATE:{year}'
                values = {
                    'name': name,
                    'name_en': name_en,
                    'code': code,
                    'date_from': date_from,
                    'date_to': date_to,
                    'occasion_type': 'official_holiday',
                    'status': 'estimated',
                    'source_label': _('Preliminary manual estimate — review before use'),
                    'source_url': False,
                    'reviewed_on': fields.Date.context_today(self),
                    'active': True,
                }
                if self._seed_if_missing(dict(values, source_key=key)):
                    created += 1
                else:
                    skipped += 1
        return {'created': created, 'skipped': skipped}
