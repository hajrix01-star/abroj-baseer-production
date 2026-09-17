from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


MAX_CONFIGURATION_RECORDS = 100
MAX_WORKSPACE_ITEMS = 40


# This policy is intentionally an allowlist owned by the source, not an editable
# menu selector.  baseer_access_roles deliberately hides some native menus even
# where an inherited Odoo group might otherwise make them visible.  A workspace
# configuration may arrange and rename only the operational entries approved for
# the role below; extending the catalogue is an auditable code change.
BASEER_WORKSPACE_TARGET_POLICY = {
    'cashier': {
        'baseer_procurement_requests.menu_procurement_catalog': {
            'action_type': 'ir.actions.client',
            'tag': 'baseer_procurement_requests.catalog',
            'icon': 'oi oi-cart',
        },
        'baseer_procurement_requests.menu_procurement_requests': {
            'action_type': 'ir.actions.act_window',
            'icon': 'oi oi-view-list',
        },
        'baseer_pos_summary.menu_summary': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-line-chart',
        },
        'baseer_pos_summary.menu_pos_closure': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-calendar-times-o',
        },
        'baseer_access_roles.menu_pos_advance_entries': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-users',
        },
        'baseer_access_roles.menu_cashier_purchase_batches': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-files-o',
        },
        'spreadsheet_dashboard.spreadsheet_dashboard_menu_dashboard': {
            'action_type': 'ir.actions.client',
            'tag': 'action_spreadsheet_dashboard',
            'dashboard_xmlid': 'baseer_sales_heat_calendar.dashboard_sales_heat_calendar',
            'dashboard_kind': 'sales_heat_calendar',
            'icon': 'fa fa-calendar',
        },
    },
    'accountant': {
        'baseer_procurement_requests.menu_procurement_representative_petty_cash': {
            'action_type': 'ir.actions.client',
            'tag': 'baseer_procurement_requests.representative_petty_cash',
            'icon': 'fa fa-exchange',
        },
        # The native dashboard root is deliberately hidden after BASSER is
        # installed, so this explicit, read-only shortcut is the accountant's
        # approved route to supplier bills and expenses.  Its fixed dashboard
        # XML id prevents a browser from selecting a different dashboard.
        'spreadsheet_dashboard.spreadsheet_dashboard_menu_dashboard': {
            'action_type': 'ir.actions.client',
            'tag': 'action_spreadsheet_dashboard',
            'dashboard_xmlid': 'baseer_purchase_expense_dashboard.dashboard_supplier_bills',
            'dashboard_kind': 'supplier_bills',
            'icon': 'fa fa-pie-chart',
        },
        'baseer_purchase_batch.menu_purchase_batches': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-file-text-o',
        },
        'baseer_access_roles.menu_account_advance_entries': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-users',
        },
        'baseer_pos_summary.menu_summary': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-line-chart',
        },
        'baseer_procurement_requests.menu_procurement_custody': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-briefcase',
            'open_company_pool': True,
        },
        'baseer_procurement_requests.menu_procurement_custody_monthly_statement': {
            'action_type': 'ir.actions.act_window',
            'icon': 'fa fa-calendar-check-o',
        },
    },
}

ROLE_SELECTION = [
    ('cashier', 'Cashier'),
    ('accountant', 'Accountant'),
]


