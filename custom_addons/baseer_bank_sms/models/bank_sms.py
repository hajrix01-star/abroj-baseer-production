import hashlib
import hmac
import re
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from psycopg2 import IntegrityError


ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
CURRENCY_RE = r'SAR|SR|KWD|USD|ريال|د\.ك|دينار|\$'
AMOUNT_RE = re.compile(r'(?P<amount>\d+(?:[,.]\d{1,4})?)\s*(?P<currency>' + CURRENCY_RE + r')', re.I)
CURRENCY_FIRST_AMOUNT_RE = re.compile(r'(?P<currency>' + CURRENCY_RE + r')\s*(?P<amount>\d+(?:[,.]\d{1,4})?)', re.I)
EXPLICIT_IDENTIFIER_RES = (
    re.compile(r'(?:card|بطاقة|مدى-أثير|mada(?:-atheer)?|by)\s*[:؛-]?\s*(?:\*+|x+)?\s*(?P<token>\d{4})(?!\d)', re.I),
    re.compile(r'(?:\*+|x+)(?P<token>\d{3,4})(?!\d)', re.I),
    re.compile(r'(?P<token>\d{3,4})(?:\*+)(?!\d)', re.I),
)
MASKED_IDENTIFIER_RE = re.compile(
    r'(?P<left>\d{3,4})\s*(?:\*+|x+)\s*(?P<right>\d{3,4})(?!\d)', re.I,
)
TRANSFER_SOURCE_IDENTIFIER_RE = re.compile(
    r'(?:\bfrom\b|(?<!\S)من(?=\s|[:؛-]|$))\s*[:؛-]?\s*(?:حساب(?:ك)?\s*)?(?:\*+|x+)\s*(?P<token>\d{3,4})(?!\d)',
    re.I,
)
# A bare suffix is only accepted when the bank explicitly labels it as the
# outgoing source ("من 5204" or "من: 5204").  This avoids treating a
# bill/reference number elsewhere in the SMS as an account while supporting
# AlRajhi bill payments.
EXPLICIT_OUTGOING_SOURCE_IDENTIFIER_RE = re.compile(
    r'(?:\bfrom\b|(?<!\S)من(?=\s|[:؛-]|$))(?:\s*[:؛-]\s*|\s+)(?:حساب(?:ك)?\s*)?(?P<token>\d{4})(?!\d)',
    re.I,
)
MASKED_IDENTIFIER_RE = re.compile(
    r'(?P<left>\d{3,4})\s*(?:\*+|x+)\s*(?P<right>\d{3,4})(?!\d)', re.I,
)


def _normalise_text(value):
    return ' '.join((value or '').translate(ARABIC_DIGITS).split())


def _normalise_account_number(value):
    """Keep a complete account readable while matching it consistently."""
    return re.sub(r'[^A-Za-z0-9]', '', _normalise_text(value)).upper()


def _account_digits(value):
    return ''.join(character for character in _normalise_account_number(value) if character.isdigit())


def _complete_account_candidates(body):
    """Return full account/IBAN values only; short suffixes stay aliases."""
    return re.findall(r'(?<![A-Za-z0-9])(?:[A-Za-z]{2})?\d{7,}(?![A-Za-z0-9])', _normalise_text(body))


def _parse_amount(body):
    """Return the first monetary value and original currency code.

    The SMS itself remains the evidence.  This extractor only provides a
    deterministic suggestion and deliberately leaves uncertain messages for
    review rather than creating any financial entry.
    """
    text = _normalise_text(body)
    matches = sorted(
        list(AMOUNT_RE.finditer(text)) + list(CURRENCY_FIRST_AMOUNT_RE.finditer(text)),
        key=lambda match: match.start(),
    )
    for match in matches:
        currency = match.group('currency').upper()
        currency = {
            'SR': 'SAR', 'ريال': 'SAR', 'د.ك': 'KWD', 'دينار': 'KWD', '$': 'USD',
        }.get(currency, currency)
        try:
            return Decimal(match.group('amount').replace(',', '.')), currency
        except InvalidOperation:
            continue
    return False, False


def _parse_identifier(body):
    """Extract an explicit card/account suffix, never a bare amount or date."""
    text = _normalise_text(body)
    for pattern in EXPLICIT_IDENTIFIER_RES:
        match = pattern.search(text)
        if match:
            return match.group('token')
    return False


def _parse_transfer_source_identifier(body):
    """Extract the debited account in an outgoing transfer, if the bank names it."""
    text = _normalise_text(body)
    match = EXPLICIT_OUTGOING_SOURCE_IDENTIFIER_RE.search(text)
    if not match:
        match = TRANSFER_SOURCE_IDENTIFIER_RE.search(text)
    if not match:
        # Arabic bidi rendering may persist the mask after its digits (0409*)
        # although it is displayed before them (*0409) on the phone.
        text = re.sub(r'(?P<token>\d{3,4})\s*(?P<mask>\*+|x+)', r'\g<mask>\g<token>', text)
        match = TRANSFER_SOURCE_IDENTIFIER_RE.search(text)
    return match.group('token') if match else False


def _masked_identifier_pairs(body):
    """Return visible pairs from masked references without retaining an account."""
    return [
        (match.group('left'), match.group('right'))
        for match in MASKED_IDENTIFIER_RE.finditer(_normalise_text(body))
    ]


def _masked_identifier_pairs(body):
    """Return the visible parts of masked bank account references.

    Arabic SMS rendering can present the two parts in reverse visual order.
    Matching therefore accepts either order, but only for one unambiguous
    reference identifier from the same bank sender.
    """
    return [
        (match.group('left'), match.group('right'))
        for match in MASKED_IDENTIFIER_RE.finditer(_normalise_text(body))
    ]


