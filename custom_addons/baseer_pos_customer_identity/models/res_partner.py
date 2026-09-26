import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import SQL


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_SAUDI_MOBILE = re.compile(r'^5\d{8}$')
_POS_CUSTOMER_CAPABILITY_PARAM = 'baseer_pos_customer_identity.customer_capability_secret'
_POS_CUSTOMER_CAPABILITY_TTL_SECONDS = 300
_POS_CUSTOMER_EDITABLE_FIELDS = frozenset({'name', 'phone', 'city'})


def _saudi_mobile_key(value):
    """Return one E.164-like key for common Saudi mobile entry variants."""
    digits = ''.join(char for char in (value or '').translate(_ARABIC_DIGITS) if char.isdigit())
    if digits.startswith('00966'):
        digits = digits[2:]
    if digits.startswith('966'):
        national = digits[3:]
    elif digits.startswith('0'):
        national = digits[1:]
    else:
        national = digits
    return f'966{national}' if _SAUDI_MOBILE.fullmatch(national) else False


def _looks_like_saudi_mobile(value):
    """Identify a Saudi-mobile entry even when it has an invalid length."""
    raw = (value or '').translate(_ARABIC_DIGITS).strip()
    digits = ''.join(char for char in raw if char.isdigit())
    if digits.startswith(('009665', '9665', '05')):
        return True
    return bool(digits.startswith('5') and not raw.startswith('+') and not digits.startswith('00'))


