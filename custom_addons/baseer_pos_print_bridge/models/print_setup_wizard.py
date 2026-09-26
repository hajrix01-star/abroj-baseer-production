from urllib.parse import urlparse

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .common import new_secret


class BaseerPrintSetupWizard(models.TransientModel):
    """Admin-only guided setup; the bridge remains the sole hardware owner."""

    _name = 'baseer.print.setup.wizard'
    _description = 'Baseer POS Print Setup'

    pos_config_id = fields.Many2one('pos.config', required=True, readonly=True)
    company_id = fields.Many2one(related='pos_config_id.company_id', readonly=True)
    setup_mode = fields.Selection([
        ('existing', 'Use existing print computer'),
        ('new', 'Add new print computer'),
    ], required=True, default='existing')
    server_url = fields.Char(readonly=True)
    agent_id = fields.Many2one('baseer.print.agent', string='Windows computer')
    pairing_code = fields.Char(string='One-time pairing code', readonly=True, copy=False)
    receipt_printer_id = fields.Many2one('baseer.print.printer', string='80 mm receipt printer')
    create_default_kitchen_route = fields.Boolean(string='Use the same printer for the kitchen by default', default=True)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        config_id = self.env.context.get('baseer_pos_config_id')
        if config_id:
            config = self.env['pos.config'].browse(config_id).exists()
            if config:
                existing_agent = config.baseer_receipt_printer_id.agent_id
                available_agent = self.env['baseer.print.agent'].search([
                    ('active', '=', True), ('state', 'in', ['online', 'offline']),
                    ('allowed_company_ids', 'in', config.company_id.ids),
                ], limit=1)
                values.update({
                    'pos_config_id': config.id,
                    'setup_mode': 'existing' if (existing_agent or available_agent) else 'new',
                    'agent_id': existing_agent.id,
                    'receipt_printer_id': config.baseer_receipt_printer_id.id,
                    'server_url': self.env['ir.config_parameter'].sudo().get_param('web.base.url', ''),
                })
        return values

    @api.onchange('agent_id')
    def _onchange_agent_id(self):
        """Keep printer ownership valid and select the only safe default."""
        if self.receipt_printer_id and self.receipt_printer_id.agent_id != self.agent_id:
            self.receipt_printer_id = False
        if not self.agent_id or self.receipt_printer_id:
            return

        # Never guess between several physical printers.  When the selected
        # Windows computer has exactly one company-authorised 80 mm printer,
        # choosing it removes an unnecessary setup step.  With two or more,
        # leave the field blank so the administrator explicitly picks one.
        printers = self.env['baseer.print.printer'].search([
            ('agent_id', '=', self.agent_id.id),
            ('active', '=', True),
            ('paper_width', '=', '80'),
            ('allowed_company_ids', 'in', self.company_id.ids),
        ], order='id', limit=2)
        if len(printers) == 1:
            self.receipt_printer_id = printers

    def _require_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can configure Windows printing.'))

    def _validate_https_url(self):
        parsed = urlparse(self.server_url or '')
        if parsed.scheme != 'https' or not parsed.netloc:
            raise UserError(_(
                'This environment has no HTTPS address for secure agent pairing. '
                'Use the production or HTTPS QA address; the Windows agent intentionally refuses HTTP.'
            ))

    def _next_wizard_action(self, message, level='success'):
        """Reload the wizard after an action without relying on a chained toast.

        Odoo's POS/backend action manager does not consistently execute the
        ``next`` action nested inside ``display_notification`` for a transient
        modal.  Returning the wizard action directly keeps the pairing code
        visible and works identically from every supported web client.
        """
        return {
            'type': 'ir.actions.act_window',
            'name': _('Guided print setup'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_download_approved_agent(self):
        self.ensure_one()
        self._require_admin()
        release = self.env['baseer.print.agent.release'].search([('state', '=', 'approved')], limit=1)
        if not release:
            raise UserError(_('No approved Windows print agent is available. Ask a system administrator to publish one first.'))
        return release.action_download()

    def action_download_and_connect_agent(self):
        """Prepare one pending computer and download its one-click Agent EXE."""
        self.ensure_one()
        self._require_admin()
        if self.setup_mode != 'new':
            raise UserError(_('Choose "Add new print computer" before downloading its connection file.'))
        self._validate_https_url()
        if self.agent_id and not self.agent_id.device_uid.startswith('PENDING-'):
            self.agent_id = False
            self.receipt_printer_id = False
        if not self.agent_id:
            self.agent_id = self.env['baseer.print.agent'].create({
                'name': _('New printer computer'),
                'device_uid': 'PENDING-%s' % new_secret(24),
                'allowed_company_ids': [Command.set(self.company_id.ids)],
            })
        release = self.env['baseer.print.agent.release'].search([('state', '=', 'approved')], limit=1)
        if not release:
            raise UserError(_('No approved Windows print agent is available. Ask a system administrator to publish one first.'))
        return release.action_download_and_connect(self.agent_id)

    def action_start_pairing(self):
        self.ensure_one()
        self._require_admin()
        if self.setup_mode != 'new':
            raise UserError(_('Choose "Add new print computer" before creating a pairing code.'))
        self._validate_https_url()
        # A user can switch modes in the browser. Never issue a new code for
        # a known computer: pairing is only for a new physical Windows host.
        if self.agent_id and not self.agent_id.device_uid.startswith('PENDING-'):
            self.agent_id = False
            self.receipt_printer_id = False
        if self.agent_id and self.agent_id.state == 'online':
            return self._next_wizard_action(_('This Windows computer is already paired and online. Choose its discovered printer below.'))
        if not self.agent_id:
            agent = self.env['baseer.print.agent'].create({
                'name': _('New printer computer'),
                # Windows supplies its own stable identity during pairing. A
                # random pending value avoids asking a non-technical user to
                # type it in Odoo while preserving the required field.
                'device_uid': 'PENDING-%s' % new_secret(24),
                'allowed_company_ids': [Command.set(self.company_id.ids)],
            })
            self.agent_id = agent
        else:
            agent = self.agent_id
        code = agent._generate_pairing_code()
        self.pairing_code = code
        return self._next_wizard_action(_(
            'Open the downloaded agent on the printer computer. In its pairing window, enter this HTTPS address and one-time code within 10 minutes. The computer identity is filled in automatically by Windows.'
        ), 'warning')

    def _validate_hardware(self):
        self.ensure_one()
        if not self.agent_id or not self.receipt_printer_id:
            raise ValidationError(_('اختر جهاز الطباعة ثم طابعة الإيصالات 80 مم قبل الحفظ.'))
        agent = self.agent_id
        printer = self.receipt_printer_id
        if agent.state != 'online' or not agent.active:
            raise ValidationError(_('The selected Windows computer is not online yet. Start the Baseer Print Agent, wait a moment, then reopen this setup.'))
        if printer.agent_id != agent:
            raise ValidationError(_('The selected printer was discovered from a different Windows computer.'))
        if not agent._allows_company(self.company_id) or not printer._allows_company(self.company_id):
            raise ValidationError(_('The Windows computer or printer is not authorized for this POS company.'))
        if printer.paper_width != '80':
            raise ValidationError(_('Choose an 80 mm receipt printer.'))
        if not self.env['baseer.print.job']._agent_supports_native_receipts(agent):
            raise ValidationError(_('Update the Windows print agent to 1.4.0 or later before enabling the original Odoo receipt.'))

    def action_apply_and_test(self):
        self.ensure_one()
        self._require_admin()
        self._validate_hardware()
        config = self.pos_config_id
        config._baseer_assert_native_receipt_company_ready()
        printer = self.receipt_printer_id
        if not printer.active:
            printer.write({'active': True})
        config.write({
            'baseer_direct_print_enabled': True,
            'baseer_receipt_printer_id': printer.id,
            'baseer_receipt_copies': 1,
            'baseer_native_receipt_enabled': True,
            'baseer_print_session_close_report': True,
        })
        if self.create_default_kitchen_route:
            Route = self.env['baseer.print.route']
            route = Route.search([
                ('pos_config_id', '=', config.id), ('ticket_type', '=', 'preparation'),
                ('pos_category_id', '=', False),
            ], limit=1)
            values = {'printer_id': printer.id, 'copies': 1, 'priority': 10, 'active': True}
            if route:
                route.write(values)
            else:
                Route.create({'pos_config_id': config.id, **values})
        job = self.env['baseer.print.job']._enqueue_test(printer, config)
        return {'type': 'ir.actions.act_window', 'res_model': 'baseer.print.job', 'res_id': job.id,
                'view_mode': 'form', 'target': 'current'}
