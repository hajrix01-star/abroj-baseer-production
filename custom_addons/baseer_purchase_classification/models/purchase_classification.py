"""Company-scoped immutable analytical classifications for supplier-bill lines.

This addon never writes native accounting lines.  ``account.move.line`` keeps
authority for amount, VAT, currency, refund sign and posting state.
"""
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


BASIS_POINTS = 10000


class BaseerPurchaseReportingRule(models.Model):
    _name = 'baseer.purchase.reporting.rule'
    _description = 'Purchase reporting rule'
    _order = 'company_id, target_kind, target_key'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda self: self.env.company, ondelete='restrict')
    target_kind = fields.Selection([
        ('supplier_category', 'Supplier category'),
        ('product_category', 'Product category'),
    ], required=True, default='supplier_category', index=True)
    supplier_category_map_id = fields.Many2one('baseer.purchase.category.map', ondelete='restrict',
                                                check_company=True, index=True)
    product_category_id = fields.Many2one('product.category', ondelete='restrict', index=True)
    target_key = fields.Char(required=True, readonly=True, index=True, copy=False)
    reporting_category_map_id = fields.Many2one('baseer.purchase.category.map', required=True,
                                                 ondelete='restrict', check_company=True, index=True)
    reporting_type = fields.Selection([
        ('purchase', 'Purchase'), ('expense', 'Expense'), ('excluded', 'Excluded'),
    ], required=True, default='purchase', index=True)
    active = fields.Boolean(default=True, index=True)

    _target_uniq = models.Constraint(
        'UNIQUE(company_id, target_kind, target_key)',
        'A reporting rule already exists for this company target.',
    )

    @api.model
    def _baseer_require_manager(self):
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can configure purchase reporting rules.'))

    @api.model
    def _baseer_require_allowed_company(self, company):
        """Reject a forged company id before a record rule has a record to check."""
        if not company or company not in self.env.companies:
            raise AccessError(_('Choose a company that is enabled for your user.'))
        return company

    @api.model
    def _baseer_prepare_target_values(self, values):
        values = dict(values)
        kind = values.get('target_kind', 'supplier_category')
        supplier_category = self.env['baseer.purchase.category.map'].browse(
            values.get('supplier_category_map_id')
        ).exists()
        product_category = values.get('product_category_id')
        reporting_category = self.env['baseer.purchase.category.map'].browse(
            values.get('reporting_category_map_id')
        ).exists()
        company = self.env['res.company'].browse(values.get('company_id') or self.env.company.id).exists()
        self._baseer_require_allowed_company(company)
        if not reporting_category or reporting_category.company_id != company or not reporting_category.active:
            raise ValidationError(_('Choose one active reporting category for this company.'))
        if kind == 'supplier_category':
            if not supplier_category or product_category or supplier_category.company_id != company:
                raise ValidationError(_('Choose exactly one supplier category for this company.'))
            if reporting_category != supplier_category:
                raise ValidationError(_('A supplier category rule must report through the same category.'))
            target_id = supplier_category.id
        elif kind == 'product_category':
            if not product_category or supplier_category:
                raise ValidationError(_('Choose exactly one product category target.'))
            if reporting_category.category_id != self.env['product.category'].browse(product_category).exists():
                raise ValidationError(_('A product category rule must report through the same category.'))
            target_id = product_category
        else:
            raise ValidationError(_('Choose a valid reporting rule target.'))
        values['target_key'] = str(target_id)
        return values

    @api.model_create_multi
    def create(self, vals_list):
        self._baseer_require_manager()
        prepared = []
        for values in vals_list:
            company = self.env['res.company'].browse(values.get('company_id') or self.env.company.id).exists()
            self._baseer_require_allowed_company(company)
            prepared.append(self._baseer_prepare_target_values(values))
        return super().create(prepared)

    def write(self, values):
        self._baseer_require_manager()
        for rule in self:
            self._baseer_require_allowed_company(rule.company_id)
            candidate = {
                'company_id': rule.company_id.id,
                'target_kind': rule.target_kind,
                'supplier_category_map_id': rule.supplier_category_map_id.id,
                'product_category_id': rule.product_category_id.id,
                'reporting_category_map_id': rule.reporting_category_map_id.id,
            }
            candidate.update(values)
            company = self.env['res.company'].browse(
                candidate.get('company_id') or rule.company_id.id
            ).exists()
            self._baseer_require_allowed_company(company)
            prepared = self._baseer_prepare_target_values(candidate)
            final_values = dict(values)
            final_values.update({key: prepared[key] for key in (
                'target_kind', 'supplier_category_map_id', 'product_category_id',
                'reporting_category_map_id', 'target_key',
            )})
            super(BaseerPurchaseReportingRule, rule).write(final_values)
        return True

    def unlink(self):
        self._baseer_require_manager()
        for rule in self:
            self._baseer_require_allowed_company(rule.company_id)
        return super().unlink()


