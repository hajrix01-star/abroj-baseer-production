from datetime import timedelta
from urllib.parse import urlparse

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import new_secret


class PosConfig(models.Model):
    _inherit = 'pos.config'

    baseer_effective_print_agent_id = fields.Many2one(
        'baseer.print.agent', compute='_compute_baseer_effective_print_agent',
        string='Company print computer', readonly=True,
    )
    baseer_print_hardware_status = fields.Char(
        compute='_compute_baseer_effective_print_agent', string='Printing device status', readonly=True,
    )
    baseer_direct_print_enabled = fields.Boolean(string='Use Baseer direct printing')
    baseer_receipt_printer_id = fields.Many2one(
        'baseer.print.printer', string='Receipt Windows printer', ondelete='restrict')
    baseer_receipt_copies = fields.Integer(string='Receipt copies', default=1)
    baseer_native_receipt_enabled = fields.Boolean(
        string='Print the original Odoo customer receipt',
        help='Use the original Odoo POS receipt image for customer printing. Kitchen tickets are unchanged.',
    )
    baseer_print_session_close_report = fields.Boolean(
        string='Print session closing report',
        help='Print one thermal summary after the session has closed successfully.',
    )
    baseer_preparation_binding_ids = fields.One2many(
        'baseer.print.route', 'pos_config_id', string='Kitchen printer bindings')

    @api.depends('company_id', 'company_id.baseer_primary_print_agent_id')
    def _compute_baseer_effective_print_agent(self):
        for config in self:
            agent = config.company_id._baseer_effective_print_agent() if config.company_id else self.env['baseer.print.agent']
            config.baseer_effective_print_agent_id = agent
            if not agent:
                config.baseer_print_hardware_status = _('No company print computer is configured')
            elif agent.state == 'online':
                config.baseer_print_hardware_status = _('Connected')
            else:
                config.baseer_print_hardware_status = _('Not connected')

    @api.onchange('company_id')
    def _onchange_baseer_company_print_computer(self):
        for config in self:
            agent = config.baseer_effective_print_agent_id
            if config.baseer_receipt_printer_id and config.baseer_receipt_printer_id.agent_id != agent:
                config.baseer_receipt_printer_id = False
            if agent and not config.baseer_receipt_printer_id:
                printers = self.env['baseer.print.printer'].search([
                    ('agent_id', '=', agent.id), ('active', '=', True),
                    ('paper_width', '=', '80'),
                    ('allowed_company_ids', 'in', config.company_id.ids),
                ], limit=2)
                if len(printers) == 1:
                    config.baseer_receipt_printer_id = printers

    @api.model
    def _load_pos_data_fields(self, config):
        # In native read(), [] means all fields, not no fields. Never narrow
        # that contract to a manually maintained subset of bootstrap fields.
        native_fields = super()._load_pos_data_fields(config)
        if not native_fields:
            # ``pos.load.mixin`` uses an empty list as a legacy "load all"
            # marker. Resolve it under the cashier's field access, then omit
            # relations owned by printing/HR administration.
            native_fields = list(self.fields_get())
        native_fields = [
            field_name for field_name in native_fields
            if field_name not in {
                'baseer_effective_print_agent_id',
                'baseer_print_hardware_status',
                'baseer_receipt_printer_id',
                'baseer_receipt_copies',
                'baseer_print_session_close_report',
                'baseer_preparation_binding_ids',
                'minimal_employee_ids',
                'basic_employee_ids',
                'advanced_employee_ids',
            }
        ]
        return list(dict.fromkeys(native_fields + [
            'baseer_direct_print_enabled',
            'baseer_native_receipt_enabled',
        ]))

    def _baseer_assert_native_receipt_company_ready(self):
        """Shared setup/print preflight; never manufacture fiscal data."""
        for config in self:
            company = config.company_id
            if company.country_id.code == 'SA' and (not company.vat or not company.name):
                raise ValidationError(_(
                    'Complete the Saudi company VAT and name before printing its QR receipt.'
                ))

    def _baseer_preparation_bindings_payload(self):
        self.ensure_one()
        return [{
            'category_id': binding.pos_category_id.id or False,
            'category_name': binding.pos_category_id.display_name if binding.pos_category_id else _('Kitchen'),
        } for binding in self.sudo().baseer_preparation_binding_ids.filtered(
            lambda binding: binding.active and binding.ticket_type == 'preparation'
        )]

    @api.model
    def baseer_agent_status(self, pos_config_id):
        """Return a deliberately small, server-authoritative POS health view.

        This endpoint is display-only.  It cannot expose a local printer,
        bearer credential, route, pairing secret, or an arbitrary agent record.
        """
        if not isinstance(pos_config_id, int):
            raise AccessError(_('The point of sale is not valid.'))
        config = self.browse(pos_config_id).exists()
        if not config:
            raise AccessError(_('The point of sale is not available.'))
        config.check_access('read')
        if not config.baseer_direct_print_enabled:
            return {'state': 'disabled', 'configured': False, 'last_seen_at': False}
        printer = config.sudo().baseer_receipt_printer_id
        agent = printer.agent_id if printer else self.env['baseer.print.agent']
        if not printer or not agent or not agent.active or agent.state == 'revoked':
            return {'state': 'unconfigured', 'configured': False, 'last_seen_at': False}
        now = fields.Datetime.now()
        seen = agent.last_seen_at
        if not seen or agent.state != 'online':
            state = 'offline'
        elif seen >= now - timedelta(seconds=15):
            state = 'online'
        elif seen >= now - timedelta(seconds=30):
            state = 'stale'
        else:
            state = 'offline'
        return {
            'state': state,
            'configured': True,
            'last_seen_at': fields.Datetime.to_string(seen) if seen else False,
            # This is a fixed literal handled by the installed launcher.  It
            # never carries a server URL, code, token, path or user input.
            'repair_uri_allowed': state in ('stale', 'offline'),
        }

    @api.constrains(
        'baseer_direct_print_enabled', 'baseer_receipt_printer_id', 'baseer_receipt_copies',
        'baseer_print_session_close_report', 'baseer_native_receipt_enabled', 'printer_ids',
    )
    def _check_baseer_configuration(self):
        for config in self:
            if not 1 <= config.baseer_receipt_copies <= 10:
                raise ValidationError(_('Receipt copies must be between 1 and 10.'))
            if not config.baseer_direct_print_enabled:
                if config.baseer_print_session_close_report:
                    raise ValidationError(_(
                        'Enable Baseer direct printing before enabling the session closing report.'
                    ))
                continue
            if not config.baseer_receipt_printer_id:
                raise ValidationError(_('Choose a Baseer Windows receipt printer before enabling direct printing.'))
            if not config.baseer_receipt_printer_id._allows_company(config.company_id):
                raise ValidationError(_('The receipt printer is not authorized for this company.'))
            primary_agent = config.company_id.baseer_primary_print_agent_id
            if primary_agent and config.baseer_receipt_printer_id.agent_id != primary_agent:
                raise ValidationError(_('Choose a receipt printer discovered by this company’s primary Windows print computer.'))
            if config.baseer_native_receipt_enabled:
                if config.baseer_receipt_printer_id.paper_width != '80':
                    raise ValidationError(_('The original Odoo receipt requires an 80 mm receipt printer.'))
                if not self.env['baseer.print.job']._agent_supports_native_receipts(
                        config.baseer_receipt_printer_id.agent_id):
                    raise ValidationError(_('Update the Windows print agent to version 1.4.0 before enabling the original Odoo receipt.'))
                legacy = self.env['baseer.print.job'].sudo().search_count([
                    ('pos_config_id', '=', config.id), ('ticket_type', '=', 'receipt'),
                    ('receipt_image_sha256', '=', False),
                    ('state', 'in', ('pending', 'leased')),
                ])
                if legacy:
                    raise ValidationError(_(
                        'Resolve pending customer receipt jobs before switching to the original Odoo receipt.'
                    ))
            if config.printer_ids:
                raise ValidationError(_(
                    'A POS using Baseer direct printing cannot mix Baseer with native IoT or Epson preparation printers.'
                ))

    def action_baseer_test_receipt_printer(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can test direct printing.'))
        if not self.baseer_receipt_printer_id:
            raise ValidationError(_('Choose a receipt printer first.'))
        job = self.env['baseer.print.job']._enqueue_test(self.baseer_receipt_printer_id, self)
        return {'type': 'ir.actions.act_window', 'res_model': 'baseer.print.job', 'res_id': job.id,
                'view_mode': 'form', 'target': 'current'}

    def action_baseer_download_and_connect_agent(self):
        """Create one pending company computer and download its connection EXE.

        This is the daily setup entry point: it deliberately bypasses the
        retired guided modal and never exposes a pairing code, server URL, or
        technical release list to the cashier-facing POS configuration flow.
        """
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can configure Windows printing.'))
        parsed = urlparse(self.env['ir.config_parameter'].sudo().get_param('web.base.url', ''))
        if parsed.scheme != 'https' or not parsed.netloc:
            raise UserError(_('This environment has no HTTPS address for secure agent pairing.'))
        company = self.company_id
        if company._baseer_effective_print_agent():
            raise UserError(_('A Windows print computer is already active for this company. Use its repair action instead.'))
        Agent = self.env['baseer.print.agent']
        pending = Agent.search([
            ('active', '=', True), ('state', '=', 'new'),
            ('device_uid', '=like', 'PENDING-%'),
            ('allowed_company_ids', 'in', company.ids),
        ], order='id desc', limit=1)
        if not pending:
            pending = Agent.create({
                'name': _('New printer computer'),
                'device_uid': 'PENDING-%s' % new_secret(24),
                'allowed_company_ids': [Command.set(company.ids)],
            })
        release = self.env['baseer.print.agent.release'].search([('state', '=', 'approved')], limit=1)
        if not release:
            raise UserError(_('No approved Windows print agent is available. Ask a system administrator to publish one first.'))
        return release.action_download_and_connect(pending)

    def action_baseer_open_guided_print_setup(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can configure Windows printing.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Guided print setup'),
            'res_model': 'baseer.print.setup.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'baseer_pos_config_id': self.id},
        }

    @api.model
    def _load_pos_data_read(self, records, config):
        values = super()._load_pos_data_read(records, config)
        by_id = {record.id: record for record in records}
        for value in values:
            record = by_id.get(value.get('id'))
            if record:
                value['baseer_direct_print_enabled'] = record.baseer_direct_print_enabled
                value['baseer_native_receipt_enabled'] = record.baseer_native_receipt_enabled
                # The POS receives display-only binding metadata. The browser never
                # receives a printer address or decides the final printer route.
                value['baseer_preparation_bindings'] = record._baseer_preparation_bindings_payload()
        return values