class ResPartner(models.Model):
    _inherit = 'res.partner'

    baseer_pos_phone_key = fields.Char(
        string='POS Saudi Mobile Key', compute='_compute_baseer_pos_phone_key',
        compute_sudo=True, store=True, index=True, copy=False, readonly=True,
        help='Normalized Saudi mobile identity used only to search and prevent duplicate POS customers.',
    )

    @api.model
    def _baseer_pos_capability_secret(self):
        params = self.env['ir.config_parameter'].sudo()
        secret = params.get_param(_POS_CUSTOMER_CAPABILITY_PARAM)
        if not secret:
            secret = secrets.token_urlsafe(32)
            params.set_param(_POS_CUSTOMER_CAPABILITY_PARAM, secret)
        return secret.encode()

    @api.model
    def _baseer_pos_customer_capability(self, config, operation, partner_id=False, session=False):
        payload = {
            'config_id': config.id,
            'expires_at': int(time.time()) + _POS_CUSTOMER_CAPABILITY_TTL_SECONDS,
            'operation': operation,
            'partner_id': partner_id or False,
            'session_id': session.id if session else False,
            'uid': self.env.uid,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(',', ':'), sort_keys=True).encode()
        ).decode().rstrip('=')
        signature = hmac.new(
            self._baseer_pos_capability_secret(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        return f'{encoded}.{signature}'

    @api.model
    def _baseer_pos_validate_customer_capability(self, operation, partner_ids=()):
        token = self.env.context.get('baseer_pos_customer_capability')
        if not token:
            return False
        try:
            encoded, signature = token.rsplit('.', 1)
            expected = hmac.new(
                self._baseer_pos_capability_secret(), encoded.encode(), hashlib.sha256
            ).hexdigest()
            payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        except (AttributeError, ValueError, TypeError, json.JSONDecodeError):
            raise AccessError(_('The POS customer edit authorization is invalid.'))
        if not hmac.compare_digest(signature, expected):
            raise AccessError(_('The POS customer edit authorization is invalid.'))
        if (
            payload.get('uid') != self.env.uid
            or payload.get('operation') != operation
            or payload.get('expires_at', 0) < int(time.time())
        ):
            raise AccessError(_('The POS customer edit authorization has expired.'))
        expected_partner_id = payload.get('partner_id') or False
        if operation == 'create':
            if expected_partner_id:
                raise AccessError(_('The POS customer creation authorization is invalid.'))
        elif list(partner_ids) != [expected_partner_id]:
            raise AccessError(_('The POS customer edit authorization does not match this customer.'))
        config = self.env['pos.config'].browse(payload.get('config_id')).exists()
        if not config:
            raise AccessError(_('The POS configuration is no longer available.'))
        session = config._baseer_require_customer_form_session()
        if payload.get('session_id') != session.id:
            raise AccessError(_('The POS customer edit authorization no longer belongs to this session.'))
        return config

    def _check_access(self, operation):
        """Allow no Contacts ACL bypass without a server-signed POS capability."""
        if operation in {'create', 'write'} and self._baseer_pos_validate_customer_capability(
            operation, self.ids
        ):
            return None
        return super()._check_access(operation)

    @api.depends('phone')
    def _compute_baseer_pos_phone_key(self):
        for partner in self:
            partner.baseer_pos_phone_key = _saudi_mobile_key(partner.phone)

    def _baseer_pos_duplicate_phone_domain(self, key, company=None):
        company = company or self.env.company
        return [('baseer_pos_phone_key', '=', key), '|',
                ('company_id', '=', False), ('company_id', '=', company.id)]

    @api.model
    def _baseer_pos_existing_phone_customer(self, key, company=None):
        return self.search(self._baseer_pos_duplicate_phone_domain(key, company), limit=1) if key else self.browse()

    @api.model
    def _baseer_pos_customer_company(self):
        """Use the POS configuration company when the form was opened from POS."""
        config_id = self.env.context.get('baseer_pos_config_id')
        if config_id:
            config = self.env['pos.config'].browse(config_id).exists()
            if config:
                return config.company_id
        return self.env.company

    @api.model
    def _baseer_validate_saudi_mobile(self, phone):
        if phone and _looks_like_saudi_mobile(phone) and not _saudi_mobile_key(phone):
            raise ValidationError(_(
                'A Saudi mobile number must contain exactly nine digits and start with 5.'
            ))

    @api.model_create_multi
    def create(self, vals_list):
        config = self._baseer_pos_validate_customer_capability('create')
        is_import = self.env.context.get('import_file')
        if not config and not is_import:
            return super().create(vals_list)
        prepared_vals_list = []
        for raw_values in vals_list:
            values = dict(raw_values)
            if config:
                unexpected = set(values) - _POS_CUSTOMER_EDITABLE_FIELDS
                if unexpected:
                    raise AccessError(_('Only name, mobile number and city can be set from Point of Sale.'))
                values['company_id'] = False
                values['is_company'] = False
            phone = values.get('phone')
            self._baseer_validate_saudi_mobile(phone)
            key = _saudi_mobile_key(phone)
            if key:
                self.env.execute_query(SQL('SELECT pg_advisory_xact_lock(hashtext(%s))', key))
                existing = self._baseer_pos_existing_phone_customer(
                    # A signed capability carries the authoritative POS configuration.
                    # Never trust a caller-supplied context company for this lookup.
                    key, config.company_id if config else self._baseer_pos_customer_company()
                )
                if existing:
                    raise ValidationError(_(
                        'A customer already exists for this Saudi mobile number: %(customer)s.',
                        customer=existing.display_name,
                    ))
            prepared_vals_list.append(values)
        return super().create(prepared_vals_list)

    def write(self, values):
        config = self._baseer_pos_validate_customer_capability('write', self.ids)
        if config:
            unexpected = set(values) - _POS_CUSTOMER_EDITABLE_FIELDS
            if unexpected:
                raise AccessError(_('Only name, mobile number and city can be changed from Point of Sale.'))
            self._baseer_pos_assert_customer_editable(config)
        if (config or self.env.context.get('import_file')) and 'phone' in values:
            self._baseer_validate_saudi_mobile(values['phone'])
            key = _saudi_mobile_key(values['phone'])
            if key:
                for partner in self:
                    existing = self.search(
                        self._baseer_pos_duplicate_phone_domain(
                            key, partner.company_id or (
                                config.company_id if config else self._baseer_pos_customer_company()
                            )
                        ) + [('id', '!=', partner.id)],
                        limit=1,
                    )
                    if existing:
                        raise ValidationError(_(
                            'A customer already exists for this Saudi mobile number: %(customer)s.',
                            customer=existing.display_name,
                        ))
        return super().write(values)

    def _baseer_pos_assert_customer_editable(self, config):
        for partner in self:
            if (
                partner.is_company
                or partner.employee
                or partner.user_ids
                or partner.parent_id
                or (partner.company_id and partner.company_id != config.company_id)
            ):
                raise AccessError(_('Only an independent individual customer can be edited from Point of Sale.'))

    @api.model
    def get_new_partner(self, config_id, domain, offset):
        """Append an exact Saudi-mobile result to the bounded native POS search."""
        payload = super().get_new_partner(config_id, domain, offset)
        if offset or not domain:
            return payload
        key = next((
            _saudi_mobile_key(term[2]) for term in domain
            if isinstance(term, (tuple, list)) and len(term) == 3
            and term[0] == 'phone_mobile_search' and isinstance(term[2], str)
        ), False)
        if not key:
            return payload
        config = self.env['pos.config'].browse(config_id).exists()
        if not config:
            return payload
        existing_ids = {row['id'] for row in payload.get('res.partner', [])}
        partners = self._baseer_pos_existing_phone_customer(key, config.company_id).filtered(
            lambda partner: partner.id not in existing_ids
        )
        if not partners:
            return payload
        payload.setdefault('res.partner', []).extend(self._load_pos_data_read(partners, config))
        fiscal_positions = partners.fiscal_position_id
        if fiscal_positions:
            payload.setdefault('account.fiscal.position', []).extend(
                self.env['account.fiscal.position']._load_pos_data_read(fiscal_positions, config)
            )
        return payload

    @api.model
    def _load_pos_data_fields(self, config):
        fields_to_load = super()._load_pos_data_fields(config)
        for field_name in ('is_company', 'employee', 'baseer_pos_phone_key'):
            if field_name not in fields_to_load:
                fields_to_load.append(field_name)
        return fields_to_load


class PosConfig(models.Model):
    _inherit = 'pos.config'

    def _baseer_require_customer_form_session(self):
        self.ensure_one()
        self.check_access('read')
        user = self.env.user
        if not (
            user.has_group('baseer_access_roles.group_cashier')
            or user.has_group('baseer_access_roles.group_pos_cashier')
        ):
            raise AccessError(_('A cashier role is required to maintain POS customers.'))
        if self.company_id not in user.company_ids:
            raise AccessError(_('This Point of Sale is not available for the active company.'))
        session = self.env['pos.session'].sudo().search([
            ('config_id', '=', self.id),
            ('user_id', '=', user.id),
            ('state', '=', 'opened'),
        ], limit=1)
        if not session:
            raise AccessError(_('Open this Point of Sale session before maintaining customers.'))
        return session

    def baseer_prepare_customer_form(self, partner_id=False):
        self.ensure_one()
        session = self._baseer_require_customer_form_session()
        Partner = self.env['res.partner']
        if partner_id:
            partner = Partner.sudo().browse(int(partner_id)).exists()
            if not partner:
                raise AccessError(_('This customer no longer exists.'))
            partner._baseer_pos_assert_customer_editable(self)
            return Partner._baseer_pos_customer_capability(self, 'write', partner.id, session)
        return Partner._baseer_pos_customer_capability(self, 'create', session=session)
