import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


_SELECTOR_FIELDS = {
    'partner': 'partner_id',
    'partner_tag': 'partner_tag_id',
    'product': 'product_id',
    'product_category': 'product_category_id',
}
_SELECTOR_PRIORITY = {
    'product': 0,
    'product_category': 1,
    'partner': 2,
    'partner_tag': 3,
}
_BLOCKING_OUTCOMES = {'ambiguous', 'unmapped', 'conflict', 'reconcile', 'coverage_gap', 'catalog_mismatch'}
_ACTIVE_CATALOG_VERSION_PARAM = 'baseer_native_spend.active_catalog_version'
_LEGACY_CATALOG_VERSION = 'noorix-v1'


def _baseer_active_catalog_version(env):
    """Return the reviewed catalog used for newly-created rules and previews.

    The parameter is deliberately changed only by the controlled catalog
    transition.  Keeping the legacy default until that transaction commits
    prevents a deployed module from pointing at a catalog that is not ready.
    """
    return env['ir.config_parameter'].sudo().get_param(
        _ACTIVE_CATALOG_VERSION_PARAM,
        _LEGACY_CATALOG_VERSION,
    )


class BaseerSpendMapRule(models.Model):
    """A reviewed registry for future native Odoo distribution models.

    This model deliberately does not write ``account.analytic.distribution.model``.
    It is the review layer that makes an eventual native seed deterministic.
    """

    _name = 'baseer.spend.map.rule'
    _description = 'Spend Classification Map Rule'
    _order = 'company_id, selector_kind, id'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one('res.company', string='Company', index=True,
                                 help='Leave blank only for a shared rule.')
    selector_kind = fields.Selection([
        ('partner', 'Vendor'),
        ('partner_tag', 'Vendor Tag'),
        ('product', 'Product'),
        ('product_category', 'Product Category'),
    ], required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', ondelete='restrict')
    partner_tag_id = fields.Many2one('res.partner.category', string='Vendor Tag', ondelete='restrict')
    product_id = fields.Many2one('product.product', string='Product', ondelete='restrict')
    product_category_id = fields.Many2one('product.category', string='Product Category', ondelete='restrict')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Spend Leaf',
                                          required=True, ondelete='restrict')
    catalog_version = fields.Char(
        required=True,
        default=lambda self: _baseer_active_catalog_version(self.env),
        copy=False,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('retired', 'Retired'),
    ], default='draft', required=True, copy=False, index=True)
    natural_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    note = fields.Text()

    _baseer_spend_map_rule_natural_key_unique = models.Constraint(
        'unique(natural_key)',
        'A map rule already exists for this company scope and selector.',
    )

    @api.depends('company_id', 'selector_kind', 'partner_id', 'partner_tag_id',
                 'product_id', 'product_category_id', 'analytic_account_id')
    def _compute_name(self):
        for rule in self:
            selector = rule._baseer_selector_record()
            scope = rule.company_id.display_name if rule.company_id else _('Shared')
            rule.name = '%s / %s → %s' % (
                scope,
                selector.display_name if selector else _('Incomplete selector'),
                rule.analytic_account_id.display_name if rule.analytic_account_id else _('No leaf'),
            )

    def _baseer_selector_record(self):
        self.ensure_one()
        field_name = _SELECTOR_FIELDS.get(self.selector_kind)
        return self[field_name] if field_name else self.env[field_name or 'res.partner']

    @api.model
    def _baseer_natural_key_from_values(self, values):
        kind = values.get('selector_kind')
        field_name = _SELECTOR_FIELDS.get(kind)
        selector_id = values.get(field_name) if field_name else False
        if not kind or not selector_id:
            raise ValidationError(_('Choose exactly one selector that matches the rule type.'))
        company_id = values.get('company_id') or False
        catalog_version = values.get('catalog_version') or _baseer_active_catalog_version(self.env)
        scope = 'company:%s' % company_id if company_id else 'shared'
        return '%s:%s:%s:%s' % (catalog_version, scope, kind, selector_id)

    def _baseer_rule_values(self):
        self.ensure_one()
        values = {
            'company_id': self.company_id.id,
            'selector_kind': self.selector_kind,
            'partner_id': self.partner_id.id,
            'partner_tag_id': self.partner_tag_id.id,
            'product_id': self.product_id.id,
            'product_category_id': self.product_category_id.id,
            'catalog_version': self.catalog_version,
        }
        return values

    def _baseer_validate_shape(self):
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        for rule in self:
            expected = _SELECTOR_FIELDS.get(rule.selector_kind)
            selected = [field_name for field_name in _SELECTOR_FIELDS.values() if rule[field_name]]
            if expected is None or selected != [expected]:
                raise ValidationError(_('Choose exactly one selector that matches the rule type.'))
            if (not root or rule.analytic_account_id.root_plan_id != root
                    or rule.analytic_account_id.plan_id == root):
                raise ValidationError(_('The destination must be an active leaf under Spend Classification.'))
            if not rule.analytic_account_id.active:
                raise ValidationError(_('The destination analytic account must be active.'))
            if rule.analytic_account_id.company_id and rule.analytic_account_id.company_id != rule.company_id:
                raise ValidationError(_('A company rule may only use a shared leaf or a leaf of the same company.'))
            selector = rule._baseer_selector_record()
            if (hasattr(selector, 'company_id') and selector.company_id
                    and (not rule.company_id or selector.company_id != rule.company_id)):
                raise ValidationError(_('A company rule may only select a record of the same company or a shared record.'))

    def _baseer_require_shared_scope_authority(self):
        """A shared map changes every company, so a one-company manager cannot create it."""
        active_companies = self.env['res.company'].sudo().search([('active', '=', True)])
        if not active_companies <= self.env.user.company_ids:
            raise AccessError(_('A shared rule requires access to every active company.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can manage spend mapping rules.'))
        prepared = []
        natural_keys = set()
        for values in vals_list:
            values = dict(values)
            values.setdefault('catalog_version', _baseer_active_catalog_version(self.env))
            if values.get('state', 'draft') != 'draft':
                raise AccessError(_('Rules must be created in draft.'))
            if not values.get('company_id'):
                self._baseer_require_shared_scope_authority()
            values['natural_key'] = self._baseer_natural_key_from_values(values)
            if values['natural_key'] in natural_keys or self.search_count([
                ('natural_key', '=', values['natural_key']),
            ]):
                raise ValidationError(_('A map rule already exists for this company scope and selector.'))
            natural_keys.add(values['natural_key'])
            prepared.append(values)
        rules = super().create(prepared)
        rules._baseer_validate_shape()
        return rules

    def write(self, vals):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can manage spend mapping rules.'))
        if any(rule.state != 'draft' for rule in self) or 'state' in vals:
            raise AccessError(_('Approved and retired rules are immutable. Retire an approved rule instead.'))
        if vals.get('company_id') is False or ('company_id' in vals and not vals['company_id']):
            self._baseer_require_shared_scope_authority()
        result = super().write(vals)
        for rule in self:
            rule._baseer_validate_shape()
            key = self._baseer_natural_key_from_values(rule._baseer_rule_values())
            if rule.natural_key != key:
                # Explicitly invoke the ORM base method; never trust a client context flag.
                super(BaseerSpendMapRule, rule).write({'natural_key': key})
        return result

    def unlink(self):
        if any(rule.state != 'draft' for rule in self):
            raise AccessError(_('Approved and retired rules are retained as audit evidence.'))
        return super().unlink()

    def _baseer_require_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can approve spend mapping.'))

    def action_approve(self):
        self._baseer_require_manager()
        if any(rule.state != 'draft' for rule in self):
            raise UserError(_('Only draft rules can be approved.'))
        if any(not rule.company_id for rule in self):
            self._baseer_require_shared_scope_authority()
        self._baseer_validate_shape()
        super(BaseerSpendMapRule, self).write({
            'state': 'approved',
            'approved_by_id': self.env.user.id,
            'approved_at': fields.Datetime.now(),
        })

    def action_retire(self):
        self._baseer_require_manager()
        if any(rule.state != 'approved' for rule in self):
            raise UserError(_('Only approved rules can be retired.'))
        if any(not rule.company_id for rule in self):
            self._baseer_require_shared_scope_authority()
        super(BaseerSpendMapRule, self).write({'state': 'retired'})