class BaseerPurchaseLineClassificationCase(models.Model):
    _name = 'baseer.purchase.line.classification.case'
    _description = 'Purchase line analytical classification case'
    _order = 'company_id, source_line_id'
    _check_company_auto = True

    source_line_id = fields.Many2one('account.move.line', required=True, readonly=True, index=True,
                                     ondelete='restrict', check_company=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True,
                                 ondelete='restrict')
    current_snapshot_id = fields.Many2one('baseer.purchase.line.classification', readonly=True,
                                          ondelete='restrict', check_company=True)

    _source_line_uniq = models.Constraint(
        'UNIQUE(source_line_id)', 'A classification case already exists for this source line.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Classification cases are created only from the protected posting service.'))

    def write(self, values):
        raise AccessError(_('Classification cases are managed only by the protected posting service.'))

    def unlink(self):
        raise AccessError(_('Classification cases are immutable analytical history.'))


class BaseerPurchaseLineClassification(models.Model):
    _name = 'baseer.purchase.line.classification'
    _description = 'Purchase line analytical classification snapshot'
    _order = 'case_id, version'
    _check_company_auto = True

    case_id = fields.Many2one('baseer.purchase.line.classification.case', required=True, readonly=True,
                              index=True, ondelete='restrict', check_company=True)
    source_line_id = fields.Many2one(related='case_id.source_line_id', store=True, readonly=True, index=True)
    company_id = fields.Many2one(related='case_id.company_id', store=True, readonly=True, index=True)
    version = fields.Integer(required=True, readonly=True)
    decision_source = fields.Selection([
        ('supplier_rule', 'Supplier rule'), ('product_rule', 'Product rule'),
        ('manager_override', 'Manager override'), ('manager_allocation', 'Manager allocation'),
        ('unclassified', 'Unclassified'),
    ], required=True, readonly=True, index=True)
    reason = fields.Char(readonly=True)
    leg_ids = fields.One2many('baseer.purchase.line.classification.leg', 'snapshot_id', readonly=True)
    created_by_id = fields.Many2one('res.users', required=True, readonly=True, ondelete='restrict')
    created_at = fields.Datetime(required=True, readonly=True)

    _case_version_uniq = models.Constraint(
        'UNIQUE(case_id, version)', 'A classification snapshot version already exists for this source line.'
    )

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Classification snapshots are created only from the protected posting service.'))

    def write(self, values):
        raise AccessError(_('Classification snapshots are immutable. Create a later correction instead.'))

    def unlink(self):
        raise AccessError(_('Classification snapshots are immutable.'))


class BaseerPurchaseLineClassificationLeg(models.Model):
    _name = 'baseer.purchase.line.classification.leg'
    _description = 'Purchase line analytical classification allocation'
    _order = 'snapshot_id, sequence, id'
    _check_company_auto = True

    snapshot_id = fields.Many2one('baseer.purchase.line.classification', required=True, readonly=True,
                                  index=True, ondelete='restrict', check_company=True)
    company_id = fields.Many2one(related='snapshot_id.company_id', store=True, readonly=True, index=True)
    sequence = fields.Integer(required=True, readonly=True, default=10)
    rule_id = fields.Many2one('baseer.purchase.reporting.rule', readonly=True, ondelete='restrict',
                              check_company=True)
    reporting_type = fields.Selection([
        ('purchase', 'Purchase'), ('expense', 'Expense'), ('excluded', 'Excluded'),
        ('unclassified', 'Unclassified'),
    ], required=True, readonly=True, index=True)
    reporting_category_id = fields.Many2one('product.category', readonly=True, ondelete='restrict', index=True)
    reporting_category_name = fields.Char(required=True, readonly=True)
    reporting_parent_category_id = fields.Many2one('product.category', readonly=True,
                                                    ondelete='restrict', index=True)
    reporting_parent_category_name = fields.Char(readonly=True)
    basis_points = fields.Integer(required=True, readonly=True, default=BASIS_POINTS)

    @api.constrains('basis_points')
    def _baseer_check_basis_points(self):
        for leg in self:
            if not 1 <= leg.basis_points <= BASIS_POINTS:
                raise ValidationError(_('Allocation percentage must be from 0.01% to 100.00%.'))

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Classification allocations are created only from the protected posting service.'))

    def write(self, values):
        raise AccessError(_('Classification allocations are immutable.'))

    def unlink(self):
        raise AccessError(_('Classification allocations are immutable.'))


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_post(self):
        result = super().action_post()
        moves = self.filtered(lambda move: move.state == 'posted')
        self.env['baseer.purchase.line.classification']._baseer_capture_posted_moves(moves)
        return result


