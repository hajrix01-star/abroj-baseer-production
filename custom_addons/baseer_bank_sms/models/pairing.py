import json
import secrets
from datetime import timedelta
from urllib.parse import quote

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


PAIRING_LIFETIME_MINUTES = 10


class BaseerBankSmsPairing(models.Model):
    _name = 'baseer.bank.sms.pairing'
    _description = 'Bank SMS phone pairing'
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    token = fields.Char(required=True, copy=False, readonly=True, index=True,
                        default=lambda _self: secrets.token_urlsafe(32))
    expires_at = fields.Datetime(required=True, readonly=True,
                                 default=lambda _self: fields.Datetime.now() + timedelta(minutes=PAIRING_LIFETIME_MINUTES))
    state = fields.Selection([
        ('pending', 'Pending scan'),
        ('used', 'Paired'),
        ('expired', 'Expired'),
    ], default='pending', required=True, readonly=True, index=True)
    device_id = fields.Many2one('baseer.bank.sms.device', readonly=True, ondelete='restrict')
    qr_html = fields.Html(compute='_compute_qr_html', sanitize=False)

    _token_unique = models.Constraint('UNIQUE(token)', 'The pairing token must be unique.')

    @api.depends('create_date', 'state')
    def _compute_name(self):
        for record in self:
            record.name = _('Phone pairing') + ' · ' + (record.create_date and fields.Datetime.to_string(record.create_date) or '')

    @api.depends('token', 'state', 'expires_at')
    def _compute_qr_html(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param(
            'baseer_bank_sms.pairing_base_url',
            self.env['ir.config_parameter'].sudo().get_param('web.base.url', ''),
        ).rstrip('/')
        for record in self:
            if record.state != 'pending' or not record.token or not base_url:
                record.qr_html = False
                continue
            payload = json.dumps({'v': 1, 'url': base_url, 'token': record.token}, separators=(',', ':'))
            source = '/report/barcode/QR/%s?width=320&height=320' % quote(payload, safe='')
            record.qr_html = Markup('<img src="%s" alt="%s" style="max-width:320px;width:100%%;height:auto"/>' % (source, _('Phone pairing QR code')))

    @api.model
    def action_open_new_pairing(self):
        self.search([('state', '=', 'pending'), ('expires_at', '<=', fields.Datetime.now())]).write({'state': 'expired'})
        pairing = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': pairing.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def consume(self, installation_id):
        self.ensure_one()
        if self.state != 'pending' or self.expires_at <= fields.Datetime.now():
            if self.state == 'pending':
                self.write({'state': 'expired'})
            raise ValidationError(_('This phone-pairing QR code has expired. Generate a new one in Baseer SMS.'))
        if not isinstance(installation_id, str) or not 16 <= len(installation_id) <= 120:
            raise ValidationError(_('Invalid phone installation identifier.'))
        Device = self.env['baseer.bank.sms.device'].sudo()
        existing = Device.search([('installation_id', '=', installation_id)], limit=1)
        device_code = 'sms-' + secrets.token_urlsafe(18)
        secret = secrets.token_urlsafe(32)
        salt = secrets.token_hex(16)
        if existing:
            # Reuse the stable installation record: the old bearer secret is
            # replaced atomically, while source_device_id remains audit data
            # on earlier messages.  This also satisfies the unique
            # installation constraint without creating a second active phone.
            # Backfill evidence produced before source_installation_id was
            # introduced while the old device code is still available.
            self.env['baseer.bank.sms.message'].sudo().with_context(
                baseer_bank_sms_internal=True,
            ).search([
                ('source_installation_id', '=', False),
                ('source_device_id', '=', existing.device_code),
            ]).write({'source_installation_id': installation_id})
            existing.write({
                'device_code': device_code,
                'secret_salt': salt,
                'secret_hash': Device._digest(secret, salt),
                'active': True,
            })
            device = existing
        else:
            device = Device.create({
                'name': _('Paired Android phone'),
                'device_code': device_code,
                'installation_id': installation_id,
                'secret_salt': salt,
                'secret_hash': Device._digest(secret, salt),
                'active': True,
            })
        self.write({'state': 'used', 'device_id': device.id})
        return {'device_code': device.device_code, 'device_secret': secret, 'senders': device.allowed_senders()}