def _classify(body):
    text = _normalise_text(body).lower()
    if re.search(r'otp|رمز (?:التحقق|التأكيد|مؤقت|الدخول|التفعيل)|كود التحقق', text):
        return 'unknown', 'otp', True
    # These are useful audit messages but are not completed movements.  Keep
    # them for review rather than adding them to incoming/outgoing totals.
    if re.search(r'تم رفض العملية|transaction declined|insufficient funds|رصيد غير كاف|إضافة مستفيد|اضافة مستفيد|add beneficiary', text):
        operation_type = 'beneficiary_added' if re.search(r'إضافة مستفيد|اضافة مستفيد|add beneficiary', text) else 'declined'
        return 'unknown', operation_type, False
    if re.search(r'نقاط.*(?:ستنتهي|انتهت صلاحيتها)|points?.*(?:expire|expiring)', text):
        return 'unknown', 'nonfinancial_notice', False
    if re.search(r'credit transfer internal|تحويل داخلي', text):
        return 'unknown', 'internal_transfer_candidate', False
    if re.search(r'credit\s+card\s*:?\s*payment', text):
        return 'out', 'bill_payment', False
    if re.search(r'حوالة.*(?:واردة|وارد)|إيداع|ايداع|تمت إضافة|تم إضافة|تم اضافة|incoming transfer|deposit', text):
        operation_type = 'deposit' if re.search(r'إيداع|ايداع|deposit', text) else 'transfer_in'
        return 'in', operation_type, False
    if re.search(r'حوالة.*(?:صادرة|صادر)|تم تحويل|نوع العملية\s*:\s*تحويل|outgoing transfer', text):
        return 'out', 'transfer_out', False
    if re.search(r'خصم رسوم|bank fee|تم سحب|سحب صراف|شراء|سداد|cash withdrawal|withdrawal|purchase|bill payment', text):
        if 'خصم رسوم' in text or 'bank fee' in text:
            return 'out', 'card_fee', False
        if 'سحب' in text or 'cash withdrawal' in text or 'withdrawal' in text:
            return 'out', 'cash_withdrawal', False
        if 'شراء' in text or 'purchase' in text:
            return 'out', 'card_purchase', False
        if 'سداد' in text or 'bill payment' in text:
            return 'out', 'bill_payment', False
        return 'out', 'transfer_out', False
    return 'unknown', 'unknown', False


class BaseerBankSmsInstrument(models.Model):
    _name = 'baseer.bank.sms.instrument'
    _description = 'Bank SMS identifier'
    _order = 'sender, token, id'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sender_id = fields.Many2one(
        'baseer.bank.sms.sender', string='Bank sender', ondelete='restrict', index=True,
        help='Select the bank SMS sender from the approved sender catalogue.',
    )
    sender = fields.Char(required=True, index=True, help='Exact SMS sender ID, for example the bank sender name.')
    token = fields.Char(required=True, index=True, help='Known identifier, normally the last four digits of an account or card.')
    note = fields.Text()
    analysis_company_id = fields.Many2one(
        'res.company', string='Analytical company', ondelete='restrict', index=True,
        help='Used only for reporting and manual comparison. It never creates a financial destination.',
    )
    analysis_company_ids = fields.Many2many(
        'res.company', 'baseer_bank_sms_instrument_company_rel', 'instrument_id', 'company_id',
        string='Analytical companies',
        help='Companies permitted to use this identifier analytically. A shared identifier never chooses between them automatically.',
    )
    analysis_target_ids = fields.Many2many(
        'baseer.bank.sms.analysis.target', 'baseer_bank_sms_instrument_target_rel',
        'instrument_id', 'target_id', string='Analytical classifications',
        help='Reusable analytical owners permitted for this identifier, such as a company, a shared custody, or personal use.',
    )
    card_ids = fields.One2many(
        'baseer.bank.sms.instrument.card', 'instrument_id', string='Linked cards',
        help='Analytical cards linked to this identifier. They never create a financial destination.',
    )
    alias_ids = fields.One2many('baseer.bank.sms.instrument.alias', 'instrument_id', string='Masked SMS forms')
    account_number = fields.Char(
        string='رقم الحساب الكامل', copy=False,
        help='The complete account used to recognise bank SMS. You may paste, edit, or clear it.',
    )
    account_fingerprint = fields.Char(
        copy=False, readonly=True, index=True,
        help='Fingerprint used for exact bank-SMS matching.',
    )
    account_masked_display = fields.Char(string='Account matching form', compute='_compute_account_matching_state')
    account_matching_configured = fields.Boolean(
        string='Account matching configured', compute='_compute_account_matching_state',
    )

    _instrument_unique = models.Constraint('UNIQUE(sender, token)', 'The sender and identifier must be unique.')

    @api.onchange('sender_id')
    def _onchange_sender_id(self):
        for record in self:
            if record.sender_id:
                record.sender = record.sender_id.sender

    @api.model_create_multi
    def create(self, vals_list):
        Sender = self.env['baseer.bank.sms.sender']
        for vals in vals_list:
            if vals.get('sender_id'):
                vals['sender'] = Sender.browse(vals['sender_id']).sender
            elif vals.get('sender'):
                sender = Sender.search([('sender', '=', vals['sender'])], limit=1)
                if sender:
                    vals['sender_id'] = sender.id
            if 'account_number' in vals:
                vals.update(self._account_values(vals['account_number'], vals.get('token')))
        instruments = super().create(vals_list)
        for instrument, vals in zip(instruments, vals_list):
            if vals.get('analysis_company_id') and not vals.get('analysis_company_ids'):
                instrument.write({'analysis_company_ids': [(4, vals['analysis_company_id'])]})
        instruments._sync_account_aliases()
        return instruments

    def write(self, vals):
        vals = dict(vals)
        if 'account_number' in vals and len(self) > 1:
            for record in self:
                record.write(vals)
            return True
        if vals.get('sender_id'):
            vals['sender'] = self.env['baseer.bank.sms.sender'].browse(vals['sender_id']).sender
        elif vals.get('sender'):
            sender = self.env['baseer.bank.sms.sender'].search([('sender', '=', vals['sender'])], limit=1)
            if sender:
                vals['sender_id'] = sender.id
        if 'account_number' in vals:
            vals.update(self._account_values(vals['account_number'], vals.get('token') or self.token))
        result = super().write(vals)
        if vals.get('analysis_company_id') and 'analysis_company_ids' not in vals:
            self.write({'analysis_company_ids': [(4, vals['analysis_company_id'])]})
        if 'account_number' in vals:
            self._sync_account_aliases()
        return result

    @api.constrains('token')
    def _check_token(self):
        for record in self:
            if len(_normalise_text(record.token)) < 4:
                raise ValidationError(_('Use at least the last four characters of the account or card identifier.'))

    @api.depends('account_number', 'account_fingerprint', 'alias_ids.prefix', 'alias_ids.suffix', 'alias_ids.active')
    def _compute_account_matching_state(self):
        for record in self:
            active_alias = record.alias_ids.filtered('active')[:1]
            record.account_matching_configured = bool(record.account_number or record.account_fingerprint or active_alias)
            record.account_masked_display = (
                f'{active_alias.prefix}***{active_alias.suffix}' if active_alias else False
            )

    @api.model
    def _account_fingerprint(self, account_number):
        """Fingerprint supports exact matching alongside the editable account."""
        parameter = self.env['ir.config_parameter'].sudo()
        secret = parameter.get_param('baseer_bank_sms.account_fingerprint_secret')
        if not secret:
            secret = secrets.token_urlsafe(32)
            parameter.set_param('baseer_bank_sms.account_fingerprint_secret', secret)
        return hmac.new(
            secret.encode(), _normalise_account_number(account_number).encode(), hashlib.sha256,
        ).hexdigest()

    def _account_values(self, value, token):
        account = _normalise_account_number(value)
        if not account:
            return {'account_number': False, 'account_fingerprint': False}
        digits = _account_digits(account)
        if len(digits) < 7:
            raise ValidationError(_('Enter a valid complete account number.'))
        if token and digits[-4:] != _normalise_text(token):
            raise ValidationError(_('The complete account number must end with this identifier\'s last four digits.'))
        return {
            'account_number': account,
            'account_fingerprint': self._account_fingerprint(account),
        }

    def _sync_account_aliases(self):
        Alias = self.env['baseer.bank.sms.instrument.alias']
        for instrument in self:
            generated = instrument.alias_ids.filtered('generated_from_account')
            digits = _account_digits(instrument.account_number)
            if not digits:
                generated.unlink()
                continue
            values = {
                'instrument_id': instrument.id,
                'prefix': digits[:3],
                'suffix': digits[-3:],
                'generated_from_account': True,
            }
            if generated:
                generated[:1].write(values)
                (generated - generated[:1]).unlink()
            else:
                existing = instrument.alias_ids.filtered(
                    lambda alias: alias.prefix == values['prefix'] and alias.suffix == values['suffix']
                )[:1]
                if existing:
                    existing.write({'generated_from_account': True})
                else:
                    Alias.create(values)

    @api.model
    def find_for_sms(self, sender, body, token=False):
        """Resolve exact tokens first, then an unambiguous masked form."""
        normalised = _normalise_text(body)
        full_candidates = _complete_account_candidates(normalised)
        if full_candidates:
            fingerprints = [self._account_fingerprint(candidate) for candidate in full_candidates]
            full_matches = self.search([
                ('active', '=', True), ('sender', '=', sender),
                ('account_fingerprint', 'in', fingerprints),
            ])
            if len(full_matches) == 1:
                return full_matches
        if token:
            instrument = self.search([
                ('active', '=', True), ('sender', '=', sender), ('token', '=', token),
            ], limit=1)
            if instrument:
                return instrument
        pairs = _masked_identifier_pairs(normalised)
        if not pairs:
            return self.browse()

        # Some banks expose an internal three/four digit slice of an IBAN,
        # rather than its first digits, e.g. ``078*409``.  A complete account
        # can still identify that form safely only when the visible start is
        # present in that account and the visible end is its actual end.  The
        # same sender and an unambiguous result are mandatory: otherwise the
        # message remains for review instead of being guessed.
        complete_account_matches = self.browse()
        complete_accounts = self.search([
            ('active', '=', True), ('sender', '=', sender), ('account_number', '!=', False),
        ])
        for instrument in complete_accounts:
            digits = _account_digits(instrument.account_number)
            if any(
                (digits.endswith(right) and left in digits)
                or (digits.endswith(left) and right in digits)
                for left, right in pairs
            ):
                complete_account_matches |= instrument
        if len(complete_account_matches) == 1:
            return complete_account_matches
        if complete_account_matches:
            return self.browse()

        aliases = self.env['baseer.bank.sms.instrument.alias'].search([
            ('active', '=', True), ('instrument_id.active', '=', True),
            ('instrument_id.sender', '=', sender),
        ])
        matches = self.browse()
        for alias in aliases:
            if any(
                (alias.prefix == left and alias.suffix == right)
                or (alias.prefix == right and alias.suffix == left)
                for left, right in pairs
            ):
                matches |= alias.instrument_id
        return matches if len(matches) == 1 else self.browse()


