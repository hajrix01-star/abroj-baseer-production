import logging
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta
from psycopg2 import IntegrityError

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


INTERNAL = 'baseer_representative_petty_cash_internal'
MONEY_QUANTUM = Decimal('0.01')
_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_procurement_representative_petty_cash_account_id = fields.Many2one(
        'account.account', string='Representative Petty Cash account', check_company=True,
    )
    baseer_procurement_representative_petty_cash_journal_id = fields.Many2one(
        'account.journal', string='Representative Petty Cash journal', check_company=True,
    )
    baseer_procurement_representative_petty_cash_payment_journal_ids = fields.Many2many(
        'account.journal', 'baseer_rep_pc_company_payment_journal_rel', 'company_id', 'journal_id',
        string='Representative Petty Cash payment points', check_company=True, copy=False,
        help='Existing company bank or cash points that accountants may use for Representative Petty Cash.',
    )
    baseer_procurement_default_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Default procurement warehouse', check_company=True,
        help='Used for new procurement requests when this company has one selected main warehouse.',
    )

    def _baseer_representative_petty_cash_seed_record(self, key, model):
        """Return the one record this module has created for this company."""
        self.ensure_one()
        data = self.env['ir.model.data'].sudo().search([
            ('module', '=', 'baseer_procurement_requests'),
            ('name', '=', '%s_company_%s' % (key, self.id)),
        ], limit=1)
        if not data:
            return self.env[model]
        if data.model != model:
            raise ValidationError(_('The Representative Petty Cash setup reference is invalid.'))
        record = self.env[model].browse(data.res_id).exists()
        if not record:
            raise ValidationError(_('The Representative Petty Cash setup reference is invalid.'))
        if model == 'account.account' and self not in record.company_ids:
            raise ValidationError(_('The Representative Petty Cash setup reference is invalid.'))
        if model == 'account.journal' and record.company_id != self:
            raise ValidationError(_('The Representative Petty Cash setup reference is invalid.'))
        return record

    def _baseer_remember_representative_petty_cash_seed(self, key, record):
        self.ensure_one()
        self.env['ir.model.data'].sudo().create({
            'module': 'baseer_procurement_requests',
            'name': '%s_company_%s' % (key, self.id),
            'model': record._name,
            'res_id': record.id,
            'noupdate': True,
        })
        return record

    def _baseer_representative_petty_cash_next_journal_code(self):
        self.ensure_one()
        used_codes = set(self.env['account.journal'].with_context(active_test=False).search([
            ('company_id', '=', self.id),
        ]).mapped('code'))
        for code in ('RPCA',) + tuple('RP%03d' % number for number in range(1, 1000)):
            if code not in used_codes:
                return code
        raise ValidationError(_('No available company journal code for Representative Petty Cash.'))

    def _baseer_validate_representative_petty_cash_seed(self, account, journal):
        """Reject an altered module-owned seed before creating either side.

        A missing field plus an archived or modified recorded seed must not
        result in a newly-created account/journal counterpart.  That would
        leave a company half-configured and conceal an accounting decision.
        """
        self.ensure_one()
        if account and (not account.active or not account.reconcile or account.account_type != 'asset_current'):
            raise ValidationError(_('Review the archived or modified Representative Petty Cash account.'))
        if journal and (not journal.active or journal.type != 'general'):
            raise ValidationError(_('Review the archived or modified Representative Petty Cash general journal.'))

    def _baseer_ensure_representative_petty_cash_setup(self, require_chart=False, raise_on_missing_chart=False):
        """Create the one shared account and general journal only when absent.

        An existing configured value is never replaced.  This preserves manual
        accounting choices and means a modified or archived configuration is
        surfaced to the manager as an issue instead of being silently changed.
        """
        for original in self.sorted('id'):
            company = original.sudo().with_company(original)
            self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company.id])
            company.invalidate_recordset()
            if require_chart and not company.chart_template:
                if raise_on_missing_chart:
                    raise UserError(_('Configure the company chart of accounts before initializing Representative Petty Cash.'))
                continue

            # A partially configured company is an intentional accounting
            # decision until its manager completes it; do not fill one side
            # silently and make that decision harder to audit.
            account = company.baseer_procurement_representative_petty_cash_account_id
            journal = company.baseer_procurement_representative_petty_cash_journal_id
            if bool(account) != bool(journal) or (account and journal):
                continue

            seed_account = company._baseer_representative_petty_cash_seed_record(
                'representative_petty_cash_account', 'account.account'
            ) if not account else self.env['account.account']
            seed_journal = company._baseer_representative_petty_cash_seed_record(
                'representative_petty_cash_journal', 'account.journal'
            ) if not journal else self.env['account.journal']
            company._baseer_validate_representative_petty_cash_seed(seed_account, seed_journal)

            updates = {}
            if not account:
                account = seed_account
                if not account:
                    Account = company.env['account.account']
                    account = Account.create({
                        'name': 'Representative Petty Cash | عهدة مندوبي المشتريات',
                        'code': Account._search_new_account_code('108990', cache=set()),
                        'account_type': 'asset_current',
                        'reconcile': True,
                        'company_ids': [Command.set(company.ids)],
                    })
                    company._baseer_remember_representative_petty_cash_seed(
                        'representative_petty_cash_account', account,
                    )
                if account.active and account.reconcile and account.account_type == 'asset_current':
                    updates['baseer_procurement_representative_petty_cash_account_id'] = account.id

            if not journal:
                journal = seed_journal
                if not journal:
                    journal = company.env['account.journal'].create({
                        'name': 'Representative Petty Cash | عهدة مندوبي المشتريات',
                        'code': company._baseer_representative_petty_cash_next_journal_code(),
                        'type': 'general',
                        'company_id': company.id,
                    })
                    company._baseer_remember_representative_petty_cash_seed(
                        'representative_petty_cash_journal', journal,
                    )
                if journal.active and journal.type == 'general':
                    updates['baseer_procurement_representative_petty_cash_journal_id'] = journal.id

            if updates:
                company.write(updates)
        return True

    def action_baseer_initialize_representative_petty_cash(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Only an ERP manager can initialize Representative Petty Cash.'))
        for company in self:
            if bool(company.baseer_procurement_representative_petty_cash_account_id) != bool(
                company.baseer_procurement_representative_petty_cash_journal_id
            ):
                raise UserError(_(
                    'Complete or clear the existing Representative Petty Cash account and journal setup first.'
                ))
        self.sudo()._baseer_ensure_representative_petty_cash_setup(
            require_chart=True, raise_on_missing_chart=True,
        )
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.constrains('baseer_procurement_representative_petty_cash_payment_journal_ids')
    def _check_baseer_representative_petty_cash_payment_points(self):
        for company in self:
            invalid = company.baseer_procurement_representative_petty_cash_payment_journal_ids.filtered(
                lambda journal: (
                    journal.company_id != company
                    or not journal.active
                    or journal.type not in ('bank', 'cash')
                    or not journal.default_account_id
                    or journal.default_account_id.account_type != 'asset_cash'
                ),
            )
            if invalid:
                raise ValidationError(_(
                    'Representative Petty Cash payment points must be active company bank or cash points.'
                ))

    def _baseer_representative_petty_cash_payment_points(self):
        """Return only the explicitly approved, usable existing payment journals."""
        self.ensure_one()
        return self.baseer_procurement_representative_petty_cash_payment_journal_ids.filtered(
            lambda journal: (
                journal.company_id == self
                and journal.active
                and journal.type in ('bank', 'cash')
                and journal.default_account_id
                and journal.default_account_id.account_type == 'asset_cash'
            ),
        )

    def _baseer_validate_representative_petty_cash_payment_point(self, journal):
        self.ensure_one()
        if journal not in self._baseer_representative_petty_cash_payment_points():
            raise ValidationError(_(
                'Choose a payment point configured for Representative Petty Cash in the company settings.'
            ))
        return journal

    def _baseer_representative_petty_cash_setup_issue(self):
        self.ensure_one()
        account = self.baseer_procurement_representative_petty_cash_account_id
        journal = self.baseer_procurement_representative_petty_cash_journal_id
        if (not account or self not in account.company_ids or not account.active or not account.reconcile
                or account.account_type not in ('asset_receivable', 'asset_current')):
            return _('Configure an active reconcilable Representative Petty Cash account first.')
        if not journal or journal.company_id != self or not journal.active or journal.type != 'general':
            return _('Configure an active Representative Petty Cash general journal first.')
        return False

    def _baseer_representative_petty_cash_ready(self):
        self.ensure_one()
        issue = self._baseer_representative_petty_cash_setup_issue()
        if issue:
            raise UserError(issue)
        account = self.baseer_procurement_representative_petty_cash_account_id
        journal = self.baseer_procurement_representative_petty_cash_journal_id
        return account, journal


class BaseerRepresentativePettyCashChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    def _load(self, template_code, company, install_demo, force_create=True):
        """Attach the seed to Odoo's definitive chart-completion boundary.

        A module-local class name is deliberate: it avoids colliding with
        Odoo's own `AccountChartTemplate` Python class during model assembly.
        This runs after the native chart is present; payment points and every
        operational movement remain explicit choices.
        """
        result = super()._load(template_code, company, install_demo, force_create)
        company_id = company if isinstance(company, int) else company.id
        self.env['res.company'].browse(company_id).sudo()._baseer_ensure_representative_petty_cash_setup(
            require_chart=True,
        )
        return result


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _baseer_assert_custody_lifecycle(self):
        super()._baseer_assert_custody_lifecycle()
        if self and self.env['account.move.line'].sudo().search_count([
            ('move_id', 'in', self.ids),
            ('baseer_representative_petty_cash_id', '!=', False),
        ]):
            raise UserError(_(
                'Representative Petty Cash entries cannot be reset, cancelled, reversed, or deleted. '
                'Record a linked returned-cash movement instead.'
            ))


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    baseer_representative_petty_cash_id = fields.Many2one(
        'baseer.procurement.representative.advance', string='Representative Petty Cash source',
        readonly=True, copy=False, index=True, ondelete='restrict', check_company=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if (any('baseer_representative_petty_cash_id' in values for values in vals_list)
                and not (self.env.su and self.env.context.get(INTERNAL))):
            raise AccessError(_('Representative Petty Cash source links are controlled by the server.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'baseer_representative_petty_cash_id' in vals:
            raise AccessError(_('Representative Petty Cash source links are immutable.'))
        return super().write(vals)


class RepresentativePettyCash(models.Model):
    """One immutable transfer to a purchase representative, never a company fund."""

    _name = 'baseer.procurement.representative.advance'
    _description = 'Representative Petty Cash'
    _order = 'movement_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    movement_type = fields.Selection([('funding', 'Funding'), ('return', 'Return'), ('reversal', 'Funding reversal')], required=True, readonly=True, default='funding')
    representative_partner_id = fields.Many2one('res.partner', required=True, readonly=True, ondelete='restrict', check_company=True, index=True)
    procurement_request_id = fields.Many2one('baseer.procurement.request', readonly=True, ondelete='restrict', check_company=True, index=True)
    origin_id = fields.Many2one('baseer.procurement.representative.advance', readonly=True, ondelete='restrict', check_company=True, index=True)
    payment_journal_id = fields.Many2one('account.journal', required=True, readonly=True, ondelete='restrict', check_company=True)
    movement_date = fields.Date(required=True, readonly=True, default=fields.Date.context_today, index=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')
    external_reference = fields.Char(readonly=True, copy=False)
    reversal_reason = fields.Char(readonly=True, copy=False)
    transfer_proof = fields.Binary(readonly=True, copy=False, attachment=True)
    transfer_proof_filename = fields.Char(readonly=True, copy=False)
    client_token = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection([('posted', 'Posted')], default='posted', required=True, readonly=True, index=True)
    move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict', check_company=True)
    created_by_id = fields.Many2one('res.users', required=True, readonly=True, default=lambda self: self.env.user, ondelete='restrict', index=True)
    return_ids = fields.One2many('baseer.procurement.representative.advance', 'origin_id', readonly=True, string='Returns')
    returned_amount = fields.Monetary(compute='_compute_returned_amount', currency_field='currency_id', readonly=True)
    remaining_amount = fields.Monetary(compute='_compute_returned_amount', currency_field='currency_id', readonly=True)

    _sql_constraints = [
        ('representative_petty_cash_client_token_unique', 'unique(company_id, created_by_id, client_token)', 'This save request was already recorded.'),
    ]

    def init(self):
        self.env.cr.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_rep_pc_external_reference_unique
            ON baseer_procurement_representative_advance (company_id, payment_journal_id, external_reference)
            WHERE external_reference IS NOT NULL AND external_reference <> ''
        ''')
        self.env.cr.execute('''
            CREATE UNIQUE INDEX IF NOT EXISTS baseer_rep_pc_funding_reversal_unique
            ON baseer_procurement_representative_advance (origin_id)
            WHERE movement_type = 'reversal' AND state = 'posted'
        ''')

    @api.depends('amount', 'return_ids.amount', 'return_ids.state')
    def _compute_returned_amount(self):
        posted_returns = self.read_group([
            ('origin_id', 'in', self.ids), ('state', '=', 'posted'), ('movement_type', '=', 'return'),
        ], ['origin_id', 'amount:sum'], ['origin_id']) if self.ids else []
        totals = {row['origin_id'][0]: row['amount'] for row in posted_returns if row['origin_id']}
        reversals = self.read_group([
            ('origin_id', 'in', self.ids), ('state', '=', 'posted'), ('movement_type', '=', 'reversal'),
        ], ['origin_id', 'amount:sum'], ['origin_id']) if self.ids else []
        reversed_totals = {row['origin_id'][0]: row['amount'] for row in reversals if row['origin_id']}
        for record in self:
            record.returned_amount = totals.get(record.id, 0.0)
            record.remaining_amount = record.amount - record.returned_amount - reversed_totals.get(record.id, 0.0) if record.movement_type == 'funding' else 0.0

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            try:
                value = Decimal(str(record.amount))
            except (InvalidOperation, TypeError):
                raise ValidationError(_('Enter a valid amount.'))
            if value <= 0 or value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP) != value:
                raise ValidationError(_('The amount must be positive and use no more than two decimal places.'))

    @api.constrains('representative_partner_id', 'procurement_request_id', 'origin_id', 'movement_type')
    def _check_relationships(self):
        for record in self:
            partner = record.representative_partner_id.with_company(record.company_id)
            if (not record.representative_partner_id.active or record.representative_partner_id.is_company
                    or record.representative_partner_id.parent_id or not partner.is_purchase_representative
                    or (record.representative_partner_id.company_id and record.representative_partner_id.company_id != record.company_id)):
                raise ValidationError(_('Choose an active purchase-representative contact in the active company.'))
            if record.movement_type == 'funding':
                request = record.procurement_request_id
                if request:
                    request._require_receipt_workflow()
                if request and (request.company_id != record.company_id or request.state not in ('sent', 'received', 'purchased')):
                    raise ValidationError(_('Choose a sent, received, or completed purchase request in the active company.'))
                if request and request.representative_partner_id != record.representative_partner_id:
                    raise ValidationError(_('The purchase representative must match the selected purchase request.'))
                if record.origin_id:
                    raise ValidationError(_('A funding movement cannot have an original movement.'))
            else:
                origin = record.origin_id
                if record.movement_type == 'reversal' and not origin:
                    raise ValidationError(_('A reversal must reference its original funding movement.'))
                if (origin and (origin.company_id != record.company_id or origin.movement_type != 'funding'
                               or origin.representative_partner_id != record.representative_partner_id)):
                    raise ValidationError(_('A return must be linked to its original representative petty-cash movement.'))
                if record.procurement_request_id:
                    raise ValidationError(_('A return does not carry a purchase request.'))

    @api.constrains('payment_journal_id')
    def _check_payment_journal(self):
        for record in self:
            journal = record.payment_journal_id
            if (journal.company_id != record.company_id or not journal.active or journal.type not in ('bank', 'cash')
                    or not journal.default_account_id or journal.default_account_id.account_type != 'asset_cash'):
                raise ValidationError(_('Choose an active company bank or cash payment point.'))
            record.company_id._baseer_validate_representative_petty_cash_payment_point(journal)

    @api.model_create_multi
    def create(self, vals_list):
        if not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Use the Representative Petty Cash save action.'))
        normalized = []
        for values in vals_list:
            values = dict(values)
            values['name'] = self.env['ir.sequence'].next_by_code('baseer.procurement.representative.petty.cash') or 'New'
            values['state'] = 'posted'
            normalized.append(values)
        return super().create(normalized)

    def write(self, vals):
        if self.env.su and self.env.context.get(INTERNAL) and set(vals) <= {'move_id'}:
            return super().write(vals)
        raise UserError(_('Posted Representative Petty Cash movements are immutable. Record a linked return instead.'))

    def unlink(self):
        raise UserError(_('Posted Representative Petty Cash movements cannot be deleted.'))

    def _require_accountant(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can record Representative Petty Cash.'))

    def _require_reader(self):
        if not (self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant')
                or self.env.user.has_group('baseer_procurement_requests.group_procurement_manager')
                or self.env.user.has_group('base.group_system')):
            raise AccessError(_('You are not allowed to view Representative Petty Cash.'))

    @api.model
    def _month_range(self, month_start=False):
        start = (fields.Date.to_date(month_start) if month_start else fields.Date.context_today(self)).replace(day=1)
        return start, start + relativedelta(months=1)

    @api.model
    def dashboard_data(self, representative_id=False, month_start=False):
        self._require_reader()
        try:
            return self._dashboard_data(representative_id, month_start)
        except UserError:
            raise
        except Exception as error:
            _logger.exception('Representative Petty Cash dashboard failed for company %s', self.env.company.id)
            if self.env.user.has_group('base.group_system'):
                raise UserError(_(
                    'تعذر تحميل لوحة عهدة مندوب المشتريات: %(type)s — %(message)s',
                    type=type(error).__name__, message=str(error),
                )) from error
            raise UserError(_('تعذر تحميل لوحة عهدة مندوب المشتريات. تم تسجيل الخطأ للمراجعة.')) from error

    def _dashboard_data(self, representative_id=False, month_start=False):
        stage = _('إعداد الفترة')
        try:
            start, end = self._month_range(month_start)
            company = self.env.company
            read_model = self.sudo().with_company(company)
            stage = _('طلبات الشراء')
            request_domain = [('company_id', '=', company.id), ('state', 'in', ['sent', 'received', 'purchased'])]
            if representative_id:
                request_domain.append(('representative_partner_id', '=', int(representative_id)))
            requests = self.env['baseer.procurement.request'].sudo().with_company(company).search(request_domain, order='request_date desc, id desc', limit=100)
            stage = _('قائمة المندوبين')
            partners = self.env['res.partner'].sudo().with_company(company).search([
                ('is_purchase_representative', '=', True), ('company_id', 'in', [False, company.id]),
                ('is_company', '=', False), ('parent_id', '=', False), ('active', '=', True),
            ], order='name, id')
            representatives = [{'id': partner.id, 'display_name': partner.display_name} for partner in partners]
            request_rows = [{
                'id': request.id, 'name': request.name, 'representative_id': request.representative_partner_id.id,
                'representative_name': request.representative_partner_id.display_name,
                'request_date': fields.Datetime.to_string(request.request_date),
                'amount': request.actual_total if request.state == 'purchased' else request.requested_total,
                'currency_symbol': request.currency_id.symbol, 'currency_position': request.currency_id.position,
            } for request in requests]
            stage = _('حركات العهدة')
            movement_domain = [('company_id', '=', company.id), ('movement_date', '>=', start), ('movement_date', '<', end)]
            if representative_id:
                movement_domain.append(('representative_partner_id', '=', int(representative_id)))
            movements = read_model.search(movement_domain, limit=100)
            open_funding_domain = [
                ('company_id', '=', company.id), ('movement_type', '=', 'funding'), ('state', '=', 'posted'),
            ]
            if representative_id:
                open_funding_domain.append(('representative_partner_id', '=', int(representative_id)))
            open_fundings = read_model.search(open_funding_domain, order='movement_date desc, id desc', limit=200)
            stage = _('نقاط الدفع')
            can_record = self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant')
            payment_points = []
            if can_record:
                journals = company.sudo()._baseer_representative_petty_cash_payment_points()
                payment_points = [{
                    'id': journal.id, 'name': journal.name, 'type': journal.type,
                } for journal in journals.sorted(lambda journal: (journal.sequence, journal.name))]
        except Exception as error:
            _logger.exception('Representative Petty Cash dashboard failed at %s for company %s', stage, self.env.company.id)
            raise UserError(_('تعذر تحميل %(stage)s في لوحة العهدة (%(type)s).') % {
                'stage': stage, 'type': type(error).__name__,
            }) from error
        return {
            'month_start': fields.Date.to_string(start), 'currency_symbol': company.currency_id.symbol,
            'currency_position': company.currency_id.position, 'representatives': representatives,
            'can_record': can_record,
            'requests': request_rows,
            'payment_points': payment_points,
            'payment_points_configured': bool(payment_points),
            'setup_issue': company._baseer_representative_petty_cash_setup_issue() if can_record else False,
            # The invoice-source extension calculates complete server totals.
            'summary': {},
            'open_fundings': [{
                'id': funding.id, 'name': funding.name, 'representative_name': funding.representative_partner_id.display_name,
                'request_name': funding.procurement_request_id.name, 'remaining': funding.remaining_amount,
            } for funding in open_fundings if not company.currency_id.is_zero(funding.remaining_amount)],
            'movements': [{
                'id': movement.id, 'date': fields.Date.to_string(movement.movement_date),
                'type': movement.movement_type, 'name': movement.name, 'amount': movement.amount,
                'representative_name': movement.representative_partner_id.display_name,
                'request_name': movement.procurement_request_id.name,
                'payment_point_name': movement.payment_journal_id.display_name,
                # Funding leaves the company payment point.  A return comes
                # back from the representative to that same payment point.
                'from_name': (
                    movement.representative_partner_id.display_name
                    if movement.movement_type == 'return'
                    else movement.payment_journal_id.display_name
                ),
                'to_name': (
                    movement.payment_journal_id.display_name
                    if movement.movement_type == 'return'
                    else movement.representative_partner_id.display_name
                ),
            } for movement in movements],
        }

    @api.model
    def _lock_request(self, request_id):
        self.env.cr.execute('SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [request_id])
        self.env.cr.execute('UPDATE baseer_procurement_request SET id = id WHERE id = %s', [request_id])
        request = self.env['baseer.procurement.request'].browse(request_id).exists()
        request.invalidate_recordset()
        return request

    def _lock_advance(self, advance_id):
        self.env.cr.execute(
            'SELECT id FROM baseer_procurement_representative_advance WHERE id = %s FOR UPDATE', [advance_id],
        )
        self.env.cr.execute(
            'UPDATE baseer_procurement_representative_advance SET id = id WHERE id = %s', [advance_id],
        )
        advance = self.browse(advance_id).exists()
        advance.invalidate_recordset()
        return advance

    @api.model
    def submit_funding(self, request_id, payment_journal_id, representative_partner_id, amount, client_token,
                       movement_date=False, external_reference=False, transfer_proof=False, transfer_proof_filename=False):
        self._require_accountant()
        token = (client_token or '').strip()
        if not token:
            raise ValidationError(_('Reload the page and try saving again.'))
        if not movement_date:
            raise ValidationError(_('Enter the transfer date before saving.'))
        company = self.env.company
        existing = self.search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
        if existing:
            return existing.id
        request = self._lock_request(int(request_id)) if request_id else self.env['baseer.procurement.request']
        if request:
            request._require_receipt_workflow()
        payment_journal = self.env['account.journal'].browse(int(payment_journal_id)).exists()
        representative = self.env['res.partner'].browse(int(representative_partner_id)).exists()
        if not payment_journal or not representative or (request_id and not request):
            raise ValidationError(_('Choose the payment point and purchase representative.'))
        company._baseer_validate_representative_petty_cash_payment_point(payment_journal)
        if request and representative != request.representative_partner_id:
            raise ValidationError(_('The transfer destination must match the purchase representative on the selected request.'))
        if request and (request.company_id != company or request.state not in ('sent', 'received', 'purchased')):
            raise ValidationError(_('Choose a sent, received, or completed purchase request in the active company.'))
        values = {
            'company_id': company.id, 'movement_type': 'funding',
            'representative_partner_id': representative.id,
            'procurement_request_id': request.id or False, 'payment_journal_id': payment_journal.id,
            'movement_date': movement_date, 'amount': amount,
            'client_token': token, 'created_by_id': self.env.user.id,
        }
        try:
            with self.env.cr.savepoint():
                return self._create_and_post(values).id
        except IntegrityError:
            existing = self.search([
                ('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token),
            ], limit=1)
            if existing:
                return existing.id
            raise ValidationError(_('This save request was already recorded.'))

    @api.model
    def submit_return(self, origin_id, payment_journal_id, amount, client_token, movement_date=False, external_reference=False):
        self._require_accountant()
        token = (client_token or '').strip()
        if not token:
            raise ValidationError(_('Reload the page and try saving again.'))
        company = self.env.company
        existing = self.search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
        if existing:
            return existing.id
        origin = self._lock_advance(int(origin_id))
        payment_journal = self.env['account.journal'].browse(int(payment_journal_id)).exists()
        if (not origin or origin.company_id != company or origin.movement_type != 'funding' or not payment_journal):
            raise ValidationError(_('Choose an open original movement and a company payment point.'))
        company._baseer_validate_representative_petty_cash_payment_point(payment_journal)
        try:
            return_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            raise ValidationError(_('Enter a valid amount.'))
        if return_amount <= 0 or return_amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP) != return_amount:
            raise ValidationError(_('The amount must be positive and use no more than two decimal places.'))
        if return_amount > Decimal(str(origin.remaining_amount)).quantize(MONEY_QUANTUM):
            raise ValidationError(_('Returned cash cannot exceed the remaining amount of the original movement.'))
        values = {
            'company_id': company.id, 'movement_type': 'return',
            'representative_partner_id': origin.representative_partner_id.id, 'origin_id': origin.id,
            'payment_journal_id': payment_journal.id, 'movement_date': movement_date or fields.Date.context_today(self),
            'amount': amount, 'external_reference': (external_reference or '').strip() or False,
            'client_token': token, 'created_by_id': self.env.user.id,
        }
        try:
            with self.env.cr.savepoint():
                return self._create_and_post(values).id
        except IntegrityError:
            existing = self.search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
            if existing:
                return existing.id
            raise ValidationError(_('This external transfer reference was already used for the selected payment point.'))

    @api.model
    def submit_funding_reversal(self, funding_id, reason, reversal_date, client_token):
        """Reverse one untouched funding entry without changing its history."""
        self._require_accountant()
        token = (client_token or '').strip()
        reason = (reason or '').strip()
        if not token or not reason or len(reason) > 500 or not reversal_date:
            raise ValidationError(_('Enter a correction reason and reversal date.'))
        try:
            day = fields.Date.to_date(reversal_date)
            funding_id = int(funding_id)
        except (ValueError, TypeError):
            raise ValidationError(_('Choose a valid movement and reversal date.')) from None
        company = self.env.company
        existing = self.sudo().search([('company_id', '=', company.id), ('created_by_id', '=', self.env.user.id), ('client_token', '=', token)], limit=1)
        if existing:
            if existing.movement_type == 'reversal' and existing.origin_id.id == funding_id:
                return existing.id
            raise ValidationError(_('This save request was already used for another movement.'))
        original = self.sudo()._lock_advance(funding_id)
        if not original or original.company_id != company or original.movement_type != 'funding' or not original.move_id:
            raise ValidationError(_('Choose a posted funding movement in the active company.'))
        # Match the linked-return lock order: funding row, then company and representative.
        self._baseer_lock_representative_balance(company, original.representative_partner_id)
        original.invalidate_recordset()
        if day < original.movement_date:
            raise ValidationError(_('The reversal date cannot precede the funding date.'))
        if self.sudo().search_count([('movement_type', '=', 'reversal'), ('origin_id', '=', original.id), ('state', '=', 'posted')]):
            raise ValidationError(_('This funding movement has already been reversed.'))
        move = original.move_id
        if move.state != 'posted' or move.company_id != company or len(move.line_ids) != 2:
            raise ValidationError(_('The original entry is not eligible for reversal.'))
        if any(record.currency_id and record.currency_id != company.currency_id for record in (
                move, move.journal_id, original.payment_journal_id, original.payment_journal_id.default_account_id,
                *move.line_ids, *move.line_ids.account_id)):
            raise ValidationError(_('Foreign-currency funding entries cannot be reversed by this action.'))
        if company._get_violated_lock_dates(day, False, move.journal_id):
            raise ValidationError(_('The reversal date is in a locked accounting period.'))
        if move.line_ids.filtered(lambda line: line.matched_debit_ids or line.matched_credit_ids or line.reconciled):
            raise ValidationError(_('A matched or settled funding entry cannot be reversed here.'))
        if Decimal(str(original.amount)) > self._baseer_representative_available_amount(company, original.representative_partner_id):
            raise ValidationError(_('The available representative balance is insufficient to reverse this funding.'))
        values = {
            'company_id': company.id, 'movement_type': 'reversal', 'origin_id': original.id,
            'representative_partner_id': original.representative_partner_id.id,
            'payment_journal_id': original.payment_journal_id.id, 'movement_date': day,
            'amount': original.amount, 'client_token': token, 'created_by_id': self.env.user.id,
            'reversal_reason': reason,
        }
        try:
            with self.env.cr.savepoint():
                reversal = self.sudo().with_company(company).with_context(**{INTERNAL: True}).create(values)
                lines = []
                for line in move.line_ids:
                    lines.append(Command.create({
                        'name': _('Reversal of %(name)s: %(reason)s', name=original.name, reason=reason),
                        'account_id': line.account_id.id, 'partner_id': line.partner_id.id,
                        'debit': line.credit, 'credit': line.debit,
                        'baseer_representative_petty_cash_id': original.id if line.baseer_representative_petty_cash_id else False,
                    }))
                reversal_move = self.env['account.move'].sudo().with_company(company).with_context(**{INTERNAL: True}).create({
                    'move_type': 'entry', 'company_id': company.id, 'journal_id': move.journal_id.id,
                    'date': day, 'ref': _('Reversal of %(name)s: %(reason)s', name=original.name, reason=reason),
                    'reversed_entry_id': move.id, 'line_ids': lines,
                })
                reversal_move.action_post()
                original_lines = move.line_ids.filtered('baseer_representative_petty_cash_id')
                reversal_lines = reversal_move.line_ids.filtered('baseer_representative_petty_cash_id')
                if len(original_lines) != 1 or len(reversal_lines) != 1 or original_lines.account_id != reversal_lines.account_id:
                    raise ValidationError(_('The original entry is not eligible for reversal.'))
                if original_lines.reconciled != reversal_lines.reconciled:
                    raise ValidationError(_('The original entry is not eligible for reversal.'))
                if not original_lines.reconciled:
                    (original_lines | reversal_lines).reconcile()
                reversal.with_context(**{INTERNAL: True}).write({'move_id': reversal_move.id})
                original.invalidate_recordset(['return_ids', 'returned_amount', 'remaining_amount'])
                return reversal.id
        except IntegrityError:
            raise ValidationError(_('This funding movement has already been reversed.')) from None

    def _create_and_post(self, values):
        company = self.env['res.company'].browse(values['company_id'])
        account, journal = company._baseer_representative_petty_cash_ready()
        payment_journal = self.env['account.journal'].browse(values['payment_journal_id']).exists()
        company._baseer_validate_representative_petty_cash_payment_point(payment_journal)
        if any(record.currency_id and record.currency_id != company.currency_id for record in (
                account, journal, payment_journal, payment_journal.default_account_id)):
            raise ValidationError(_('Representative Petty Cash movements require company-currency accounts and journals.'))
        record = self.sudo().with_company(company).with_context(**{INTERNAL: True}).create(values)
        self._lock_advance(record.id)
        original = record.origin_id if record.movement_type == 'return' and record.origin_id else record
        if record.movement_type == 'return' and record.origin_id:
            original = self._lock_advance(record.origin_id.id)
            if Decimal(str(record.amount)) > Decimal(str(original.remaining_amount)).quantize(MONEY_QUANTUM):
                raise ValidationError(_('Returned cash cannot exceed the remaining amount of the original movement.'))
        if company._get_violated_lock_dates(record.movement_date, False, journal):
            raise ValidationError(_('The movement date is in a locked accounting period.'))
        source_account = record.payment_journal_id.default_account_id
        label = '%s — %s' % (
            record.name,
            record.procurement_request_id.name or record.origin_id.name or record.representative_partner_id.display_name,
        )
        debit, credit = (account, source_account) if record.movement_type == 'funding' else (source_account, account)
        move = self.env['account.move'].sudo().with_company(company).with_context(**{INTERNAL: True}).create({
            'move_type': 'entry', 'company_id': company.id, 'journal_id': journal.id,
            'date': record.movement_date, 'ref': record.external_reference or label,
            'line_ids': [
                Command.create({'name': label, 'account_id': debit.id, 'partner_id': record.representative_partner_id.id, 'debit': record.amount,
                                'baseer_representative_petty_cash_id': original.id if debit == account else False}),
                Command.create({'name': label, 'account_id': credit.id, 'partner_id': record.representative_partner_id.id, 'credit': record.amount,
                                'baseer_representative_petty_cash_id': original.id if credit == account else False}),
            ],
        })
        move.action_post()
        petty_cash_line = move.line_ids.filtered(lambda line: line.account_id == account and line.partner_id == record.representative_partner_id)
        if petty_cash_line.credit:
            funding_domain = [
                ('account_id', '=', account.id), ('partner_id', '=', record.representative_partner_id.id),
                ('parent_state', '=', 'posted'), ('reconciled', '=', False), ('debit', '>', 0),
            ]
            # Historical returns remain tied to a particular funding movement.
            # New aggregate returns reconcile only real, marked funding debits
            # for that representative, never unrelated manual entries.
            if record.origin_id:
                funding_domain.append(('baseer_representative_petty_cash_id', '=', original.id))
            else:
                funding_domain.append(('baseer_representative_petty_cash_id', '!=', False))
            open_lines = self.env['account.move.line'].search([
                *funding_domain, ('id', '!=', petty_cash_line.id),
            ])
            (open_lines | petty_cash_line).reconcile()
        record.sudo().with_context(**{INTERNAL: True}).write({'move_id': move.id})
        if record.movement_type == 'return':
            original.invalidate_recordset(['return_ids', 'returned_amount', 'remaining_amount'])
        return record
