from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerPrintPrinter(models.Model):
    """A discovered Windows queue. Network address and driver stay in Windows."""

    _name = 'baseer.print.printer'
    _description = 'Baseer Windows Printer'
    _rec_name = 'name'
    _order = 'agent_id, name, id'
    _check_company_auto = False

    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', readonly=True, copy=False, index=True)
    agent_id = fields.Many2one('baseer.print.agent', required=True, ondelete='restrict', index=True)
    allowed_company_ids = fields.Many2many(
        'res.company', 'baseer_print_printer_company_rel', 'printer_id', 'company_id',
        string='Authorized companies', required=True)
    machine_identifier = fields.Char(required=True, readonly=True, copy=False)
    driver_name = fields.Char(readonly=True, copy=False)
    paper_width = fields.Selection([('58', '58 mm'), ('80', '80 mm')], required=True, default='80')
    active = fields.Boolean(default=False)
    discovered_at = fields.Datetime(readonly=True)
    last_seen_at = fields.Datetime(readonly=True)

    _agent_machine_unique = models.Constraint(
        'unique(agent_id, machine_identifier)', 'A discovered printer may only exist once on an agent.')

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('baseer_print_discovery'):
            raise AccessError(_('Printers must be discovered by a paired Windows agent.'))
        for vals in vals_list:
            if not vals.get('allowed_company_ids') and vals.get('agent_id'):
                agent = self.env['baseer.print.agent'].browse(vals['agent_id'])
                vals['allowed_company_ids'] = [(6, 0, agent.allowed_company_ids.ids)]
        return super().create(vals_list)

    @api.constrains('agent_id', 'allowed_company_ids')
    def _check_authorization(self):
        for record in self:
            if not record.allowed_company_ids:
                raise ValidationError(_('Authorize at least one company for the printer.'))
            if record.agent_id and not record.allowed_company_ids <= record.agent_id.allowed_company_ids:
                raise ValidationError(_('A printer may only authorize companies already authorized for its agent.'))

    def _allows_company(self, company):
        self.ensure_one()
        return bool(company and company in self.allowed_company_ids and self.agent_id._allows_company(company))

    def _require_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can manage direct-print hardware.'))

    def action_test_print(self):
        self._require_admin()
        config_id = self.env.context.get('baseer_pos_config_id')
        if not config_id:
            raise ValidationError(_('Open the test from the Point of Sale configuration so its company is explicit.'))
        config = self.env['pos.config'].browse(config_id).exists()
        if not config:
            raise ValidationError(_('The point of sale is no longer available.'))
        for printer in self:
            self.env['baseer.print.job']._enqueue_test(printer, config)
        return True

    def write(self, vals):
        discovered = {'machine_identifier', 'name', 'driver_name', 'discovered_at', 'last_seen_at'}
        if discovered.intersection(vals) and not self.env.context.get('baseer_print_discovery'):
            raise AccessError(_('Discovered printer metadata is controlled by the agent.'))
        return super().write(vals)

    @api.model
    def _sync_from_agent(self, agent, printers):
        """Discovery updates metadata only; absence is a warning, never deactivation."""
        now = fields.Datetime.now()
        Printer = self.sudo().with_context(active_test=False)
        for item in printers:
            current = Printer.search([
                ('agent_id', '=', agent.id), ('machine_identifier', '=', item['machine_identifier']),
            ], limit=1)
            # Discovery is the source of availability.  A newly paired
            # computer must make its Windows printers selectable immediately;
            # otherwise the normal receipt-printer field is empty even though
            # the agent has already found the device.
            vals = {
                'name': item['display_name'],
                'driver_name': item.get('driver_name', ''),
                'last_seen_at': now,
                'active': True,
            }
            if current:
                current.with_context(baseer_print_discovery=True).write(vals)
            else:
                Printer.with_context(baseer_print_discovery=True).create({
                    **vals, 'agent_id': agent.id, 'machine_identifier': item['machine_identifier'],
                    'discovered_at': now,
                    'allowed_company_ids': [(6, 0, agent.allowed_company_ids.ids)],
                })

    def init(self):
        self._cr.execute('''
            INSERT INTO baseer_print_printer_company_rel (printer_id, company_id)
            SELECT legacy.id, legacy.company_id
              FROM baseer_print_printer AS legacy
             WHERE legacy.company_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM baseer_print_printer_company_rel AS relation
                    WHERE relation.printer_id = legacy.id
                      AND relation.company_id = legacy.company_id
               )
        ''')