class BaseerBankSmsInstrumentCard(models.Model):
    """A card reference that belongs to an analytical account identifier.

    This is deliberately a recognition aid, not a bank card or accounting
    object.  The parent identifier remains the reporting owner.
    """

    _name = 'baseer.bank.sms.instrument.card'
    _description = 'Bank SMS linked card'
    _order = 'instrument_id, token, id'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    instrument_id = fields.Many2one(
        'baseer.bank.sms.instrument', string='Identifier', required=True, ondelete='cascade', index=True,
    )
    token = fields.Char(
        string='Card suffix', required=True, index=True,
        help='Last four digits shown by the bank SMS for this card.',
    )
    note = fields.Text()

    _instrument_card_unique = models.Constraint(
        'UNIQUE(instrument_id, token)',
        'This card is already linked to the selected identifier.',
    )

    @api.constrains('token', 'instrument_id')
    def _check_token_is_unambiguous_for_sender(self):
        for record in self:
            token = _normalise_text(record.token)
            if not re.fullmatch(r'\d{4}', token or ''):
                raise ValidationError(_('Use the last four digits of the card.'))
            if not record.instrument_id.sender:
                continue
            duplicate = self.search([
                ('id', '!=', record.id), ('active', '=', True), ('token', '=', token),
                ('instrument_id.active', '=', True),
                ('instrument_id.sender', '=', record.instrument_id.sender),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'This card suffix is already linked to another identifier for the same bank sender.'
                ))

    @api.model
    def find_for_sms(self, sender, token=False):
        if not token:
            return self.browse()
        matches = self.search([
            ('active', '=', True), ('token', '=', token),
            ('instrument_id.active', '=', True), ('instrument_id.sender', '=', sender),
        ])
        return matches if len(matches) == 1 else self.browse()

class BaseerBankSmsInstrumentAlias(models.Model):
    _name = 'baseer.bank.sms.instrument.alias'
    _description = 'Bank SMS masked identifier form'
    _order = 'instrument_id, prefix, suffix, id'

    instrument_id = fields.Many2one(
        'baseer.bank.sms.instrument', required=True, ondelete='cascade', index=True,
    )
    prefix = fields.Char(string='Visible start', required=True, index=True, copy=False,
                         help='Visible leading digits in a masked bank SMS. The full account is never stored.')
    suffix = fields.Char(string='Visible end', required=True, index=True, copy=False,
                         help='Visible trailing digits in a masked bank SMS. The full account is never stored.')
    active = fields.Boolean(default=True)
    generated_from_account = fields.Boolean(
        string='مستخرج من رقم الحساب الكامل', readonly=True, copy=False,
        help='Managed automatically when the complete account number changes.',
    )

    _instrument_alias_unique = models.Constraint(
        'UNIQUE(instrument_id, prefix, suffix)',
        'This masked form already belongs to the selected identifier.',
    )

    @api.constrains('prefix', 'suffix')
    def _check_masked_parts(self):
        for record in self:
            for value in (record.prefix, record.suffix):
                normalised = _normalise_text(value)
                if not re.fullmatch(r'\d{3,4}', normalised or ''):
                    raise ValidationError(_('Each masked account part must contain three or four digits.'))


