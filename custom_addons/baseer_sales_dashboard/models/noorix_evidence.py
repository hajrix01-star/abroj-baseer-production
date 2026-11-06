"""Explicit reporting metadata; existing posted entries remain the money source."""
import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.baseer_pos_summary.models.common import active_company


CENT = Decimal('0.01')
ZERO = Decimal('0.00')
MAX_IMPORT_ROWS = 10000
MAX_AMOUNT = Decimal('999999999.99')
IMPORT_FIELDS = frozenset({
    'company_id', 'move_id', 'source_tenant', 'source_company_key', 'source_id',
    'business_date', 'period_scope', 'customer_count', 'source_gross',
    'extracted_at', 'source_digest',
})


def _amount(value):
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        result = Decimal(str(value))
        if (not result.is_finite() or result < 0 or result > MAX_AMOUNT
                or result != result.quantize(CENT)):
            raise InvalidOperation
        return result.quantize(CENT)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(_('Enter a finite nonnegative amount with at most two decimals.')) from None


class NoorixSalesEvidence(models.Model):
    _name = 'baseer.noorix.sales.evidence'
    _description = 'Noorix sales reporting evidence'
    _rec_name = 'source_id'
    _order = 'business_date, id'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True, readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    move_id = fields.Many2one('account.move', required=True, check_company=True,
                              ondelete='restrict', index=True, readonly=True)
    source_tenant = fields.Char(required=True, readonly=True)
    source_company_key = fields.Char(required=True, readonly=True)
    source_id = fields.Char(required=True, readonly=True, index=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    period_scope = fields.Selection([
        ('all', 'All day'), ('morning', 'Morning'), ('evening', 'Evening'),
    ], required=True, readonly=True)
    customer_count = fields.Integer(required=True, readonly=True)
    source_gross = fields.Monetary(required=True, readonly=True)
    extracted_at = fields.Datetime(required=True, readonly=True)
    source_digest = fields.Char(required=True, readonly=True)
    ledger_digest = fields.Char(required=True, readonly=True, copy=False)

    _source_unique = models.Constraint(
        'UNIQUE(company_id, source_tenant, source_company_key, source_id)',
        'Each Noorix source event may provide reporting evidence only once.',
    )
    _move_unique = models.Constraint(
        'UNIQUE(move_id)', 'Each original entry may have reporting evidence only once.',
    )
    _customers_nonnegative = models.Constraint(
        'CHECK(customer_count >= 0)', 'The recorded customer count cannot be negative.',
    )
    _company_date_index = models.Index('(company_id, business_date)')

    @api.model
    def _require_importer(self):
        if not (self.env.user.has_group('base.group_system')
                or self.env.user.has_group('account.group_account_manager')):
            raise AccessError(_('Only an administrator or accounting manager can import Noorix reporting evidence.'))

    @api.model
    def _normalize_row(self, row):
        if not isinstance(row, dict) or set(row) != IMPORT_FIELDS:
            raise ValidationError(_('Provide exactly the supported Noorix reporting evidence fields.'))
        values = dict(row)
        for key in ('company_id', 'move_id'):
            if type(values[key]) is not int or values[key] <= 0:
                raise ValidationError(_('Choose a valid company and original entry.'))
        if type(values['customer_count']) is not int or not 0 <= values['customer_count'] <= 2147483647:
            raise ValidationError(_('Enter a nonnegative whole recorded customer count.'))
        for key, pattern in (
            ('source_tenant', r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}'),
            ('source_company_key', r'[A-Z][A-Z0-9_-]{0,63}'),
            ('source_id', r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}'),
            ('source_digest', r'[A-Fa-f0-9]{64}'),
        ):
            if not isinstance(values[key], str) or not re.fullmatch(pattern, values[key]):
                raise ValidationError(_('Provide a valid Noorix source identity and SHA-256 digest.'))
        values['source_digest'] = values['source_digest'].lower()
        if values['period_scope'] not in ('all', 'morning', 'evening'):
            raise ValidationError(_('Choose an explicitly recorded sales period.'))
        try:
            business_date = values['business_date']
            if isinstance(business_date, str):
                business_date = date.fromisoformat(business_date)
                if business_date.isoformat() != values['business_date']:
                    raise ValueError
            if type(business_date) is not date:
                raise ValueError
            extracted_at = values['extracted_at']
            if isinstance(extracted_at, str):
                extracted_at = datetime.fromisoformat(extracted_at)
            if (type(extracted_at) is not datetime or extracted_at.tzinfo is not None
                    or extracted_at.microsecond):
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError(_('Provide an ISO business date and an extraction timestamp in UTC with whole seconds.')) from None
        values.update(business_date=business_date, extracted_at=extracted_at,
                      source_gross=float(_amount(values['source_gross'])))
        company = self.env['res.company'].browse(values['company_id']).exists()
        active_company(self, company)
        return values

    @staticmethod
    def _identity(values):
        return tuple(values[key] for key in ('company_id', 'source_tenant', 'source_company_key', 'source_id'))

    def _import_values(self):
        self.ensure_one()
        return {
            key: (self[key].id if key in ('company_id', 'move_id') else self[key])
            for key in IMPORT_FIELDS
        }

    @api.model_create_multi
    def create(self, vals_list):
        self._require_importer()
        if len(vals_list) > MAX_IMPORT_ROWS:
            raise ValidationError(_('Import a list of at most 10,000 Noorix reporting evidence rows.'))
        values = [self._normalize_row(row) for row in vals_list]
        # Include creation validation in the savepoint even for an explicit
        # administrator ORM/RPC create, so a caught validation cannot leave rows.
        with self.env.cr.savepoint():
            for row in values:
                move = self.env['account.move'].browse(row['move_id']).exists()
                if not move:
                    raise ValidationError(_('The original Noorix entry does not exist.'))
                row['ledger_digest'] = self._ledger_digest(move)
            records = super().create(values)
            records._validated_amounts()
        return records

    def write(self, vals):
        raise AccessError(_('Noorix reporting evidence is immutable. Import a corrected snapshot explicitly after administrator removal.'))

    def unlink(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only an administrator can remove reporting metadata.'))
        for record in self:
            active_company(record, record.company_id)
        return super().unlink()

    @api.model
    def import_evidence(self, rows):
        """Atomic, explicitly authorized metadata import; return IDs in input order."""
        self._require_importer()
        if not isinstance(rows, list) or len(rows) > MAX_IMPORT_ROWS:
            raise ValidationError(_('Import a list of at most 10,000 Noorix reporting evidence rows.'))
        values = [self._normalize_row(row) for row in rows]
        if not values:
            return []
        with self.env.cr.savepoint():
            existing = self.search([
                ('company_id', '=', self.env.company.id), '|',
                ('move_id', 'in', [row['move_id'] for row in values]),
                ('source_id', 'in', [row['source_id'] for row in values]),
            ])
            existing._validated_amounts()
            by_identity = {self._identity(record._import_values()): record for record in existing}
            by_move = {record.move_id.id: record for record in existing}
            pending, pending_moves = {}, {}
            for row in values:
                key = self._identity(row)
                record = by_identity.get(key) or by_move.get(row['move_id'])
                if record:
                    if record._import_values() != row:
                        raise ValidationError(_('Conflicting Noorix reporting evidence; no rows have been imported.'))
                    continue
                if ((key in pending and pending[key] != row)
                        or (row['move_id'] in pending_moves and pending_moves[row['move_id']] != key)):
                    raise ValidationError(_('Conflicting Noorix reporting evidence; no rows have been imported.'))
                pending[key] = row
                pending_moves[row['move_id']] = key
            created = self.create(list(pending.values())) if pending else self.browse()
            by_identity.update({self._identity(record._import_values()): record for record in created})
            return [by_identity[self._identity(row)].id for row in values]

    @api.model
    def _ledger_digest(self, move):
        move.check_access('read')
        lines = move.line_ids
        lines.check_access('read')
        lines.account_id.check_access('read')
        data = [move.id, move.company_id.id, move.move_type, move.state,
                str(move.date), move.currency_id.id, move.ref, move.reversed_entry_id.id,
                sorted((line.id, line.account_id.id, line.account_id.account_type,
                        str(Decimal(str(line.balance))), str(Decimal(str(line.amount_currency))),
                        line.currency_id.id, line.tax_line_id.id, line.tax_repartition_line_id.id,
                        sorted(line.tax_tag_ids.ids)) for line in lines)]
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def _validated_amount(self):
        self.ensure_one()
        return self._validated_amounts()[self.id]

    def _validated_amounts(self):
        """Batch tax-configuration lookup; no writes, sudo or estimated VAT."""
        self.check_access('read')
        if not self:
            return {}
        for record in self:
            active_company(record, record.company_id)
        moves = self.move_id
        moves.check_access('read')
        lines = moves.line_ids
        lines.check_access('read')
        lines.account_id.check_access('read')
        lines.tax_line_id.check_access('read')
        lines.tax_repartition_line_id.check_access('read')
        fallback_accounts = lines.filtered(lambda line: not line.tax_line_id and line.tax_tag_ids).account_id
        candidates = self.env['account.tax.repartition.line']
        if fallback_accounts:
            candidates = candidates.search([
                ('company_id', '=', self.env.company.id), ('repartition_type', '=', 'tax'),
                ('document_type', '=', 'invoice'), ('tax_id.type_tax_use', '=', 'sale'),
                ('account_id', 'in', fallback_accounts.ids),
            ])
            candidates.tax_id.check_access('read')
        return {record.id: record._validate_ledger(candidates) for record in self}

    def _validate_ledger(self, candidates):
        self.ensure_one()
        move = self.move_id
        if (move.company_id != self.company_id or move.state != 'posted' or move.move_type != 'entry'
                or move.date != self.business_date or move.currency_id != self.currency_id
                or self.currency_id.name != 'SAR' or move.reversed_entry_id):
            raise ValidationError(_('Noorix reporting evidence no longer matches its original posted SAR entry.'))
        ref = move.ref or ''
        match = re.fullmatch(
            r'(?:AGENT:[ \t]+[^|\r\n]+\|[ \t]*)?'
            r'NOORIX-SALES[ \t]+([A-Z][A-Z0-9_-]*)[ \t]+(\d{4}-\d{2}-\d{2})[^\r\n]*', ref)
        source_ids = re.findall(r'(?<!\S)src:([A-Za-z0-9_-]+)(?=\s|$)', ref)
        if (not match or match[1] != self.source_company_key or match[2] != self.business_date.isoformat()
                or source_ids != [self.source_id]):
            raise ValidationError(_('The Noorix entry reference does not identify this exact source company, date and source ID.'))
        if any(move[name] for name in (
                'baseer_pos_summary_id', 'pos_session_ids', 'pos_order_ids',
                'reversed_pos_order_id', 'origin_payment_id', 'statement_line_id')):
            raise ValidationError(_('The Noorix entry already belongs to a POS, invoice, payment or summary source.'))
        if self.ledger_digest != self._ledger_digest(move):
            raise ValidationError(_('The Noorix source entry changed after evidence extraction. Reconcile its reporting evidence explicitly.'))
        net, vat, funding = ZERO, ZERO, ZERO
        has_income = has_tax = False
        for line in move.line_ids:
            if (line.company_id != self.company_id or self.company_id not in line.account_id.company_ids
                    or line.currency_id != self.currency_id):
                raise ValidationError(_('Noorix source lines have inconsistent company or currency evidence.'))
            balance = Decimal(str(line.balance))
            if not balance.is_finite() or balance != balance.quantize(CENT):
                raise ValidationError(_('Noorix source amounts must be finite SAR amounts with at most two decimals.'))
            tax = line.tax_line_id
            repartition = line.tax_repartition_line_id
            official_tax = bool(tax and repartition and repartition.tax_id == tax
                                and repartition.repartition_type == 'tax'
                                and repartition.document_type == 'invoice'
                                and repartition.account_id == line.account_id
                                and tax.company_id == self.company_id and tax.type_tax_use == 'sale')
            tagged_tax = bool(not tax and line.tax_tag_ids and any(
                candidate.account_id == line.account_id and set(candidate.tag_ids.ids) == set(line.tax_tag_ids.ids)
                for candidate in candidates))
            if official_tax or tagged_tax:
                if balance > 0 or line.account_id.internal_group != 'liability':
                    raise ValidationError(_('The Noorix VAT evidence is not an original sales-tax credit.'))
                vat -= balance
                has_tax = True
            elif tax or repartition:
                raise ValidationError(_('The Noorix VAT origin is unsupported or incomplete; no VAT amount was estimated.'))
            elif line.account_id.account_type in ('income', 'income_other'):
                if balance > 0:
                    raise ValidationError(_('Mixed or partial Noorix sales corrections require explicit reconciliation.'))
                net -= balance
                has_income = True
            elif balance:
                if balance < 0 or line.account_id.internal_group != 'asset':
                    raise ValidationError(_('The Noorix entry contains an unsupported non-sales or mixed component.'))
                funding += balance
        gross = net + vat
        if not has_income or not has_tax or funding != gross or gross != _amount(self.source_gross):
            raise ValidationError(_('Noorix revenue, VAT and debit funding do not reconcile to the source snapshot.'))
        return gross.quantize(CENT)
