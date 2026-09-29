import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class BaseerPrintRoute(models.Model):
    """Internal POS-owned preparation binding; never a stand-alone daily menu."""

    _name = 'baseer.print.route'
    _description = 'Baseer POS Preparation Binding'
    _order = 'pos_config_id, printer_id, priority, id'
    _check_company_auto = False

    name = fields.Char(compute='_compute_name', store=True)
    # Preserves PRINT-1 data. New values are copied from pos_config by the server.
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    pos_config_id = fields.Many2one('pos.config', required=True, ondelete='restrict', index=True)
    ticket_type = fields.Selection([('receipt', 'Receipt'), ('preparation', 'Preparation')],
                                   required=True, default='preparation', index=True)
    # Kept solely as a read-compatible migration source for historic rows.
    # New routing and the UI use the explicit multiple-category relation.
    pos_category_id = fields.Many2one('pos.category', ondelete='restrict', string='Legacy POS Category', readonly=True)
    pos_category_ids = fields.Many2many(
        'pos.category', 'baseer_print_route_pos_category_rel', 'route_id', 'category_id',
        string='POS Categories', help='Product categories sent to this preparation printer.')
    printer_id = fields.Many2one('baseer.print.printer', required=True, ondelete='restrict', index=True)
    copies = fields.Integer(required=True, default=1)
    priority = fields.Integer(required=True, default=10)
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('pos_config_id'):
                config = self.env['pos.config'].browse(vals['pos_config_id'])
                vals['company_id'] = config.company_id.id
            # Preserve API compatibility for internal callers during the
            # migration. The legacy value is copied once into the new relation.
            if vals.get('pos_category_id') and not vals.get('pos_category_ids'):
                vals['pos_category_ids'] = [fields.Command.link(vals['pos_category_id'])]
                vals['pos_category_id'] = False
            vals.setdefault('ticket_type', 'preparation')
        records = super().create(vals_list)
        records._check_active_category_ownership()
        return records

    def write(self, vals):
        if vals.get('pos_config_id'):
            vals['company_id'] = self.env['pos.config'].browse(vals['pos_config_id']).company_id.id
        result = super().write(vals)
        self._check_active_category_ownership()
        return result

    @api.depends('pos_config_id', 'pos_category_id', 'pos_category_ids', 'printer_id')
    def _compute_name(self):
        for record in self:
            categories = record.pos_category_ids
            category_name = ', '.join(categories.mapped('display_name')) if categories else _('Default kitchen')
            record.name = '%s · %s · %s' % (
                record.pos_config_id.display_name or '', category_name,
                record.printer_id.display_name or '',
            )

    @api.constrains('pos_config_id', 'printer_id', 'copies', 'priority', 'ticket_type')
    def _check_binding(self):
        for record in self:
            if record.ticket_type != 'preparation':
                raise ValidationError(_('Receipt routing is configured directly on the point of sale.'))
            if not 1 <= record.copies <= 10:
                raise ValidationError(_('Copies must be between 1 and 10.'))
            if not 1 <= record.priority <= 99:
                raise ValidationError(_('Priority must be between 1 and 99.'))
            if not record.printer_id._allows_company(record.pos_config_id.company_id):
                raise ValidationError(_('This Windows printer is not authorized for the point-of-sale company.'))

    @api.constrains('pos_config_id', 'pos_category_id', 'pos_category_ids', 'active', 'ticket_type')
    def _check_duplicate(self):
        self._check_active_category_ownership()

    @staticmethod
    def _ownership_lock_key(pos_config_id, category_id):
        """Return one stable PostgreSQL advisory-lock key per POS/category."""
        value = '%s:%s' % (pos_config_id, category_id or 'default')
        digest = hashlib.sha256(value.encode('utf-8')).digest()
        return int.from_bytes(digest[:8], 'big', signed=True)

    def _routing_categories(self):
        self.ensure_one()
        # Once the upgrade backfill has completed, the visible M2M relation
        # is the single routing authority.  The legacy field is deliberately
        # not a fallback: clearing the visible selection must make a route a
        # true default route, never leave a hidden historic category active.
        return self.pos_category_ids

    def _check_active_category_ownership(self):
        """Keep each active category (and the optional default) unambiguous.

        ORM constraints alone can race between two administrators.  Acquiring
        a transaction lock before the conflict search serialises competing
        writes for precisely the affected POS/category pair.
        """
        active_routes = self.filtered(lambda route: route.active and route.ticket_type == 'preparation')
        lock_pairs = {
            (route.pos_config_id.id, category.id)
            for route in active_routes for category in route._routing_categories()
        }
        lock_pairs |= {
            (route.pos_config_id.id, False)
            for route in active_routes if not route._routing_categories()
        }
        for pos_config_id, category_id in sorted(lock_pairs):
            self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [self._ownership_lock_key(pos_config_id, category_id)])

        for route in active_routes:
            categories = route._routing_categories()
            if categories:
                for category in categories:
                    duplicate = self.search([
                        ('id', '!=', route.id), ('active', '=', True), ('ticket_type', '=', 'preparation'),
                        ('pos_config_id', '=', route.pos_config_id.id),
                        ('pos_category_ids', 'in', category.id),
                    ], limit=1)
                    if duplicate:
                        raise ValidationError(_('Only one active preparation binding may use this POS category.'))
            else:
                duplicate = self.search([
                    ('id', '!=', route.id), ('active', '=', True), ('ticket_type', '=', 'preparation'),
                    ('pos_config_id', '=', route.pos_config_id.id), ('pos_category_ids', '=', False),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_('Only one active default kitchen binding is allowed for this point of sale.'))

    def action_test_preparation_printer(self):
        self.ensure_one()
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only a system administrator can test direct printing.'))
        if not self.active or self.ticket_type != 'preparation':
            raise ValidationError(_('Choose an active preparation route before testing its printer.'))
        job = self.env['baseer.print.job']._enqueue_test(self.printer_id, self.pos_config_id)
        return {
            'type': 'ir.actions.act_window', 'res_model': 'baseer.print.job',
            'res_id': job.id, 'view_mode': 'form', 'target': 'current',
        }

    def init(self):
        """Backfill legacy category links once the M2M table exists.

        The insert is idempotent. Upgrade preflight stops rather than silently
        choosing a destination whenever historic routes already conflict.
        """
        self.env.cr.execute('''
            INSERT INTO baseer_print_route_pos_category_rel (route_id, category_id)
            SELECT id, pos_category_id
              FROM baseer_print_route
             WHERE pos_category_id IS NOT NULL
            ON CONFLICT DO NOTHING
        ''')
        self.env.cr.execute('''
            SELECT route.pos_config_id, relation.category_id, array_agg(route.id ORDER BY route.id)
              FROM baseer_print_route AS route
              JOIN baseer_print_route_pos_category_rel AS relation ON relation.route_id = route.id
             WHERE route.active = TRUE
               AND route.ticket_type = 'preparation'
             GROUP BY route.pos_config_id, relation.category_id
            HAVING COUNT(*) > 1
        ''')
        duplicate_categories = self.env.cr.fetchall()
        if duplicate_categories:
            raise ValidationError(_(
                'Cannot upgrade preparation routing: an active POS category belongs to more than one route. '
                'Deactivate or correct the overlapping routes, then upgrade again.'
            ))

        self.env.cr.execute('''
            SELECT route.pos_config_id, array_agg(route.id ORDER BY route.id)
              FROM baseer_print_route AS route
             WHERE route.active = TRUE
               AND route.ticket_type = 'preparation'
               AND NOT EXISTS (
                   SELECT 1 FROM baseer_print_route_pos_category_rel AS relation
                    WHERE relation.route_id = route.id
               )
             GROUP BY route.pos_config_id
            HAVING COUNT(*) > 1
        ''')
        duplicate_defaults = self.env.cr.fetchall()
        if duplicate_defaults:
            raise ValidationError(_(
                'Cannot upgrade preparation routing: a point of sale has more than one active default route. '
                'Deactivate or correct the duplicate default routes, then upgrade again.'
            ))

        # The legacy column is a one-way upgrade source, not a second truth.
        # Clearing it prevents any later module upgrade from resurrecting a
        # category that an administrator intentionally removed from the M2M.
        self.env.cr.execute('''
            UPDATE baseer_print_route
               SET pos_category_id = NULL
             WHERE pos_category_id IS NOT NULL
        ''')

    @api.model
    def _select_binding(self, config, categories):
        bindings = self.sudo().search([
            ('pos_config_id', '=', config.id), ('ticket_type', '=', 'preparation'), ('active', '=', True),
            ('printer_id.active', '=', True), ('printer_id.agent_id.active', '=', True),
        ], order='priority, id')
        candidates = bindings.filtered(lambda binding: bool(binding._routing_categories() & categories))
        return candidates[:1] or bindings.filtered(lambda binding: not binding._routing_categories())[:1]