class BaseerSpendMapRun(models.Model):
    _name = 'baseer.spend.map.run'
    _description = 'Spend Classification Readiness Run'
    _order = 'create_date desc, id desc'

    name = fields.Char(required=True, default=lambda self: _('Spend map preview'))
    company_id = fields.Many2one('res.company', required=True, index=True, ondelete='restrict')
    catalog_version = fields.Char(
        required=True,
        default=lambda self: _baseer_active_catalog_version(self.env),
        copy=False,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('generated', 'Generated'),
        ('ready', 'Ready for approval'),
        ('blocked', 'Blocked'),
        ('stale', 'Stale'),
        ('approved', 'Approved'),
    ], default='draft', required=True, readonly=True, copy=False, index=True)
    snapshot_hash = fields.Char(readonly=True, copy=False)
    catalog_hash = fields.Char(readonly=True, copy=False)
    is_stale = fields.Boolean(readonly=True, copy=False)
    stale_at = fields.Datetime(readonly=True, copy=False)
    generated_at = fields.Datetime(readonly=True, copy=False)
    generated_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one('res.users', readonly=True, copy=False)
    line_ids = fields.One2many('baseer.spend.map.preview.line', 'run_id', readonly=True)
    freshness_check_ids = fields.One2many('baseer.spend.map.freshness.check', 'run_id', readonly=True)
    total_count = fields.Integer(readonly=True)
    resolved_count = fields.Integer(readonly=True)
    blocked_count = fields.Integer(readonly=True)
    note = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can create a readiness run.'))
        for values in vals_list:
            if values.get('state', 'draft') != 'draft':
                raise AccessError(_('Readiness runs must be created in draft.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can manage readiness runs.'))
        protected = {'state', 'snapshot_hash', 'catalog_hash', 'line_ids', 'generated_at',
                     'generated_by_id', 'approved_at', 'approved_by_id', 'is_stale', 'stale_at',
                     'total_count', 'resolved_count', 'blocked_count'}
        if any(run.state != 'draft' for run in self) or protected & set(vals):
            raise AccessError(_('Generated readiness evidence is immutable. Create a new run instead.'))
        return super().write(vals)

    def unlink(self):
        if any(run.state != 'draft' for run in self):
            raise AccessError(_('Generated and approved readiness runs are retained as audit evidence.'))
        return super().unlink()

    def _baseer_require_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only Accounting Managers can approve readiness.'))

    def _baseer_snapshot_hash(self):
        self.ensure_one()
        company = self.company_id
        Supplier = self.env['res.partner'].sudo()
        Rule = self.env['baseer.spend.map.rule'].sudo()
        Product = self.env['product.product'].sudo()
        Category = self.env['product.category'].sudo()
        Native = self.env['account.analytic.distribution.model'].sudo()
        Account = self.env['account.analytic.account'].sudo()
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)

        suppliers = Supplier.search([
            ('active', '=', True), ('supplier_rank', '>', 0),
            ('company_id', 'in', [False, company.id]),
        ])
        rules = Rule.search([
            ('company_id', 'in', [False, company.id]),
            ('catalog_version', '=', self.catalog_version),
        ])
        products = Product.search([('active', '=', True), ('company_id', 'in', [False, company.id])])
        categories = Category.search([])
        native_models = Native.search([('company_id', 'in', [False, company.id])])
        accounts = Account.search([('root_plan_id', '=', root.id)]) if root else Account.browse()
        pair_sources = self._baseer_pair_sources()

        payload = {
            'company': [company.id, str(company.write_date)],
            'suppliers': [(r.id, str(r.write_date), sorted(r.category_id.ids)) for r in suppliers],
            'catalog_version': self.catalog_version,
            'rules': [(r.id, str(r.write_date), r.natural_key, r.catalog_version,
                       r.analytic_account_id.id, r.state) for r in rules],
            'products': [(r.id, str(r.write_date), r.categ_id.id) for r in products],
            'categories': [(r.id, str(r.write_date), r.parent_id.id) for r in categories],
            'native_models': [(r.id, str(r.write_date), r.company_id.id, r.partner_id.id,
                               r.partner_category_id.id, r.product_id.id, r.product_categ_id.id,
                               r.analytic_distribution) for r in native_models],
            'accounts': [(r.id, str(r.write_date), r.company_id.id, r.active) for r in accounts],
            'supplier_product_pairs': sorted([
                (partner_id, product_id, tuple(
                    (item['kind'], item['id'], item['write_date']) for item in sources
                )) for (partner_id, product_id), sources in pair_sources.items()
            ]),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(',', ':'))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _baseer_catalog_hash(self):
        """Immutable fingerprint of the exact catalog selected by this run."""
        self.ensure_one()
        rules = self.env['baseer.spend.map.rule'].sudo().search([
            ('company_id', 'in', [False, self.company_id.id]),
            ('catalog_version', '=', self.catalog_version),
        ])
        payload = [(rule.natural_key, rule.state, rule.analytic_account_id.id,
                    str(rule.write_date)) for rule in rules]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def _baseer_pair_sources(self):
        """Return only evidence that belongs to this company.

        Both this function and the preview use this exact source, keeping the
        snapshot freshness guarantee aligned with supplier-product evidence.
        """
        self.ensure_one()
        sources = {}
        MoveLine = self.env['account.move.line'].sudo()
        for line in MoveLine.search([
            ('move_id.company_id', '=', self.company_id.id),
            ('move_id.state', '=', 'posted'),
            ('move_id.move_type', 'in', ('in_invoice', 'in_refund')),
            ('display_type', '=', 'product'),
            ('move_id.partner_id', '!=', False), ('product_id', '!=', False),
        ]):
            partner = line.move_id.partner_id
            product = line.product_id
            if (partner.company_id and partner.company_id != self.company_id
                    or product.company_id and product.company_id != self.company_id):
                continue
            sources.setdefault((partner.id, product.id), []).append({
                'kind': 'posted_bill', 'id': line.id, 'write_date': str(line.write_date),
            })
        for info in self.env['product.supplierinfo'].sudo().search([
            ('partner_id', '!=', False), ('company_id', 'in', [False, self.company_id.id]),
        ]):
            partner = info.partner_id
            if (info.company_id and info.company_id != self.company_id
                    or partner.company_id and partner.company_id != self.company_id):
                continue
            for product in (info.product_id or info.product_tmpl_id.product_variant_ids):
                if not product.active or (product.company_id and product.company_id != self.company_id):
                    continue
                sources.setdefault((partner.id, product.id), []).append({
                    'kind': 'supplierinfo', 'id': info.id, 'write_date': str(info.write_date),
                })
        return {key: sorted(value, key=lambda item: (item['kind'], item['id'])) for key, value in sources.items()}

    def _baseer_native_destinations(self, model, root):
        destinations = set()
        for key in (model.analytic_distribution or {}):
            for account_id in key.split(','):
                account = self.env['account.analytic.account'].sudo().browse(int(account_id)).exists()
                if account and account.root_plan_id == root:
                    destinations.add(account.id)
        return destinations

    def _baseer_category_matches(self, category, expected):
        return bool(category and expected and category.parent_path and expected.parent_path
                    and category.parent_path.startswith(expected.parent_path))

    def _baseer_model_matches(self, model, partner=False, product=False, category=False):
        if model.partner_id and model.partner_id != partner:
            return False
        if model.partner_category_id and (not partner or model.partner_category_id not in partner.category_id):
            return False
        if model.product_id and model.product_id != product:
            return False
        if model.product_categ_id:
            actual_category = product.categ_id if product else category
            if not self._baseer_category_matches(actual_category, model.product_categ_id):
                return False
        # Prefix-specific models require an account context and remain a
        # deliberate reconciliation item rather than a guessed match here.
        if model.account_prefix:
            return False
        return True

    def _baseer_rule_matches(self, rule, partner=False, product=False, category=False):
        if rule.selector_kind == 'partner':
            return rule.partner_id == partner
        if rule.selector_kind == 'partner_tag':
            return bool(partner and rule.partner_tag_id in partner.category_id)
        if rule.selector_kind == 'product':
            return rule.product_id == product
        if rule.selector_kind == 'product_category':
            actual_category = product.categ_id if product else category
            return self._baseer_category_matches(actual_category, rule.product_category_id)
        return False

    def _baseer_candidate_lines(self, partner=False, product=False, category=False):
        self.ensure_one()
        root = self.env.ref('baseer_native_spend.spend_plan', raise_if_not_found=False)
        rules = self.env['baseer.spend.map.rule'].sudo().search([
            ('state', 'in', ['draft', 'approved']),
            ('company_id', 'in', [False, self.company_id.id]),
            ('catalog_version', '=', self.catalog_version),
        ])
        configured = []
        for rule in rules:
            if self._baseer_rule_matches(rule, partner, product, category):
                configured.append({
                    'source': 'rule', 'record': rule,
                    'level': _SELECTOR_PRIORITY[rule.selector_kind],
                    'scope': 0 if rule.company_id else 1,
                    'destinations': {rule.analytic_account_id.id},
                })
        native = []
        models = self.env['account.analytic.distribution.model'].sudo().search([
            ('company_id', 'in', [False, self.company_id.id]),
        ])
        for model in models:
            if not root or not self._baseer_model_matches(model, partner, product, category):
                continue
            if model.product_id:
                kind = 'product'
            elif model.product_categ_id:
                kind = 'product_category'
            elif model.partner_id:
                kind = 'partner'
            elif model.partner_category_id:
                kind = 'partner_tag'
            else:
                kind = 'partner_tag'
            destinations = self._baseer_native_destinations(model, root)
            if destinations:
                native.append({
                    'source': 'native', 'record': model,
                    'level': _SELECTOR_PRIORITY[kind],
                    'scope': 0 if model.company_id else 1,
                    'destinations': destinations,
                })
        return configured, native

    def _baseer_evaluate_context(self, partner=False, product=False, tag=False, category=False):
        configured, native = self._baseer_candidate_lines(partner, product, category)
        candidate_rule_ids = [candidate['record'].id for candidate in configured]
        candidate_native_ids = [candidate['record'].id for candidate in native]
        result = {
            'partner_id': partner.id if partner else False,
            'product_id': product.id if product else False,
            'product_category_id': category.id if category else (product.categ_id.id if product else False),
            'partner_tag_id': tag.id if tag else False,
            'candidate_rule_ids': [(6, 0, candidate_rule_ids)],
            'candidate_native_model_ids': [(6, 0, candidate_native_ids)],
        }

        def seal(outcome, message):
            # Store a readable, immutable capture; relational fields are only
            # navigation conveniences and may change after this run.
            winner = result.get('selected_analytic_account_id') or False
            payload = {
                'catalog_version': self.catalog_version,
                'context': {
                    'partner': partner and [partner.id, partner.display_name],
                    'product': product and [product.id, product.display_name],
                    'category': (category or (product and product.categ_id)) and [
                        (category or product.categ_id).id,
                        (category or product.categ_id).display_name,
                    ],
                    'tag': tag and [tag.id, tag.display_name],
                },
                'candidates': [{
                    'source': item['source'], 'id': item['record'].id,
                    'natural_key': getattr(item['record'], 'natural_key', False),
                    'selector_kind': getattr(item['record'], 'selector_kind', False),
                    'catalog_version': getattr(item['record'], 'catalog_version', False),
                    'destinations': sorted(item['destinations']),
                } for item in configured + native],
                'winner_leaf_id': winner,
                'outcome': outcome,
            }
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str,
                                 separators=(',', ':'))
            result.update(outcome=outcome, message=message, evidence_json=payload,
                          evidence_hash=hashlib.sha256(encoded.encode()).hexdigest())
            return result
        if configured:
            rank = min((candidate['level'], candidate['scope']) for candidate in configured)
            winners = [candidate for candidate in configured if (candidate['level'], candidate['scope']) == rank]
            destinations = set().union(*(candidate['destinations'] for candidate in winners))
            result['selected_analytic_account_id'] = next(iter(destinations)) if len(destinations) == 1 else False
            if len(destinations) != 1:
                return seal('ambiguous', _('Winning rules point to different Spend Classification leaves.'))
            native_destinations = set().union(*(candidate['destinations'] for candidate in native)) if native else set()
            if native_destinations and native_destinations != destinations:
                return seal('conflict', _('The reviewed map conflicts with an existing native Odoo distribution model.'))
            if any(candidate['record'].state != 'approved' for candidate in winners):
                return seal('reconcile', _('The selected map rule is still draft and must be approved before readiness.'))
            return seal('resolved', _('One reviewed destination was selected without a tie.'))
        if native:
            return seal('reconcile', _('Existing native Odoo model found. Reconcile it into the reviewed map before activation.'))
        # An untagged vendor never inherits a tag fallback.  Explicit product
        # and vendor rules above remain valid and deliberately take precedence.
        if partner and not partner.category_id:
            return seal('unmapped', _('Vendor has no classification tag or explicit mapping.'))
        if product or category:
            return seal('not_applicable', _('No product rule applies without a supplier context.'))
        return seal('unmapped', _('No approved or draft mapping rule applies to this vendor context.'))

    def _baseer_preview_values(self):
        self.ensure_one()
        Supplier = self.env['res.partner'].sudo()
        Product = self.env['product.product'].sudo()
        Category = self.env['product.category'].sudo()
        suppliers = Supplier.search([
            ('active', '=', True), ('supplier_rank', '>', 0),
            ('company_id', 'in', [False, self.company_id.id]),
        ])
        products = Product.search([('active', '=', True), ('company_id', 'in', [False, self.company_id.id])])
        categories = Category.search([])
        values = []
        for partner in suppliers:
            row = self._baseer_evaluate_context(partner=partner)
            row.update(context_kind='supplier_no_product')
            values.append(row)
            for tag in partner.category_id:
                row = self._baseer_evaluate_context(partner=partner, tag=tag)
                row.update(context_kind='supplier_tag')
                values.append(row)
        for product in products:
            row = self._baseer_evaluate_context(product=product, category=product.categ_id)
            row.update(context_kind='product')
            values.append(row)
        for category in categories:
            row = self._baseer_evaluate_context(category=category)
            row.update(context_kind='product_category')
            values.append(row)

        # Evaluate actual vendor × product contexts only.  The tuples are
        # evidence from posted vendor bills and supplierinfo, never a guessed
        # Cartesian product.  This is the context Odoo will use when a bill
        # has both a supplier and a product.
        pair_sources = self._baseer_pair_sources()
        for (partner_id, product_id), source in sorted(pair_sources.items()):
            partner = Supplier.browse(partner_id).exists()
            product = Product.browse(product_id).exists()
            if not partner or not product:
                continue
            row = self._baseer_evaluate_context(partner=partner, product=product, category=product.categ_id)
            row.update(context_kind='supplier_product')
            row['evidence_json']['relationship_sources'] = source
            encoded = json.dumps(row['evidence_json'], ensure_ascii=False, sort_keys=True,
                                 default=str, separators=(',', ':'))
            row['evidence_hash'] = hashlib.sha256(encoded.encode()).hexdigest()
            values.append(row)

        rules = self.env['baseer.spend.map.rule'].sudo().search([
            ('state', 'in', ['draft', 'approved']),
            ('company_id', 'in', [False, self.company_id.id]),
            ('catalog_version', '=', self.catalog_version),
        ])
        has_product = any(rule.selector_kind in ('product', 'product_category') for rule in rules)
        has_supplier = any(rule.selector_kind in ('partner', 'partner_tag') for rule in rules)
        if has_product and has_supplier and not pair_sources:
            payload = {'catalog_version': self.catalog_version, 'reason': 'no_supplier_product_evidence'}
            encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            values.append({
                'context_kind': 'coverage_gap',
                'outcome': 'coverage_gap',
                'message': _('Product and supplier rules coexist, but no supplier-product relationship was found for coverage.'),
                'evidence_json': payload,
                'evidence_hash': hashlib.sha256(encoded.encode()).hexdigest(),
            })
        return values

    def _baseer_write_preview(self, values):
        self.ensure_one()
        # Server-side base ORM calls are intentional.  Context must never be
        # treated as a capability because RPC clients can forge it.
        super(BaseerSpendMapPreviewLine, self.line_ids).unlink()
        for value in values:
            value['run_id'] = self.id
        Preview = self.env['baseer.spend.map.preview.line']
        super(BaseerSpendMapPreviewLine, Preview).create(values)
        lines = self.line_ids
        blocked = lines.filtered(lambda line: line.outcome in _BLOCKING_OUTCOMES)
        resolved = lines.filtered(lambda line: line.outcome == 'resolved')
        state = 'ready' if not blocked else 'blocked'
        super(BaseerSpendMapRun, self).write({
            'state': state,
            'snapshot_hash': self._baseer_snapshot_hash(),
            'catalog_hash': self._baseer_catalog_hash(),
            'generated_at': fields.Datetime.now(),
            'generated_by_id': self.env.user.id,
            'is_stale': False,
            'stale_at': False,
            'total_count': len(lines),
            'resolved_count': len(resolved),
            'blocked_count': len(blocked),
        })

    def action_generate_preview(self):
        self._baseer_require_manager()
        for run in self:
            if run.state not in ('draft', 'stale', 'blocked', 'generated', 'ready'):
                raise UserError(_('An approved run is immutable. Create a new run for a new snapshot.'))
            run._baseer_write_preview(run._baseer_preview_values())

    def action_check_stale(self):
        self._baseer_require_manager()
        for run in self:
            if not run.snapshot_hash:
                raise UserError(_('Generate the preview before checking its freshness.'))
            current_hash = run._baseer_snapshot_hash()
            stale = run.snapshot_hash != current_hash or run.catalog_hash != run._baseer_catalog_hash()
            Check = self.env['baseer.spend.map.freshness.check']
            super(BaseerSpendMapFreshnessCheck, Check).create({
                'run_id': run.id, 'snapshot_hash': current_hash, 'is_stale': stale,
                'checked_at': fields.Datetime.now(), 'checked_by_id': self.env.user.id,
            })
            # Approved evidence is immutable forever.  A fresh check is a
            # separate audit record; only a non-approved working run may move
            # to stale and require regeneration.
            if stale and run.state != 'approved':
                super(BaseerSpendMapRun, run).write({
                    'state': 'stale', 'is_stale': True, 'stale_at': fields.Datetime.now(),
                })

    def action_approve(self):
        self._baseer_require_manager()
        for run in self:
            if run.state != 'ready' or run.blocked_count:
                raise UserError(_('Only a complete, unblocked readiness run can be approved.'))
            if (run.is_stale or run.catalog_hash != run._baseer_catalog_hash()
                    or run.snapshot_hash != run._baseer_snapshot_hash()):
                super(BaseerSpendMapRun, run).write({
                    'state': 'stale', 'is_stale': True, 'stale_at': fields.Datetime.now(),
                })
                raise UserError(_('The source data changed after the preview. Generate a new preview.'))
            super(BaseerSpendMapRun, run).write({
                'state': 'approved',
                'approved_by_id': self.env.user.id,
                'approved_at': fields.Datetime.now(),
            })


