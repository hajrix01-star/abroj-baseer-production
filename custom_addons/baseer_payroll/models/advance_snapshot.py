"""Auditable, read-only employee-advance snapshots for a bounded API route."""
import base64
import binascii
import json
from datetime import datetime, time

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .common import decimal, money


SNAPSHOT_GROUP = 'baseer_payroll.group_advance_snapshot_reader'
PAGE_SIZE = 100


class BaseerLoanSnapshotCompany(models.Model):
    _name = 'baseer.hr.loan.snapshot.company'
    _description = 'Advance Snapshot Company Key'
    _order = 'key'

    key = fields.Char(required=True, index=True)
    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('baseer_advance_snapshot_company_key_unique', 'unique(key)',
         'The advance snapshot company key must be unique.'),
        ('baseer_advance_snapshot_company_unique', 'unique(company_id)',
         'A company can have only one advance snapshot key.'),
    ]

    @api.constrains('key')
    def _check_key(self):
        for record in self:
            if not record.key or record.key != record.key.strip().lower() or not record.key.replace('_', '').isalnum():
                raise ValidationError(_('Use a lowercase company key with letters, numbers, and underscores only.'))


class BaseerLoanSnapshot(models.AbstractModel):
    _name = 'baseer.hr.loan.snapshot'
    _description = 'Employee Advance Snapshot Reader'

    def _require_reader(self):
        if not self.env.user.has_group(SNAPSHOT_GROUP):
            raise AccessError(_('Advance snapshot reader access is required.'))

    @staticmethod
    def _parse_positive_id(value, field_name):
        if value in (None, False, ''):
            return False
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValidationError(_('%s must be a positive integer.') % field_name)
        return value

    @staticmethod
    def _parse_cutoff(value):
        try:
            cutoff = fields.Date.to_date(value)
        except (TypeError, ValueError):
            raise ValidationError(_('Cutoff must be an ISO date.'))
        if not cutoff:
            raise ValidationError(_('Cutoff must be an ISO date.'))
        return cutoff

    @staticmethod
    def _encode_token(payload):
        # This token is only a stable-page cursor, never an authorization credential.
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')

    @staticmethod
    def _decode_token(token):
        if not isinstance(token, str) or len(token) > 512:
            raise ValidationError(_('Invalid snapshot token.'))
        try:
            padded = token + '=' * (-len(token) % 4)
            value = json.loads(base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8'))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
            raise ValidationError(_('Invalid snapshot token.'))
        if not isinstance(value, dict):
            raise ValidationError(_('Invalid snapshot token.'))
        return value

    @staticmethod
    def _company_cutoff_end(company, cutoff):
        timezone = pytz.timezone(company.partner_id.tz or 'Asia/Riyadh')
        local = timezone.localize(datetime.combine(cutoff, time.max))
        return local.astimezone(pytz.UTC).replace(tzinfo=None)

    @staticmethod
    def _date_string(value):
        return fields.Date.to_string(value) if value else False

    @staticmethod
    def _amount(value):
        return format(money(decimal(value)), '.2f')

    def _proof(self, record, cutoff_end, reversal=False):
        if reversal:
            return 'unverified', 'reversal_requires_accounting_audit'
        if record.create_date and record.create_date > cutoff_end:
            return 'unverified', 'entered_after_cutoff'
        if record.write_date and record.write_date > cutoff_end:
            return 'unverified', 'changed_after_cutoff'
        return 'verified', False

    def _snapshot_context(self, company_key, cutoff, employee_id, snapshot_token):
        self._require_reader()
        if not isinstance(company_key, str) or not company_key or company_key != company_key.strip().lower():
            raise ValidationError(_('Invalid company key.'))
        cutoff = self._parse_cutoff(cutoff)
        employee_id = self._parse_positive_id(employee_id, 'Employee')
        mapping = self.env['baseer.hr.loan.snapshot.company'].search([
            ('key', '=', company_key), ('active', '=', True),
        ], limit=2)
        if len(mapping) != 1:
            raise AccessError(_('This company key is not available to the snapshot reader.'))
        company = mapping.company_id
        company.check_access('read')
        company.check_access_rule('read')
        if employee_id:
            employee = self.env['hr.employee'].browse(employee_id).exists()
            employee.check_access('read')
            employee.check_access_rule('read')
            if not employee or employee.company_id != company:
                raise AccessError(_('The employee is not available for this company.'))

        expected = {'user_id': self.env.user.id, 'company_key': company_key,
                    'cutoff': self._date_string(cutoff), 'employee_id': employee_id or 0}
        if snapshot_token:
            state = self._decode_token(snapshot_token)
            if any(state.get(key) != value for key, value in expected.items()):
                raise AccessError(_('Snapshot token scope does not match this request.'))
            try:
                max_loan_id = self._parse_positive_id(state['max_loan_id'], 'Snapshot loan')
                max_line_id = self._parse_positive_id(state['max_line_id'], 'Snapshot line')
                max_allocation_id = self._parse_positive_id(state['max_allocation_id'], 'Snapshot allocation')
            except KeyError:
                raise ValidationError(_('Invalid snapshot token.'))
            return company, cutoff, employee_id, max_loan_id, max_line_id, max_allocation_id, snapshot_token

        loan_domain = [('company_id', '=', company.id), ('date', '<=', cutoff), ('move_id', '!=', False)]
        if employee_id:
            loan_domain.append(('employee_id', '=', employee_id))
        loans = self.env['baseer.hr.loan'].search(loan_domain, order='id desc', limit=1)
        max_loan_id = loans.id or 0
        lines = self.env['baseer.hr.loan.line'].search([('company_id', '=', company.id)], order='id desc', limit=1)
        allocations = self.env['baseer.hr.loan.allocation'].search([('company_id', '=', company.id)], order='id desc', limit=1)
        state = dict(expected, max_loan_id=max_loan_id, max_line_id=lines.id or 0,
                     max_allocation_id=allocations.id or 0)
        return company, cutoff, employee_id, max_loan_id, lines.id or 0, allocations.id or 0, self._encode_token(state)

    def read_snapshot(self, company_key, cutoff, employee_id=None, cursor=None, snapshot_token=None):
        """Return immutable source events and a proven historical balance; never writes."""
        cursor = self._parse_positive_id(cursor, 'Cursor') or 0
        (company, cutoff, employee_id, max_loan_id, max_line_id,
         max_allocation_id, token) = self._snapshot_context(
            company_key, cutoff, employee_id, snapshot_token)
        if not max_loan_id:
            return {'snapshot_token': token, 'next_cursor': False, 'rows': []}

        cutoff_end = self._company_cutoff_end(company, cutoff)
        domain = [
            ('company_id', '=', company.id), ('date', '<=', cutoff), ('move_id', '!=', False),
            ('id', '>', cursor), ('id', '<=', max_loan_id),
        ]
        if employee_id:
            domain.append(('employee_id', '=', employee_id))
        loans = self.env['baseer.hr.loan'].search(domain, order='id', limit=PAGE_SIZE + 1)
        page, more = loans[:PAGE_SIZE], len(loans) > PAGE_SIZE
        currency = company.currency_id.name
        rows = []
        for loan in page:
            loan_status, loan_reason = self._proof(loan, cutoff_end, bool(loan.reversal_move_id))
            lines = loan.line_ids.filtered(lambda line: line.id <= max_line_id)
            allocations = loan.allocation_ids.filtered(
                lambda allocation: allocation.id <= max_allocation_id and allocation.date <= cutoff
            )
            allocation_rows = []
            verified_recovered = decimal(0)
            for allocation in allocations.sorted(lambda row: (row.date, row.id)):
                status, reason = self._proof(allocation, cutoff_end, bool(allocation.reversal_move_id))
                if status == 'verified':
                    verified_recovered += decimal(allocation.amount)
                allocation_rows.append({
                    'date': self._date_string(allocation.date), 'amount': self._amount(allocation.amount),
                    'currency': currency, 'kind': allocation.kind, 'proof_status': status,
                    'proof_reason': reason,
                })
            row_status = loan_status
            row_reason = loan_reason
            if row_status == 'verified' and any(a['proof_status'] != 'verified' for a in allocation_rows):
                row_status, row_reason = 'unverified', 'recovery_requires_audit'
            rows.append({
                'employee_id': loan.employee_id.id, 'employee_name': loan.employee_id.name,
                'loan_date': self._date_string(loan.date), 'loan_amount': self._amount(loan.amount),
                'currency': currency, 'proof_status': row_status, 'proof_reason': row_reason,
                'installments': [{
                    'sequence': line.sequence, 'amount': self._amount(line.amount), 'currency': currency,
                    'original_due_date': self._date_string(line.original_due_date),
                } for line in lines.sorted(lambda line: (line.sequence, line.id))],
                'recoveries': allocation_rows,
                'verified_balance_at_cutoff': self._amount(decimal(loan.amount) - verified_recovered)
                    if row_status == 'verified' else False,
            })
        return {
            'snapshot_token': token,
            'next_cursor': page[-1:].id if more else False,
            'rows': rows,
        }