class BaseerPurchaseClassificationService(models.Model):
    _inherit = 'baseer.purchase.line.classification'

    @api.model
    def _baseer_rule_for_line(self, line):
        """Use a rule only when its source is explicit and unambiguous."""
        Rule = self.env['baseer.purchase.reporting.rule'].sudo()
        product_category = line.product_id.categ_id
        if product_category:
            rule = Rule.search([
                ('company_id', '=', line.company_id.id), ('active', '=', True),
                ('target_kind', '=', 'product_category'), ('target_key', '=', str(product_category.id)),
            ], limit=2)
            if len(rule) == 1:
                return rule, 'product_rule'
        supplier_category = line.move_id.commercial_partner_id.with_company(
            line.company_id
        ).baseer_purchase_category_map_id
        if supplier_category and supplier_category.active and supplier_category.company_id == line.company_id:
            rule = Rule.search([
                ('company_id', '=', line.company_id.id), ('active', '=', True),
                ('target_kind', '=', 'supplier_category'), ('target_key', '=', str(supplier_category.id)),
            ], limit=2)
            if len(rule) == 1:
                return rule, 'supplier_rule'
        return Rule, 'unclassified'

    @api.model
    def _baseer_capture_posted_moves(self, moves):
        """Atomic post hook: an analytical failure rolls native posting back."""
        Case = self.env['baseer.purchase.line.classification.case'].sudo()
        Snapshot = self.sudo()
        Leg = self.env['baseer.purchase.line.classification.leg'].sudo()
        for move in moves.filtered(lambda item: item.state == 'posted' and item.move_type in ('in_invoice', 'in_refund')):
            for line in move.invoice_line_ids.filtered(lambda item: item.display_type == 'product'):
                self.env.cr.execute('SELECT id FROM account_move_line WHERE id = %s FOR UPDATE', [line.id])
                case = Case.search([('source_line_id', '=', line.id)], limit=1)
                if not case:
                    case = super(BaseerPurchaseLineClassificationCase, Case).create({
                        'source_line_id': line.id, 'company_id': line.company_id.id,
                    })
                previous = case.current_snapshot_id
                rule, source = Snapshot._baseer_rule_for_line(line)
                snapshot = super(BaseerPurchaseLineClassification, Snapshot).create({
                    'case_id': case.id,
                    'version': (previous.version if previous else 0) + 1,
                    'decision_source': source,
                    'reason': 'Native posting' if not previous else 'Native reposting',
                    'created_by_id': self.env.user.id,
                    'created_at': fields.Datetime.now(),
                })
                if rule:
                    leg_values = {
                        'snapshot_id': snapshot.id, 'sequence': 10, 'rule_id': rule.id,
                        'reporting_type': rule.reporting_type,
                        'reporting_category_id': rule.reporting_category_map_id.category_id.id,
                        'reporting_category_name': rule.reporting_category_map_id.category_id.name,
                        'reporting_parent_category_id': rule.reporting_category_map_id.parent_category_id.id,
                        'reporting_parent_category_name': rule.reporting_category_map_id.parent_category_id.name,
                        'basis_points': BASIS_POINTS,
                    }
                else:
                    leg_values = {
                        'snapshot_id': snapshot.id, 'sequence': 10, 'reporting_type': 'unclassified',
                        'reporting_category_name': _('Unclassified'), 'basis_points': BASIS_POINTS,
                    }
                super(BaseerPurchaseLineClassificationLeg, Leg).create(leg_values)
                super(BaseerPurchaseLineClassificationCase, case).write({'current_snapshot_id': snapshot.id})