class BaseerSpendMapFreshnessCheck(models.Model):
    """Append-only freshness evidence; it never changes an approved run."""

    _name = 'baseer.spend.map.freshness.check'
    _description = 'Spend Map Freshness Check'
    _order = 'checked_at desc, id desc'

    run_id = fields.Many2one('baseer.spend.map.run', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True, readonly=True)
    snapshot_hash = fields.Char(required=True, readonly=True, copy=False)
    is_stale = fields.Boolean(required=True, readonly=True, copy=False)
    checked_at = fields.Datetime(required=True, readonly=True, copy=False)
    checked_by_id = fields.Many2one('res.users', required=True, readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Freshness checks are created by the readiness action only.'))

    def write(self, vals):
        raise AccessError(_('Freshness checks are append-only audit evidence.'))

    def unlink(self):
        raise AccessError(_('Freshness checks are retained as audit evidence.'))


class BaseerSpendMapPreviewLine(models.Model):
    _name = 'baseer.spend.map.preview.line'
    _description = 'Spend Classification Preview Line'
    _order = 'run_id, context_kind, id'

    run_id = fields.Many2one('baseer.spend.map.run', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='run_id.company_id', store=True, readonly=True)
    context_kind = fields.Selection([
        ('supplier_no_product', 'Vendor without product'),
        ('supplier_tag', 'Vendor tag'),
        ('product', 'Product'),
        ('product_category', 'Product category'),
        ('supplier_product', 'Vendor and product'),
        ('coverage_gap', 'Coverage gap'),
        ('catalog_mismatch', 'Catalog mismatch'),
    ], required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', readonly=True)
    partner_tag_id = fields.Many2one('res.partner.category', readonly=True)
    product_id = fields.Many2one('product.product', readonly=True)
    product_category_id = fields.Many2one('product.category', readonly=True)
    candidate_rule_ids = fields.Many2many(
        'baseer.spend.map.rule', 'baseer_spend_map_preview_rule_rel',
        'preview_id', 'rule_id', readonly=True,
    )
    candidate_native_model_ids = fields.Many2many(
        'account.analytic.distribution.model', 'baseer_spend_map_preview_native_rel',
        'preview_id', 'native_model_id', readonly=True,
    )
    selected_analytic_account_id = fields.Many2one('account.analytic.account', readonly=True)
    outcome = fields.Selection([
        ('resolved', 'Resolved'),
        ('ambiguous', 'Ambiguous'),
        ('unmapped', 'Unmapped'),
        ('conflict', 'Conflict'),
        ('reconcile', 'Needs reconciliation'),
        ('coverage_gap', 'Coverage gap'),
        ('not_applicable', 'Not applicable alone'),
    ], required=True, readonly=True, index=True)
    message = fields.Text(readonly=True)
    evidence_json = fields.Json(readonly=True, copy=False)
    evidence_hash = fields.Char(readonly=True, copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Preview evidence is generated by a readiness run only.'))

    def write(self, vals):
        raise AccessError(_('Preview evidence is immutable. Generate a new run instead.'))

    def unlink(self):
        raise AccessError(_('Preview evidence is immutable. Generate a new run instead.'))