class BaseerBankSmsInstrumentAccountWizard(models.TransientModel):
    _name = 'baseer.bank.sms.instrument.account.wizard'
    _description = 'Set bank SMS account matching pattern'

    instrument_id = fields.Many2one('baseer.bank.sms.instrument', required=True, readonly=True)
    full_account = fields.Char(
        required=True,
        help='Used once to derive matching data, then cleared. The complete account is not retained.',
    )

    def action_apply(self):
        self.ensure_one()
        account = ''.join(character for character in _normalise_text(self.full_account) if character.isdigit())
        if len(account) < 7:
            raise ValidationError(_('Enter a valid complete account number.'))
        if account[-4:] != self.instrument_id.token:
            raise ValidationError(_('The complete account number must end with this identifier\'s last four digits.'))
        Alias = self.env['baseer.bank.sms.instrument.alias']
        values = {
            'instrument_id': self.instrument_id.id,
            'prefix': account[:3],
            'suffix': account[-3:],
        }
        if not Alias.search([
            ('instrument_id', '=', self.instrument_id.id),
            ('prefix', '=', values['prefix']), ('suffix', '=', values['suffix']),
        ], limit=1):
            Alias.create(values)
        self.instrument_id.write({
            'account_fingerprint': self.instrument_id._account_fingerprint(account),
        })
        self.write({'full_account': False})
        return {'type': 'ir.actions.act_window_close'}


class BaseerBankSmsAnalysisTarget(models.Model):
    """A non-financial reporting owner for an SMS identifier or message."""

    _name = 'baseer.bank.sms.analysis.target'
    _description = 'Bank SMS analytical classification'
    _order = 'name, id'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Imported company', ondelete='cascade', index=True,
        help='Set only for the automatic classification created from an existing Odoo company.',
    )
    company_ids = fields.Many2many(
        'res.company', 'baseer_bank_sms_target_company_rel', 'target_id', 'company_id',
        string='Related companies',
        help='Reporting context only. It does not create a financial link, journal, or accounting entry.',
    )
    kind = fields.Selection([
        ('company', 'Company'), ('custody', 'Custody'), ('personal', 'Personal'), ('other', 'Other'),
    ], default='other', required=True)
    note = fields.Text()

    _company_target_unique = models.Constraint(
        'UNIQUE(company_id)', 'Each company can have only one imported analytical classification.',
    )

    @api.model
    def ensure_company_targets(self):
        """Expose the existing company catalogue without creating financial links."""
        companies = self.env['res.company'].with_context(active_test=False).search([])
        existing = self.with_context(active_test=False).search([('company_id', 'in', companies.ids)])
        existing_ids = set(existing.mapped('company_id').ids)
        self.create([
            {
                'name': company.name,
                'company_id': company.id,
                'company_ids': [(4, company.id)],
                'kind': 'company',
            }
            for company in companies if company.id not in existing_ids
        ])
        targets_by_company = {
            target.company_id.id: target
            for target in self.with_context(active_test=False).search([('company_id', 'in', companies.ids)])
        }
        for instrument in self.env['baseer.bank.sms.instrument'].search([
            ('analysis_company_id', '!=', False),
        ]):
            target = targets_by_company.get(instrument.analysis_company_id.id)
            values = {}
            if not instrument.analysis_company_ids:
                values['analysis_company_ids'] = [(4, instrument.analysis_company_id.id)]
            if target and not instrument.analysis_target_ids:
                values['analysis_target_ids'] = [(4, target.id)]
            if values:
                instrument.write(values)
        return True


class BaseerBankSmsSender(models.Model):
    _name = 'baseer.bank.sms.sender'
    _description = 'Allowed bank SMS sender'
    _order = 'sender, id'

    name = fields.Char(required=True, translate=True)
    sender = fields.Char(required=True, index=True, help='Exact sender ID accepted from the Android phone.')
    active = fields.Boolean(default=True)

    _sender_unique = models.Constraint('UNIQUE(sender)', 'The sender ID must be unique.')


class BaseerBankSmsRule(models.Model):
    _name = 'baseer.bank.sms.rule'
    _description = 'Bank SMS routing rule'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    sender_id = fields.Many2one(
        'baseer.bank.sms.sender', string='Bank sender', ondelete='restrict', index=True,
        help='Select the bank SMS sender from the approved sender catalogue.',
    )
    sender = fields.Char(index=True, help='Exact sender ID. Leave empty only for a deliberately generic rule.')
    contains_text = fields.Char(translate=True, help='Required text fragment after sender and identifier matching.')
    instrument_id = fields.Many2one('baseer.bank.sms.instrument', ondelete='restrict', index=True)
    direction = fields.Selection([
        ('in', _('Incoming')), ('out', _('Outgoing')), ('unknown', _('Unknown')),
    ], help='Optional direction condition.')
    company_id = fields.Many2one('res.company', ondelete='restrict', index=True)
    journal_id = fields.Many2one('account.journal', ondelete='restrict', index=True)
    custody_id = fields.Many2one('baseer.procurement.custody', ondelete='restrict', index=True)
    employee_id = fields.Many2one('hr.employee', ondelete='restrict', index=True)
    note = fields.Text()

    @api.onchange('sender_id')
    def _onchange_sender_id(self):
        for record in self:
            if record.sender_id:
                record.sender = record.sender_id.sender

    @api.model_create_multi
    def create(self, vals_list):
        Sender = self.env['baseer.bank.sms.sender']
        for vals in vals_list:
            if vals.get('sender_id'):
                vals['sender'] = Sender.browse(vals['sender_id']).sender
            elif vals.get('sender'):
                sender = Sender.search([('sender', '=', vals['sender'])], limit=1)
                if sender:
                    vals['sender_id'] = sender.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('sender_id'):
            vals['sender'] = self.env['baseer.bank.sms.sender'].browse(vals['sender_id']).sender
        elif vals.get('sender'):
            sender = self.env['baseer.bank.sms.sender'].search([('sender', '=', vals['sender'])], limit=1)
            if sender:
                vals['sender_id'] = sender.id
        return super().write(vals)

    @api.constrains('company_id', 'journal_id', 'custody_id', 'employee_id')
    def _check_destination_company(self):
        for rule in self:
            destinations = [rule.journal_id.company_id, rule.custody_id.company_id, rule.employee_id.company_id]
            destinations = [company for company in destinations if company]
            if rule.company_id and any(company != rule.company_id for company in destinations):
                raise ValidationError(_('Every configured destination must belong to the selected company.'))
            if not rule.company_id and len({company.id for company in destinations}) > 1:
                raise ValidationError(_('A routing rule cannot mix destinations from different companies.'))

    def _matches(self, message):
        self.ensure_one()
        if not self.active:
            return False
        if self.sender and self.sender != message.sender:
            return False
        if self.instrument_id and self.instrument_id != message.instrument_id:
            return False
        if self.direction and self.direction != message.direction:
            return False
        return not self.contains_text or self.contains_text.lower() in (message.raw_body or '').lower()


