"""Server-authoritative batch editing for heat-calendar targets.

The dashboard submits explicit company-local month/weekday cells.  This
service deliberately has no table and accepts no company id: the active Odoo
company is the only authority for every read and write.
"""

import hashlib
import json

from psycopg2 import IntegrityError

from odoo import _, api, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .occasion import HEAT_CALENDAR_MANAGER_GROUP


class HeatCalendarTargetBatch(models.AbstractModel):
    _name = 'baseer.heat.calendar.target.batch'
    _description = 'Heat calendar target batch service'

    @api.model
    def _is_manager(self):
        return (self.env.user.has_group('base.group_system')
                or self.env.user.has_group(HEAT_CALENDAR_MANAGER_GROUP))

    @api.model
    def _check_manager_and_company(self):
        if not self._is_manager():
            raise AccessError(_('Only a heat calendar manager can set targets.'))
        company = self.env.company
        if company.id not in self.env.companies.ids:
            raise AccessError(_('Choose a company available in the current session.'))
        return company

    @api.model
    def _validate_year(self, year):
        if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
            raise ValidationError(_('Choose a valid calendar year for this target.'))
        return year

    @api.model
    def _canonical_amount(self, value):
        amount = self.env['baseer.heat.calendar.target']._validate_target_amount(value)
        return amount, format(amount, '.2f')

    @api.model
    def _load_targets(self, company, year):
        """Read the complete exact-target snapshot, including inactive rows."""
        Target = self.env['baseer.heat.calendar.target'].with_context(active_test=False)
        targets = Target.search([
            ('company_id', '=', company.id),
            ('year', '=', year),
        ])
        by_scope = {}
        snapshot = []
        for target in targets.sorted(lambda record: (record.month, record.weekday, record.id)):
            scope = (target.month, target.weekday)
            # The database constraint is the durable overlap authority.  This
            # defensive check prevents an ambiguous legacy database from being
            # silently represented as a safe batch matrix.
            if scope in by_scope:
                raise ValidationError(_('Only one target is allowed for this scope.'))
            _amount, amount_text = self._canonical_amount(target.target_amount)
            by_scope[scope] = target
            snapshot.append({
                'id': target.id,
                'month': target.month,
                'weekday': target.weekday,
                'target_amount': amount_text,
                'active': bool(target.active),
                # Odoo keeps write_date in UTC.  Format it explicitly so the
                # optimistic-lock token is locale-independent and retains
                # sub-second precision when PostgreSQL provides it.
                'write_date': (
                    target.write_date.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
                    if target.write_date else False
                ),
            })
        digest_input = json.dumps({
            'company_id': company.id,
            'year': year,
            'targets': snapshot,
        }, sort_keys=True, separators=(',', ':')).encode()
        return by_scope, hashlib.sha256(digest_input).hexdigest()

    @api.model
    def _matrix_payload(self, company, year):
        targets, version = self._load_targets(company, year)
        cells = []
        for month in range(1, 13):
            for weekday in range(7):
                target = targets.get((month, weekday))
                cells.append({
                    'month': month,
                    'weekday': weekday,
                    'configured': bool(target),
                    'target_amount': float(target.target_amount) if target else False,
                    'active': bool(target.active) if target else False,
                })
        return {
            'company': {
                'id': company.id,
                'name': company.display_name,
                'currency': company.currency_id.name,
            },
            'company_id': company.id,
            'year': year,
            'currency_id': company.currency_id.id,
            'cells': cells,
            'version': version,
        }

    @api.model
    def get_target_batch(self, year):
        """Return all 84 exact scopes and a snapshot version for this company."""
        company = self._check_manager_and_company()
        year = self._validate_year(year)
        return self._matrix_payload(company, year)

    @api.model
    def _validate_entries(self, entries):
        """Normalize the full request before acquiring a write lock or writing."""
        if not isinstance(entries, list) or not 1 <= len(entries) <= 84:
            raise ValidationError(_('Choose from one to 84 exact target cells.'))
        normalized = []
        scopes = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValidationError(_('Each target cell must include its month, weekday, amount, and status.'))
            month = entry.get('month')
            weekday = entry.get('weekday')
            active = entry.get('active')
            if (isinstance(month, bool) or not isinstance(month, int) or not 1 <= month <= 12
                    or isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6):
                raise ValidationError(_('Choose one exact calendar month and weekday for every target cell.'))
            if not isinstance(active, bool):
                raise ValidationError(_('Each target cell must state whether it is active.'))
            if 'target_amount' not in entry:
                raise ValidationError(_('Each target cell needs a target amount, including inactive cells.'))
            amount, _amount_text = self._canonical_amount(entry['target_amount'])
            scope = (month, weekday)
            if scope in scopes:
                raise ValidationError(_('A target scope can appear only once in one batch.'))
            scopes.add(scope)
            normalized.append({
                'month': month,
                'weekday': weekday,
                'target_amount': float(amount),
                'active': active,
            })
        return normalized

    @api.model
    def _lock_scope(self, company, year):
        """Serialize batch writers for one company/year without table locks."""
        self.env['baseer.heat.calendar.target']._lock_target_scopes([
            (company.id, year),
        ])

    @api.model
    def _create_or_update_exact_target(self, target, company, year, entry):
        """Keep the unique persistent scope as the final race authority."""
        Target = self.env['baseer.heat.calendar.target']
        values = {
            'company_id': company.id,
            'year': year,
            'month': entry['month'],
            'weekday': entry['weekday'],
            'target_amount': entry['target_amount'],
            'active': entry['active'],
        }
        if target:
            existing_amount, _existing_amount_text = self._canonical_amount(target.target_amount)
            requested_amount, _requested_amount_text = self._canonical_amount(
                entry['target_amount']
            )
            # An idempotent replay must not touch write_date.  The snapshot
            # version includes that field, so an unnecessary ORM write would
            # make a manager's own unchanged retry appear stale.
            if (existing_amount == requested_amount
                    and bool(target.active) == entry['active']):
                return
            target.write(values)
            return
        try:
            with self.env.cr.savepoint():
                Target.create(values)
            return
        except IntegrityError:
            # The batch lock coordinates this service.  This fallback also
            # handles a concurrent legacy single-target wizard safely.
            target = Target.with_context(active_test=False).search([
                ('company_id', '=', company.id),
                ('year', '=', year),
                ('month', '=', entry['month']),
                ('weekday', '=', entry['weekday']),
            ], limit=1)
            if not target:
                raise
            target.write(values)

    @api.model
    def apply_target_batch(self, year, entries, version):
        """Atomically update explicitly submitted exact scopes for this company.

        A client never writes its own company, does not create wildcard rules,
        and cannot overwrite a newer matrix because the complete persisted
        snapshot is checked inside the company/year transaction lock.
        """
        company = self._check_manager_and_company()
        year = self._validate_year(year)
        if not isinstance(version, str) or not version:
            raise ValidationError(_('Refresh the targets before saving changes.'))
        normalized_entries = self._validate_entries(entries)

        Target = self.env['baseer.heat.calendar.target']
        Target.check_access('read')
        Target.check_access('create')
        Target.check_access('write')
        self._lock_scope(company, year)
        existing, current_version = self._load_targets(company, year)
        if version != current_version:
            raise UserError(_('Targets changed in another session. Refresh required before saving.'))

        # The RPC transaction is normally atomic already.  This savepoint is
        # intentional: callers that catch an Odoo exception still cannot keep
        # a partial subset of this batch.
        with self.env.cr.savepoint():
            for entry in normalized_entries:
                self._create_or_update_exact_target(
                    existing.get((entry['month'], entry['weekday'])), company, year, entry,
                )
        return self._matrix_payload(company, year)