class BasserWorkspaceSection(models.Model):
    _name = 'baseer.basser.workspace.section'
    _description = 'Baseer Workspace Section'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    role = fields.Selection(ROLE_SELECTION, required=True, default='cashier', index=True)
    company_id = fields.Many2one('res.company', index=True, ondelete='cascade')
    sequence = fields.Integer(default=10, index=True)
    active = fields.Boolean(string='Visible in Baseer', default=True, index=True)
    item_ids = fields.One2many('baseer.basser.workspace.item', 'section_id', string='Items')

    @api.model
    def _current_workspace_role(self):
        user = self.env.user
        # A technical Odoo administrator is the system owner of the workspace
        # even when no Baseer preset was assigned to that user.  Otherwise the
        # BASSER root menu can be visible only to an administrator who was also
        # manually given the Owner preset, which is needlessly confusing and
        # prevents safe workspace administration.
        if self.env.su or user.has_group('base.group_system'):
            return 'owner'
        if user.has_group('baseer_access_roles.group_owner'):
            return 'owner'
        if user.has_group('baseer_access_roles.group_cashier'):
            return 'cashier'
        if user.has_group('baseer_access_roles.group_accountant'):
            return 'accountant'
        raise AccessError(_('You are not allowed to use the BASSER workspace.'))

    @api.model
    def _ensure_active_company(self):
        company = self.env.company
        if not company or company not in self.env.companies or company not in self.env.user.company_ids:
            raise AccessError(_('The active company is not available to you.'))
        return company

    def _check_company_scope(self):
        available_company_ids = set(self.env.companies.ids)
        for section in self:
            if section.company_id and section.company_id.id not in available_company_ids:
                raise ValidationError(_('Choose a company available in your current Odoo session.'))

    @api.constrains('company_id', 'role', 'active')
    def _check_section_scope_and_limits(self):
        self._check_company_scope()
        self._enforce_configuration_limits()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._enforce_configuration_limits(enforce_total=True)
        return records

    @api.model
    def _enforce_configuration_limits(self, enforce_total=False):
        section_model = self.sudo()
        item_model = self.env['baseer.basser.workspace.item'].sudo()
        if enforce_total:
            total = section_model.with_context(active_test=False).search_count([])
            total += item_model.with_context(active_test=False).search_count([])
        else:
            total = 0
        if total > MAX_CONFIGURATION_RECORDS:
            raise ValidationError(_(
                'BASSER allows at most %(limit)s configuration records.',
                limit=MAX_CONFIGURATION_RECORDS,
            ))

        companies = self.env['res.company'].sudo().search([])
        for role, _label in ROLE_SELECTION:
            for company in companies:
                item_count = item_model.search_count([
                    ('active', '=', True),
                    ('section_id.active', '=', True),
                    ('section_id.role', '=', role),
                    '|', ('section_id.company_id', '=', False),
                    ('section_id.company_id', '=', company.id),
                ])
                if item_count > MAX_WORKSPACE_ITEMS:
                    raise ValidationError(_(
                        'BASSER allows at most %(limit)s visible items for one role and company.',
                        limit=MAX_WORKSPACE_ITEMS,
                    ))

    @api.model
    def _menu_xmlids(self, menu):
        rows = self.env['ir.model.data'].sudo().search([
            ('model', '=', 'ir.ui.menu'),
            ('res_id', '=', menu.id),
        ])
        return {f'{row.module}.{row.name}' for row in rows}

    @api.model
    def _policy_spec(self, menu, role):
        for xmlid in self._menu_xmlids(menu):
            spec = BASEER_WORKSPACE_TARGET_POLICY.get(role, {}).get(xmlid)
            if spec:
                return spec
        return False

    @api.model
    def _validate_target_definition(self, menu, role, require_model_access=False):
        spec = self._policy_spec(menu, role)
        # Odoo deliberately keeps generic action records unreadable for many
        # operational users.  This is only static action metadata, read after
        # the fixed policy and native-menu eligibility gates; it never reads a
        # target model or lets the browser choose an action.
        action = menu.sudo().action
        if not spec or not action or action.type != spec['action_type']:
            return False
        if action.type == 'ir.actions.client':
            if not action.tag or action.tag != spec.get('tag'):
                return False
            dashboard_xmlid = spec.get('dashboard_xmlid')
            if not dashboard_xmlid:
                return True
            dashboard = self.env.ref(dashboard_xmlid, raise_if_not_found=False)
            if (not dashboard or dashboard._name != 'spreadsheet.dashboard'
                    or dashboard.baseer_dashboard_kind != spec.get('dashboard_kind')
                    or not dashboard.is_published):
                return False
            try:
                dashboard.check_access('read')
                dashboard.check_access_rule('read')
            except AccessError:
                return False
            return True
        if action.type != 'ir.actions.act_window' or not action.res_model:
            return False
        if require_model_access:
            target_model = self.env[action.res_model]
            try:
                target_model.check_access('read')
            except AccessError:
                return False
        return True

    @api.model
    def _available_workspace_items(self):
        role = self._current_workspace_role()
        if role == 'owner':
            return role, []
        company = self._ensure_active_company()
        sections = self.sudo().search([
            ('active', '=', True),
            ('role', '=', role),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='sequence, id')
        native_visible_menu_ids = self.env['ir.ui.menu']._baseer_native_visible_menu_ids()
        available = []
        for section in sections:
            for item in section.item_ids.filtered('active').sorted(lambda record: (record.sequence, record.id)):
                menu = self.env['ir.ui.menu'].browse(item.menu_id.id)
                if menu.id not in native_visible_menu_ids:
                    continue
                if not self._validate_target_definition(menu, role, require_model_access=True):
                    continue
                available.append((section, item, menu))
        if len(available) > MAX_WORKSPACE_ITEMS:
            raise ValidationError(_(
                'BASSER configuration exceeds the safe visible-item limit. Ask an owner to reduce it.'
            ))
        return role, available

    @api.model
    def get_workspace(self):
        role, available = self._available_workspace_items()
        if role == 'owner':
            return {
                'role': role,
                'can_manage': True,
                'sections': [],
            }

        sections = []
        by_section = {}
        for section, item, menu in available:
            payload = by_section.get(section.id)
            if not payload:
                payload = {
                    'id': section.id,
                    'name': section.name,
                    'items': [],
                }
                by_section[section.id] = payload
                sections.append(payload)
            spec = self._policy_spec(menu, role)
            payload['items'].append({
                'id': item.id,
                'name': item.name or menu.name,
                'description': item.description or '',
                'icon': spec['icon'],
            })
        return {
            'role': role,
            'can_manage': False,
            'sections': sections,
        }

    @api.model
    def open_workspace_item(self, item_id):
        if not isinstance(item_id, int):
            raise AccessError(_('The requested workspace item is invalid.'))
        role, available = self._available_workspace_items()
        if role == 'owner':
            raise AccessError(_('Owners manage BASSER from its configuration screen.'))
        target = next((entry for entry in available if entry[1].id == item_id), None)
        if not target:
            raise AccessError(_('This BASSER item is not available to you.'))
        _section, _item, menu = target
        spec = self._policy_spec(menu, role)
        action = menu.sudo().action
        if action.type == 'ir.actions.client':
            client_action = {
                'type': 'ir.actions.client',
                'tag': action.tag,
                'name': menu.name,
            }
            dashboard_xmlid = spec.get('dashboard_xmlid')
            if dashboard_xmlid:
                dashboard = self.env.ref(dashboard_xmlid, raise_if_not_found=False)
                if not dashboard:
                    raise AccessError(_('The approved dashboard is unavailable.'))
                client_action['params'] = {'dashboard_id': dashboard.id}
            return {
                'action': client_action,
            }
        if spec.get('open_company_pool'):
            # The company and target are derived server-side from this fixed,
            # allowlisted workspace card; the browser cannot select either.
            return {
                'action': self.env['baseer.procurement.custody'].action_open_company_pool(),
            }
        return {'action_id': action.id}

    @api.model
    def open_workspace_management(self):
        if self._current_workspace_role() != 'owner':
            raise AccessError(_('Only the owner can manage BASSER.'))
        return {'action_id': self.env.ref('baseer_basser_workspace.action_workspace_section').id}

    def action_open_workspace_items(self):
        """Open the approved commands for this section without exposing others."""
        self._require_workspace_owner()
        self.ensure_one()
        action = self.env.ref('baseer_basser_workspace.action_workspace_item').read()[0]
        action.update({
            'name': _('BASSER commands: %(section)s', section=self.name),
            'domain': [('section_id', '=', self.id)],
            'context': {
                'active_test': False,
                'default_section_id': self.id,
            },
        })
        return action

    def _require_workspace_owner(self):
        if self._current_workspace_role() != 'owner':
            raise AccessError(_('Only the owner can change BASSER visibility.'))

    def action_hide_from_basser(self):
        self._require_workspace_owner()
        self.write({'active': False})
        return True

    def action_show_in_basser(self):
        self._require_workspace_owner()
        self.write({'active': True})
        return True


class BasserWorkspaceItem(models.Model):
    _name = 'baseer.basser.workspace.item'
    _description = 'Baseer Workspace Item'
    _order = 'section_id, sequence, id'

    _section_menu_unique = models.Constraint(
        'unique(section_id, menu_id)',
        'A menu can appear only once in one BASSER section.',
    )

    section_id = fields.Many2one(
        'baseer.basser.workspace.section', required=True, ondelete='cascade', index=True,
    )
    name = fields.Char(translate=True)
    description = fields.Char(translate=True)
    menu_id = fields.Many2one('ir.ui.menu', required=True, ondelete='restrict')
    allowed_menu_ids = fields.Many2many('ir.ui.menu', compute='_compute_allowed_menu_ids')
    sequence = fields.Integer(default=10, index=True)
    active = fields.Boolean(string='Visible in Baseer', default=True, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.section_id._enforce_configuration_limits(enforce_total=True)
        return records

    @api.depends('section_id.role')
    def _compute_allowed_menu_ids(self):
        for item in self:
            xmlids = BASEER_WORKSPACE_TARGET_POLICY.get(item.section_id.role, {})
            menus = self.env['ir.ui.menu']
            for xmlid in xmlids:
                menu = self.env.ref(xmlid, raise_if_not_found=False)
                if menu:
                    menus |= menu
            item.allowed_menu_ids = menus

    @api.constrains('section_id', 'menu_id', 'active')
    def _check_target_and_limits(self):
        for item in self:
            if not item.section_id or not item.menu_id:
                continue
            if not item.section_id._validate_target_definition(
                item.menu_id, item.section_id.role,
            ):
                raise ValidationError(_(
                    'Choose an approved BASSER operation for this role.'
                ))
        self.env['baseer.basser.workspace.section']._enforce_configuration_limits()

    def _require_workspace_owner(self):
        if self.env['baseer.basser.workspace.section']._current_workspace_role() != 'owner':
            raise AccessError(_('Only the owner can change BASSER visibility.'))

    def action_hide_from_basser(self):
        self._require_workspace_owner()
        self.write({'active': False})
        return True

    def action_show_in_basser(self):
        self._require_workspace_owner()
        self.write({'active': True})
        return True