class BaseerBankSmsMessage(models.Model):
    _name = 'baseer.bank.sms.message'
    _description = 'Bank SMS message'
    _order = 'received_at desc, id desc'

    name = fields.Char(compute='_compute_name', store=True, index=True)
    source_device_id = fields.Char(required=True, copy=False, index=True, readonly=True)
    idempotency_key = fields.Char(required=True, copy=False, index=True, readonly=True)
    sender = fields.Char(required=True, readonly=True, index=True)
    # The server timestamp is the reporting and audit timestamp.  A device
    # timestamp is evidence only: the phone is not a trusted clock.
    received_at = fields.Datetime(string='System Receipt Time', required=True, readonly=True, index=True)
    device_received_at = fields.Datetime(string='Phone SMS Received At', readonly=True, index=True)
    raw_body = fields.Text(required=True, readonly=True, groups='base.group_system')
    body_preview = fields.Char(compute='_compute_body_preview', store=True, index=True,
                               groups='base.group_system')
    body_fingerprint = fields.Char(required=True, readonly=True, index=True)
    amount = fields.Monetary(readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', readonly=True, ondelete='restrict')
    currency_code = fields.Char(readonly=True, index=True)
    identifier_token = fields.Char(readonly=True, index=True)
    source_token = fields.Char(
        string='Source account', readonly=True, index=True,
        help='Account suffix named after “from” in an outgoing transfer. It never uses the beneficiary after “to”.',
    )
    instrument_id = fields.Many2one('baseer.bank.sms.instrument', readonly=True, ondelete='restrict', index=True)
    card_id = fields.Many2one(
        'baseer.bank.sms.instrument.card', string='Linked card', readonly=True, ondelete='restrict', index=True,
        help='Matched analytical card. Its parent identifier owns the reporting classification.',
    )
    manual_analysis_company_id = fields.Many2one(
        'res.company', string='Manual analytical company', ondelete='restrict', index=True, copy=False,
        help='Applies only to this SMS unless an identifier is explicitly learned from its source account.',
    )
    analysis_company_id = fields.Many2one(
        'res.company', string='Analytical company', compute='_compute_analysis_company_id',
        inverse='_inverse_analysis_company_id', store=True, index=True,
        help='Reporting classification only. It never creates a journal entry, payment, or financial routing.',
    )
    manual_analysis_target_id = fields.Many2one(
        'baseer.bank.sms.analysis.target', string='Manual analytical classification',
        ondelete='restrict', index=True, copy=False,
    )
    analysis_target_id = fields.Many2one(
        'baseer.bank.sms.analysis.target', string='Analytical classification',
        compute='_compute_analysis_target_id', inverse='_inverse_analysis_target_id',
        store=True, index=True,
        help='A company, shared custody, personal use, or other reporting classification. It has no financial effect.',
    )
    analysis_at = fields.Datetime(
        string='Analysis date', compute='_compute_analysis_at', store=True, readonly=True, index=True,
        help='Phone receipt time when available, otherwise the system receipt time.',
    )
    direction = fields.Selection([
        ('in', _('Incoming')), ('out', _('Outgoing')), ('unknown', _('Needs review')),
    ], default='unknown', readonly=True, index=True)
    operation_type = fields.Selection([
        ('transfer_in', _('Incoming transfer')), ('transfer_out', _('Outgoing transfer')),
        ('deposit', _('Deposit')), ('card_purchase', _('Card purchase')), ('cash_withdrawal', _('Cash withdrawal')),
        ('bill_payment', _('Bill payment')), ('otp', _('Temporary code')), ('declined', _('Declined transaction')),
        ('beneficiary_added', _('Beneficiary added')), ('card_fee', _('Bank fee')),
        ('internal_transfer_candidate', _('Possible internal transfer')), ('nonfinancial_notice', _('Non-financial notice')),
        ('unknown', _('Unknown')),
    ], default='unknown', readonly=True, index=True)
    suspected_otp = fields.Boolean(readonly=True, index=True)
    state = fields.Selection([
        ('new', _('New')), ('routed', _('Routed')), ('review', _('Needs review')), ('rejected', _('Rejected operations')), ('trash', _('Trash')),
    ], default='new', readonly=True, index=True)
    applied_rule_id = fields.Many2one('baseer.bank.sms.rule', readonly=True, ondelete='restrict')
    company_id = fields.Many2one('res.company', readonly=True, ondelete='restrict', index=True)
    journal_id = fields.Many2one('account.journal', readonly=True, ondelete='restrict', index=True)
    custody_id = fields.Many2one('baseer.procurement.custody', readonly=True, ondelete='restrict', index=True)
    employee_id = fields.Many2one('hr.employee', readonly=True, ondelete='restrict', index=True)

    _source_message_unique = models.Constraint(
        'UNIQUE(source_device_id, idempotency_key)',
        'This SMS has already been received for this device.',
    )

    @api.depends('sender', 'received_at', 'identifier_token')
    def _compute_name(self):
        for record in self:
            record.name = ' / '.join(filter(None, [record.sender, record.identifier_token, fields.Datetime.to_string(record.received_at) if record.received_at else False]))

    @api.depends('instrument_id.analysis_company_id', 'instrument_id.analysis_company_ids', 'manual_analysis_company_id')
    def _compute_analysis_company_id(self):
        for record in self:
            companies = record.instrument_id.analysis_company_ids
            automatic_company = record.instrument_id.analysis_company_id if len(companies) <= 1 else False
            record.analysis_company_id = record.manual_analysis_company_id or automatic_company

    def _inverse_analysis_company_id(self):
        for record in self:
            companies = record.instrument_id.analysis_company_ids
            automatic_company = record.instrument_id.analysis_company_id if len(companies) <= 1 else False
            if record.analysis_company_id == automatic_company:
                record.manual_analysis_company_id = False
            else:
                record.manual_analysis_company_id = record.analysis_company_id

    @api.depends('instrument_id.analysis_target_ids', 'manual_analysis_target_id')
    def _compute_analysis_target_id(self):
        for record in self:
            targets = record.instrument_id.analysis_target_ids
            record.analysis_target_id = record.manual_analysis_target_id or (targets if len(targets) == 1 else False)

    def _inverse_analysis_target_id(self):
        for record in self:
            targets = record.instrument_id.analysis_target_ids
            record.manual_analysis_target_id = False if record.analysis_target_id == (targets if len(targets) == 1 else False) else record.analysis_target_id

    @api.depends('raw_body')
    def _compute_body_preview(self):
        for record in self:
            text = _normalise_text(record.raw_body)
            record.body_preview = text[:100] + ('…' if len(text) > 100 else '')

    @api.depends('device_received_at', 'received_at')
    def _compute_analysis_at(self):
        for record in self:
            record.analysis_at = record.device_received_at or record.received_at

    @api.model
    def _resolve_instrument_and_card(self, sender, body, token=False):
        """Resolve a parent identifier and optional card without guessing.

        A complete protected account match remains the highest confidence
        source.  A linked card is next, followed by the existing account/card
        identifier and unambiguous masked-account matching.
        """
        Instrument = self.env['baseer.bank.sms.instrument']
        normalised = _normalise_text(body)
        full_candidates = _complete_account_candidates(normalised)
        if full_candidates:
            fingerprints = [Instrument._account_fingerprint(candidate) for candidate in full_candidates]
            full_matches = Instrument.search([
                ('active', '=', True), ('sender', '=', sender),
                ('account_fingerprint', 'in', fingerprints),
            ])
            if len(full_matches) == 1:
                return full_matches, self.env['baseer.bank.sms.instrument.card'].browse()

        # An outgoing transfer can name both the debited account ("from") and
        # its beneficiary ("to").  Only the former owns the movement.  Never
        # assign it using the beneficiary suffix merely because it appears
        # later in the text.
        direction, operation_type, _suspected_otp = _classify(normalised)
        if direction == 'out' and operation_type in ('transfer_out', 'bill_payment'):
            source_token = _parse_transfer_source_identifier(normalised)
            if operation_type == 'transfer_out' and not source_token:
                return Instrument.browse(), self.env['baseer.bank.sms.instrument.card'].browse()
            if source_token:
                source_card = self.env['baseer.bank.sms.instrument.card'].find_for_sms(sender, source_token)
                if source_card:
                    return source_card.instrument_id, source_card
                return Instrument.find_for_sms(sender, normalised, source_token), self.env['baseer.bank.sms.instrument.card'].browse()

        card = self.env['baseer.bank.sms.instrument.card'].find_for_sms(sender, token)
        if card:
            return card.instrument_id, card
        return Instrument.find_for_sms(sender, normalised, token), self.env['baseer.bank.sms.instrument.card'].browse()

    @api.model
    def _source_token_for_analysis(self, body, direction, operation_type):
        if direction == 'out' and operation_type in ('transfer_out', 'bill_payment'):
            return _parse_transfer_source_identifier(body)
        return False

    def action_open_source_learning(self):
        self.ensure_one()
        if not self.source_token:
            raise UserError(_(
                'This message does not show a source account after “from”, so it cannot safely create an identifier.'
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Learn source account'),
            'res_model': 'baseer.bank.sms.source.learning.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_message_id': self.id,
                'default_analysis_target_id': self.analysis_target_id.id,
            },
        }

    @api.model
    def ingest(self, *, source_device_id, idempotency_key, sender, body, received_at=None):
        """Idempotently ingest one complete SMS from a trusted future device API.

        This is intentionally an internal service in the first slice. The
        public Android endpoint will be added only with device credential,
        signed request, replay protection, and its own security review.
        """
        if not source_device_id or not idempotency_key or not sender or not body:
            raise ValidationError(_('A device ID, idempotency key, sender, and complete SMS body are required.'))
        existing = self.search([
            ('source_device_id', '=', source_device_id),
            ('idempotency_key', '=', idempotency_key),
        ], limit=1)
        if existing:
            return existing
        text = _normalise_text(body)
        amount, currency_code = _parse_amount(text)
        direction, operation_type, suspected_otp = _classify(text)
        token = _parse_identifier(text)
        source_token = self._source_token_for_analysis(text, direction, operation_type)
        token = token or source_token
        instrument, card = self._resolve_instrument_and_card(sender, text, token)
        currency = self.env['res.currency'].with_context(active_test=False).search([
            ('name', '=', currency_code or 'SAR'),
        ], limit=1)
        fingerprint = hashlib.sha256(f'{sender}|{text}|{received_at or ""}'.encode()).hexdigest()
        values = {
            'source_device_id': source_device_id,
            'idempotency_key': idempotency_key,
            'sender': sender,
            'received_at': fields.Datetime.now(),
            'device_received_at': received_at or False,
            'raw_body': body,
            'body_fingerprint': fingerprint,
            'amount': amount if amount is not False else 0,
            'currency_id': currency.id,
            'currency_code': currency_code or 'SAR',
            'identifier_token': token,
            'source_token': source_token,
            'instrument_id': instrument.id,
            'card_id': card.id,
            'direction': direction,
            'operation_type': operation_type,
            'suspected_otp': suspected_otp,
            'state': self._analysis_state(direction, operation_type, suspected_otp),
        }
        # Two workers can occasionally submit the same queued row at once.
        # The SQL constraint is the final idempotency guard; turn that race
        # into a normal duplicate acknowledgement instead of a transport error.
        try:
            with self.env.cr.savepoint():
                record = self.create(values)
        except IntegrityError:
            record = self.search([
                ('source_device_id', '=', source_device_id),
                ('idempotency_key', '=', idempotency_key),
            ], limit=1)
            if record:
                return record
            raise
        record._apply_first_matching_rule()
        return record

    @api.model
    def _analysis_state(self, direction, operation_type, suspected_otp):
        if suspected_otp or operation_type in ('beneficiary_added', 'nonfinancial_notice'):
            return 'trash'
        if operation_type == 'declined':
            return 'rejected'
        return 'review' if direction == 'unknown' else 'new'

    @api.model
    def reanalyse_received_messages(self, domain=None):
        """Rebuild derived labels from the immutable original SMS evidence.

        This does not change the source, timestamps, or any accounting data.
        A previously routed message keeps its user-approved destination.
        """
        messages = self.search(domain or [])
        for message in messages:
            text = _normalise_text(message.raw_body)
            amount, currency_code = _parse_amount(text)
            direction, operation_type, suspected_otp = _classify(text)
            token = _parse_identifier(text)
            source_token = self._source_token_for_analysis(text, direction, operation_type)
            token = token or source_token
            instrument, card = self._resolve_instrument_and_card(message.sender, text, token)
            currency = self.env['res.currency'].with_context(active_test=False).search([
                ('name', '=', currency_code or 'SAR'),
            ], limit=1)
            values = {
                'amount': amount if amount is not False else 0,
                'currency_id': currency.id,
                'currency_code': currency_code or 'SAR',
                'identifier_token': token,
                'source_token': source_token,
                'instrument_id': instrument.id,
                'card_id': card.id,
                'direction': direction,
                'operation_type': operation_type,
                'suspected_otp': suspected_otp,
            }
            if message.state != 'routed':
                values['state'] = self._analysis_state(direction, operation_type, suspected_otp)
            message.with_context(baseer_bank_sms_internal=True).write(values)
        return len(messages)

    @api.model
    def _dashboard_date(self, value, fallback):
        if not value:
            return fallback
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return fields.Date.to_date(value)

    @api.model
    def _dashboard_amount(self, value, currency):
        """Return backend-formatted monetary data; the browser never sums money."""
        precision = currency.decimal_places if currency else 2
        amount = Decimal(str(value or 0)).quantize(Decimal('1').scaleb(-precision))
        return {
            'value': str(amount),
            'display': f'{amount:,.{precision}f}',
            'currency': currency.name if currency else '',
            'currency_symbol': currency.symbol if currency else '',
            'currency_position': currency.position if currency else 'after',
        }

    @api.model
    def get_analysis_dashboard(self, date_from=False, date_to=False, instrument_id=False,
                               analysis_company_id=False, sender=False):
        """Return a bounded, read-only monthly SMS analysis grouped by currency.

        The return contract contains presentation-ready amounts calculated in
        the backend.  It intentionally reports evidence-derived flow only and
        never a bank balance, journal total, or accounting reconciliation.
        """
        self.check_access('read')
        today = fields.Date.context_today(self)
        start = self._dashboard_date(date_from, today.replace(day=1))
        end = self._dashboard_date(date_to, today)
        if start > end:
            raise ValidationError(_('The start date must be before the end date.'))
        start_at = datetime.combine(start, time.min)
        end_at = datetime.combine(end + timedelta(days=1), time.min)
        message_domain = [
            ('analysis_at', '>=', fields.Datetime.to_string(start_at)),
            ('analysis_at', '<', fields.Datetime.to_string(end_at)),
            ('state', 'not in', ('trash', 'rejected')),
            ('direction', 'in', ('in', 'out')),
        ]
        if instrument_id:
            message_domain.append(('instrument_id', '=', int(instrument_id)))
        if analysis_company_id:
            message_domain.append(('analysis_company_id', '=', int(analysis_company_id)))
        if sender:
            message_domain.append(('sender', '=', sender))

        instrument_domain = [('active', '=', True)]
        if instrument_id:
            instrument_domain.append(('id', '=', int(instrument_id)))
        if analysis_company_id:
            instrument_domain.append(('analysis_company_id', '=', int(analysis_company_id)))
        if sender:
            instrument_domain.append(('sender', '=', sender))
        instruments = self.env['baseer.bank.sms.instrument'].search(instrument_domain, order='sender, token, id')
        grouped = self._read_group(
            message_domain,
            groupby=['instrument_id', 'currency_id', 'direction'],
            aggregates=['amount:sum', '__count'],
        )
        currency_ids = {currency.id for _instrument, currency, _direction, _amount, _count in grouped if currency}
        currencies = {currency.id: currency for currency in self.env['res.currency'].browse(list(currency_ids))}
        totals = {}
        by_instrument = {}
        card_totals = {}
        unassigned_totals = {}
        hidden_identifier_totals = {}
        active_instrument_ids = set(instruments.ids)

        def add_to_bucket(bucket, currency_id, direction, amount, count):
            summary = bucket.setdefault(
                currency_id, {'in': Decimal('0'), 'out': Decimal('0'), 'count': 0},
            )
            summary[direction] += amount
            summary['count'] += count

        for instrument, currency, direction, amount, count in grouped:
            if not currency:
                continue
            currency_id = currency.id
            parent_id = instrument.id if instrument else False
            amount = Decimal(str(amount or 0))
            add_to_bucket(by_instrument.setdefault(parent_id, {}), currency_id, direction, amount, count)
            add_to_bucket(totals, currency_id, direction, amount, count)
            if not parent_id:
                add_to_bucket(unassigned_totals, currency_id, direction, amount, count)
            elif parent_id in active_instrument_ids:
                add_to_bucket(card_totals, currency_id, direction, amount, count)
            else:
                add_to_bucket(hidden_identifier_totals, currency_id, direction, amount, count)

        def build_metrics(values):
            result = []
            for currency_id, summary in sorted(values.items(), key=lambda item: currencies[item[0]].name):
                currency = currencies[currency_id]
                result.append({
                    'currency_id': currency_id,
                    'incoming': self._dashboard_amount(summary['in'], currency),
                    'outgoing': self._dashboard_amount(summary['out'], currency),
                    'net': self._dashboard_amount(summary['in'] - summary['out'], currency),
                    'message_count': summary['count'],
                })
            return result

        cards = []
        for instrument in instruments:
            analysis_labels = instrument.analysis_target_ids.mapped('display_name')
            if not analysis_labels:
                analysis_labels = instrument.analysis_company_ids.mapped('display_name')
            if not analysis_labels and instrument.analysis_company_id:
                analysis_labels = [instrument.analysis_company_id.display_name]
            cards.append({
                'id': instrument.id,
                'name': instrument.name,
                'token': instrument.token,
                'sender': instrument.sender_id.name or instrument.sender,
                'analysis_label': '، '.join(analysis_labels) or 'غير محدد',
                'card_count': len(instrument.card_ids.filtered('active')),
                'metrics': build_metrics(by_instrument.get(instrument.id, {})),
            })
        return {
            'period': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'totals': build_metrics(totals),
            'card_totals': build_metrics(card_totals),
            'unassigned_totals': build_metrics(unassigned_totals),
            'hidden_identifier_totals': build_metrics(hidden_identifier_totals),
            'identifiers': cards,
            'identifier_count': len(instruments),
            'message_count': sum(item['message_count'] for item in build_metrics(totals)),
            'linked_message_count': sum(item['message_count'] for item in build_metrics(card_totals)),
            'unassigned_message_count': sum(item['message_count'] for item in build_metrics(unassigned_totals)),
            'hidden_identifier_message_count': sum(item['message_count'] for item in build_metrics(hidden_identifier_totals)),
            # Compatibility for integrations that consumed the original field.
            # Its meaning now matches its label: messages represented by cards.
            'matched_message_count': sum(item['message_count'] for item in build_metrics(card_totals)),
        }

    def _apply_first_matching_rule(self):
        Rule = self.env['baseer.bank.sms.rule']
        for message in self:
            rule = Rule.search([('active', '=', True)], order='sequence, id').filtered(lambda item: item._matches(message))[:1]
            if not rule:
                continue
            message.with_context(baseer_bank_sms_internal=True).write({
                'applied_rule_id': rule.id,
                'company_id': rule.company_id.id,
                'journal_id': rule.journal_id.id,
                'custody_id': rule.custody_id.id,
                'employee_id': rule.employee_id.id,
                'state': 'routed',
            })

    def action_delete_temporary_codes(self):
        """Allow deliberate clean-up of selected OTP evidence only."""
        if any(not message.suspected_otp for message in self):
            raise UserError(_('Only temporary-code messages can be deleted from this action.'))
        return self.unlink()

    def write(self, vals):
        protected = {'source_device_id', 'idempotency_key', 'sender', 'received_at', 'raw_body', 'body_fingerprint', 'amount', 'currency_id', 'currency_code', 'identifier_token', 'source_token', 'instrument_id', 'card_id', 'direction', 'operation_type', 'suspected_otp'}
        if protected.intersection(vals) and not self.env.context.get('baseer_bank_sms_internal'):
            raise ValidationError(_('SMS evidence fields are immutable after ingestion.'))
        return super().write(vals)

    def unlink(self):
        if any(not message.suspected_otp for message in self):
            raise ValidationError(_('Bank movement evidence cannot be deleted. Use the temporary-code action only for OTP messages.'))
        return super().unlink()


class BaseerBankSmsSourceLearningWizard(models.TransientModel):
    """Teach one analytical source account from a reviewed SMS message.

    This wizard intentionally owns no financial destination.  It can either
    classify only the selected evidence row, or create/update a reusable
    identifier from the explicit source account shown in that row.
    """

    _name = 'baseer.bank.sms.source.learning.wizard'
    _description = 'Learn Bank SMS Source Account'

    message_id = fields.Many2one(
        'baseer.bank.sms.message', required=True, readonly=True, ondelete='cascade',
    )
    sender = fields.Char(related='message_id.sender', readonly=True)
    source_token = fields.Char(related='message_id.source_token', readonly=True)
    analysis_target_id = fields.Many2one(
        'baseer.bank.sms.analysis.target', string='Analytical classification', required=True,
        ondelete='restrict',
        help='Company, shared custody, personal use, or another reporting owner. It has no financial effect.',
    )
    existing_instrument_id = fields.Many2one(
        'baseer.bank.sms.instrument', compute='_compute_existing_instrument', readonly=True,
    )

    @api.model
    def default_get(self, fields_list):
        self.env['baseer.bank.sms.analysis.target'].ensure_company_targets()
        return super().default_get(fields_list)

    @api.depends('message_id.sender', 'message_id.source_token')
    def _compute_existing_instrument(self):
        Instrument = self.env['baseer.bank.sms.instrument'].with_context(active_test=False)
        for wizard in self:
            wizard.existing_instrument_id = Instrument.search([
                ('sender', '=', wizard.message_id.sender),
                ('token', '=', wizard.message_id.source_token),
            ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        self.env['baseer.bank.sms.analysis.target'].ensure_company_targets()
        return super().create(vals_list)

    def _check_source(self):
        self.ensure_one()
        if not self.message_id.source_token:
            raise ValidationError(_('This message has no explicit source account to learn.'))

    def action_apply_to_message_only(self):
        self._check_source()
        self.message_id.write({'manual_analysis_target_id': self.analysis_target_id.id})
        return {'type': 'ir.actions.act_window_close'}

    def action_create_source_identifier(self):
        self._check_source()
        message = self.message_id
        Instrument = self.env['baseer.bank.sms.instrument'].with_context(active_test=False)
        instrument = Instrument.search([
            ('sender', '=', message.sender), ('token', '=', message.source_token),
        ], limit=1)
        if instrument:
            previous_targets = instrument.analysis_target_ids
            if self.analysis_target_id not in previous_targets and len(previous_targets) == 1:
                # Once a shared identifier has a second target, preserve every
                # previous automatic result as an explicit historical decision.
                self.env['baseer.bank.sms.message'].search([
                    ('instrument_id', '=', instrument.id), ('manual_analysis_target_id', '=', False),
                ]).write({'manual_analysis_target_id': previous_targets.id})
            instrument.write({
                'active': True,
                'analysis_target_ids': [(4, self.analysis_target_id.id)],
            })
        else:
            sender = self.env['baseer.bank.sms.sender'].search([
                ('sender', '=', message.sender),
            ], limit=1)
            instrument = Instrument.create({
                'name': _('Source account %s') % message.source_token,
                'sender_id': sender.id,
                'sender': message.sender,
                'token': message.source_token,
                'analysis_target_ids': [(4, self.analysis_target_id.id)],
                'note': _('Learned from outgoing-transfer SMS evidence.'),
            })

        # The selected classification is deliberate for this message.  It
        # remains correct even when the identifier is shared by several owners.
        message.write({'manual_analysis_target_id': self.analysis_target_id.id})

        # Rebuild only the matching source account.  This affects analysis
        # labels, never a journal, payment, custody, or routing rule.
        self.env['baseer.bank.sms.message'].reanalyse_received_messages([
            ('sender', '=', message.sender), ('source_token', '=', message.source_token),
        ])
        return {'type': 'ir.actions.act_window_close'}
