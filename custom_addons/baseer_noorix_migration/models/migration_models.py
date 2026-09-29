"""QA-only source provenance for the Noorix migration writer.

There are deliberately no menus, views or access-control rows.  The local
migration writer uses a superuser-only context; ordinary Odoo users cannot
read or mutate provenance through the UI.
"""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


WRITER_CONTEXT = 'baseer_noorix_migration_writer'


class NoorixPrivateEvidence(models.AbstractModel):
    _name = 'baseer.noorix.private.evidence'
    _description = 'Private Noorix migration evidence guard'
    _abstract = True

    def _noorix_writer_allowed(self):
        return self.env.su and self.env.context.get(WRITER_CONTEXT) is True

    @api.model_create_multi
    def create(self, vals_list):
        if not self._noorix_writer_allowed():
            raise AccessError(_('Noorix migration evidence is writer-only.'))
        return super().create(vals_list)

    def unlink(self):
        raise AccessError(_('Noorix migration evidence is append-only.'))


class NoorixMigrationRun(models.Model):
    _name = 'baseer.noorix.migration.run'
    _description = 'Noorix migration run'
    _order = 'id desc'

    name = fields.Char(required=True, readonly=True, index=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True, index=True)
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    payload_sha256 = fields.Char(required=True, readonly=True)
    scope = fields.Selection([
        ('supplier_master', 'Supplier master'),
        ('product_master', 'Product master'),
        ('product_cost', 'Product cost'),
        ('product_operational_policy', 'Product operational policy'),
        ('company_master', 'Company master'),
        ('sales_summary', 'Sales summary'),
        ('purchase_history', 'Purchase history'),
        ('payroll_settlement', 'Payroll settlement'),
    ], required=True, readonly=True)
    state = fields.Selection([
        ('planned', 'Planned'), ('dry_run', 'Dry run'), ('committed', 'Committed'),
        ('failed', 'Failed'), ('reconciled', 'Reconciled'),
    ], required=True, readonly=True, default='planned')
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    result_json = fields.Text(readonly=True)

    _baseer_noorix_run_name_uniq = models.Constraint(
        'UNIQUE(name)',
        'Migration run name must be unique.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(WRITER_CONTEXT) is True):
            raise AccessError(_('Noorix migration runs are writer-only.'))
        return super().create(vals_list)

    def write(self, vals):
        protected = {'name', 'source_archive_sha256', 'source_tenant_id', 'payload_sha256', 'scope'}
        if protected.intersection(vals):
            raise UserError(_('The Noorix run identity is write-once.'))
        if not (self.env.su and self.env.context.get(WRITER_CONTEXT) is True):
            raise AccessError(_('Noorix migration runs are writer-only.'))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_('Noorix migration runs are append-only.'))


class NoorixSupplierMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.supplier.map'
    _description = 'Noorix supplier source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_supplier_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('automatic_valid_vat', 'Automatic valid VAT'),
        ('kept_separate', 'Kept separate'),
        ('existing_global_vat', 'Existing global VAT'),
        ('existing_approved_crosswalk', 'Existing approved crosswalk'),
        ('cash_anonymous', 'Anonymous cash supplier'),
    ], required=True, readonly=True)
    partner_id = fields.Many2one('res.partner', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_supplier_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_supplier_id)',
        'Each Noorix source supplier may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix supplier mappings are write-once.'))


class NoorixSupplierCategoryMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.supplier.category.map'
    _description = 'Noorix supplier category source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_category_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    category_id = fields.Many2one('res.partner.category', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_supplier_category_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_category_id)',
        'Each Noorix source category may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix supplier category mappings are write-once.'))


class NoorixProductMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.product.map'
    _description = 'Noorix product source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_product_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('create_company_product', 'Create company product'),
        ('canonical_alias', 'Canonical source alias'),
    ], required=True, readonly=True)
    product_tmpl_id = fields.Many2one('product.template', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_product_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_product_id)',
        'Each Noorix source product may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix product mappings are write-once.'))


class NoorixProductCategoryMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.product.category.map'
    _description = 'Noorix product category source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_category_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([('create_qa_leaf', 'Create QA leaf')], required=True, readonly=True)
    category_id = fields.Many2one('product.category', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_product_category_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_category_id)',
        'Each Noorix source product category may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix product category mappings are write-once.'))


class NoorixProductUomMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.product.uom.map'
    _description = 'Noorix product unit source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_uom_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('reuse_existing_uom', 'Reuse existing UoM'),
        ('create_package_root_uom', 'Create package root UoM'),
    ], required=True, readonly=True)
    uom_id = fields.Many2one('uom.uom', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_product_uom_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_uom_id)',
        'Each Noorix source product unit may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix product unit mappings are write-once.'))


class NoorixProductCostMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.product.cost.map'
    _description = 'Noorix product cost source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_product_id = fields.Char(required=True, readonly=True, index=True)
    source_price_history_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('set_latest_received_cost', 'Set latest received cost'),
    ], required=True, readonly=True)
    source_cost = fields.Float(required=True, readonly=True)
    effective_at = fields.Datetime(required=True, readonly=True)
    product_id = fields.Many2one('product.product', required=True, readonly=True, ondelete='restrict', index=True)
    run_id = fields.Many2one('baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict')

    _baseer_noorix_product_cost_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_price_history_id)',
        'Each Noorix source cost record may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix product cost mappings are write-once.'))


class NoorixCompanyMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.company.map'
    _description = 'Noorix company source mapping'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('reuse_existing_company', 'Reuse existing company'),
        ('create_historical_company', 'Create historical company'),
        ('alias_archived_company', 'Alias archived company'),
    ], required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, ondelete='restrict', index=True,
    )
    run_id = fields.Many2one(
        'baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict',
    )

    _baseer_noorix_company_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id)',
        'Each Noorix source company may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix company mappings are write-once.'))


class NoorixSalesSummaryMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.sales.summary.map'
    _description = 'Noorix sales summary source mapping'
    _abstract = False
    _auto = True
    _order = 'business_date, id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_summary_id = fields.Char(required=True, readonly=True, index=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    source_gross = fields.Float(required=True, readonly=True)
    source_customers = fields.Integer(required=True, readonly=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    shift = fields.Selection([
        ('all', 'All day'),
        ('morning', 'Morning'),
        ('evening', 'Evening'),
    ], required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('create_summary', 'Create summary'),
        ('merge_into_all_day', 'Merge into all-day summary'),
    ], required=True, readonly=True)
    summary_id = fields.Many2one(
        'baseer.pos.summary', required=True, readonly=True, ondelete='restrict', index=True,
    )
    run_id = fields.Many2one(
        'baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict',
    )

    _baseer_noorix_sales_summary_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_summary_id)',
        'Each Noorix source sales summary may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix sales summary mappings are write-once.'))


class NoorixPurchaseCategoryMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.purchase.category.map'
    _description = 'Noorix historical purchase category decision'
    _abstract = False
    _auto = True
    _order = 'id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_mapping_key = fields.Char(required=True, readonly=True, index=True)
    source_category_id = fields.Char(readonly=True, index=True)
    source_category_name = fields.Char(readonly=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    decision = fields.Selection([
        ('reuse_existing_service', 'Reuse existing service'),
        ('create_historical_service', 'Create historical service'),
        ('document_expense_override', 'Document expense override'),
        ('document_asset_override', 'Document asset override'),
    ], required=True, readonly=True)
    tax_policy = fields.Selection([
        ('tax_when_source_positive', '15% when source tax is positive'),
        ('no_tax', 'No tax'),
    ], required=True, readonly=True)
    product_id = fields.Many2one(
        'product.product', required=True, readonly=True, ondelete='restrict', index=True,
    )
    account_id = fields.Many2one(
        'account.account', required=True, readonly=True, ondelete='restrict', index=True,
    )
    run_id = fields.Many2one(
        'baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict',
    )

    _baseer_noorix_purchase_category_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_mapping_key)',
        'Each Noorix purchase category decision may map only once.',
    )

    def write(self, vals):
        raise UserError(_('Noorix purchase category mappings are write-once.'))


class NoorixPurchaseInvoiceMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.purchase.invoice.map'
    _description = 'Noorix paid vendor bill provenance'
    _abstract = False
    _auto = True
    _order = 'business_date, id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_invoice_id = fields.Char(required=True, readonly=True, index=True)
    source_ledger_id = fields.Char(required=True, readonly=True, index=True)
    source_allocation_id = fields.Char(required=True, readonly=True, index=True)
    source_vault_id = fields.Char(required=True, readonly=True, index=True)
    source_supplier_id = fields.Char(required=True, readonly=True, index=True)
    source_category_id = fields.Char(readonly=True, index=True)
    source_invoice_number = fields.Char(required=True, readonly=True)
    source_supplier_invoice_number = fields.Char(readonly=True)
    source_document_kind = fields.Selection([
        ('purchase', 'Purchase'),
        ('expense', 'Expense'),
        ('fixed_expense', 'Fixed expense'),
    ], required=True, readonly=True)
    business_date = fields.Date(required=True, readonly=True, index=True)
    source_net_raw = fields.Char(required=True, readonly=True)
    source_tax_raw = fields.Char(required=True, readonly=True)
    source_total_raw = fields.Char(required=True, readonly=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    source_asset_id = fields.Char(readonly=True, index=True)
    source_asset_row_sha256 = fields.Char(readonly=True)
    decision = fields.Selection([
        ('create_paid_vendor_bill', 'Create paid vendor bill'),
        ('capitalize_cashier_computer', 'Capitalize cashier computer bill'),
    ], required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, ondelete='restrict', index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    category_map_id = fields.Many2one(
        'baseer.noorix.purchase.category.map', required=True, readonly=True,
        ondelete='restrict', index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', required=True, readonly=True, ondelete='restrict', index=True,
    )
    tax_id = fields.Many2one('account.tax', readonly=True, ondelete='restrict', index=True)
    purchase_journal_id = fields.Many2one(
        'account.journal', required=True, readonly=True, ondelete='restrict', index=True,
    )
    payment_journal_id = fields.Many2one(
        'account.journal', required=True, readonly=True, ondelete='restrict', index=True,
    )
    bill_id = fields.Many2one(
        'account.move', required=True, readonly=True, ondelete='restrict', index=True,
    )
    payment_id = fields.Many2one(
        'account.payment', required=True, readonly=True, ondelete='restrict', index=True,
    )
    payment_move_id = fields.Many2one(
        'account.move', required=True, readonly=True, ondelete='restrict', index=True,
    )
    target_net = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    target_tax = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    target_total = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    run_id = fields.Many2one(
        'baseer.noorix.migration.run', required=True, readonly=True, ondelete='restrict',
    )

    _baseer_noorix_purchase_invoice_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_invoice_id)',
        'Each Noorix source purchase document may map only once.',
    )
    _baseer_noorix_purchase_bill_uniq = models.Constraint(
        'UNIQUE(bill_id)',
        'Each migrated vendor bill may have only one Noorix source mapping.',
    )
    _baseer_noorix_purchase_payment_uniq = models.Constraint(
        'UNIQUE(payment_id)',
        'Each migrated payment may have only one Noorix source mapping.',
    )
    _baseer_noorix_purchase_payment_move_uniq = models.Constraint(
        'UNIQUE(payment_move_id)',
        'Each migrated payment move may have only one Noorix source mapping.',
    )

    def write(self, vals):
        raise UserError(_('Noorix purchase invoice mappings are write-once.'))


class NoorixPayrollSettlementMap(NoorixPrivateEvidence):
    _name = 'baseer.noorix.payroll.settlement.map'
    _description = 'Noorix owner-declared net payroll settlement provenance'
    _abstract = False
    _auto = True
    _order = 'target_posting_date, id'

    source_system = fields.Char(required=True, readonly=True, default='noorix')
    source_tenant_id = fields.Char(required=True, readonly=True, index=True)
    source_company_id = fields.Char(required=True, readonly=True, index=True)
    source_payroll_run_id = fields.Char(required=True, readonly=True, index=True)
    source_run_number = fields.Char(required=True, readonly=True)
    source_row_sha256 = fields.Char(required=True, readonly=True)
    source_accrual_rows_sha256 = fields.Char(required=True, readonly=True)
    source_accrual_count = fields.Integer(required=True, readonly=True)
    source_archive_sha256 = fields.Char(required=True, readonly=True)
    canonical_key = fields.Char(required=True, readonly=True, index=True)
    source_gross_raw = fields.Char(required=True, readonly=True)
    source_advances_raw = fields.Char(required=True, readonly=True)
    source_net_raw = fields.Char(required=True, readonly=True)
    source_period = fields.Date(required=True, readonly=True)
    source_completion_date = fields.Date(required=True, readonly=True)
    target_posting_date = fields.Date(required=True, readonly=True, index=True)
    date_basis = fields.Selection([
        (
            'owner_declaration_plus_source_completion',
            'Owner declaration plus source completion date',
        ),
    ], required=True, readonly=True)
    owner_declaration = fields.Selection([
        ('treat_net_as_paid_from_bank', 'Treat net salary as paid from bank'),
    ], required=True, readonly=True)
    decision = fields.Selection([
        ('create_owner_declared_bank_move', 'Create owner-declared bank move'),
    ], required=True, readonly=True)
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True, ondelete='restrict', index=True,
    )
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    journal_id = fields.Many2one(
        'account.journal', required=True, readonly=True, ondelete='restrict', index=True,
    )
    salary_expense_account_id = fields.Many2one(
        'account.account', required=True, readonly=True, ondelete='restrict', index=True,
    )
    bank_account_id = fields.Many2one(
        'account.account', required=True, readonly=True, ondelete='restrict', index=True,
    )
    target_amount = fields.Monetary(
        required=True, readonly=True, currency_field='currency_id',
    )
    move_id = fields.Many2one(
        'account.move', required=True, readonly=True, ondelete='restrict', index=True,
    )
    run_id = fields.Many2one(
        'baseer.noorix.migration.run', required=True, readonly=True,
        ondelete='restrict', index=True,
    )

    _baseer_noorix_payroll_settlement_source_uniq = models.Constraint(
        'UNIQUE(source_system, source_tenant_id, source_company_id, source_payroll_run_id)',
        'Each Noorix source payroll run may be settled only once.',
    )
    _baseer_noorix_payroll_settlement_move_uniq = models.Constraint(
        'UNIQUE(move_id)',
        'Each owner-declared payroll settlement move may have only one Noorix mapping.',
    )

    def write(self, vals):
        raise UserError(_('Noorix payroll settlement mappings are write-once.'))
