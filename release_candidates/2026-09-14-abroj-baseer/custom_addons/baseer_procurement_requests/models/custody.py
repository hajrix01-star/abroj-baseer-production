from datetime import timedelta

from odoo import api, fields, models, tools, _, Command
from odoo.exceptions import AccessError, UserError, ValidationError


INTERNAL = 'baseer_procurement_custody_internal'


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _baseer_assert_custody_lifecycle(self):
        """Keep custody source documents immutable in the native ledger.

        Custody corrections have explicit audited actions (a returned-cash
        event or a settlement reversal).  Resetting/cancelling/deleting the
        underlying native move would detach the operational source from the
        general ledger, so only moves carrying the immutable custody line link
        are protected.  Ordinary account moves remain untouched.
        """
        if not self:
            return
        protected = self.env['account.move.line'].sudo().search_count([
            ('move_id', 'in', self.ids),
            ('baseer_procurement_custody_id', '!=', False),
        ])
        if protected:
            raise UserError(_(
                'Purchasing-custody entries cannot be reset, cancelled, or deleted. '
                'Use the documented custody return or settlement-reversal action.'
            ))

    def button_draft(self):
        self._baseer_assert_custody_lifecycle()
        return super().button_draft()

    def button_cancel(self):
        self._baseer_assert_custody_lifecycle()
        return super().button_cancel()

    def _reverse_moves(self, default_values_list=None, cancel=False):
        self._baseer_assert_custody_lifecycle()
        return super()._reverse_moves(default_values_list=default_values_list, cancel=cancel)

    def unlink(self):
        self._baseer_assert_custody_lifecycle()
        return super().unlink()


class ResCompany(models.Model):
    _inherit = 'res.company'

    baseer_procurement_custody_account_id = fields.Many2one('account.account', string='Purchasing custody receivable', check_company=True)
    baseer_procurement_custody_journal_id = fields.Many2one('account.journal', string='Purchasing custody journal', check_company=True)

    def _baseer_procurement_custody_ready(self):
        self.ensure_one()
        account, journal = self.baseer_procurement_custody_account_id, self.baseer_procurement_custody_journal_id
        if (not account or self not in account.company_ids or not account.active or not account.reconcile
                or account.account_type not in ('asset_receivable', 'asset_current')):
            raise UserError(_('Configure an active reconcilable purchasing-custody receivable account first.'))
        if not journal or journal.company_id != self or not journal.active or journal.type != 'general':
            raise UserError(_('Configure an active general purchasing-custody journal first.'))
        return account, journal


class AccountMoveLine(models.Model):
    """Immutable source link for the native custody receivable entries.

    Reconciliation in Odoo is account/partner based.  Those two dimensions are
    deliberately not sufficient here: one representative can hold more than
    one open custody.  The link is put on the *native* receivable line, rather
    than inferred from a move reference, so return and settlement may only
    reconcile funding belonging to the same custody.
    """

    _inherit = 'account.move.line'

    baseer_procurement_custody_id = fields.Many2one(
        'baseer.procurement.custody', string='Purchasing custody source',
        readonly=True, copy=False, index=True, ondelete='restrict',
        check_company=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        if any('baseer_procurement_custody_id' in vals for vals in vals_list) and not (self.env.su and self.env.context.get(INTERNAL)):
            raise AccessError(_('Purchasing-custody source links are controlled by the server.'))
        return super().create(vals_list)

    def write(self, vals):
        if 'baseer_procurement_custody_id' in vals:
            raise AccessError(_('Purchasing-custody source links are immutable.'))
        return super().write(vals)


class ProcurementCustody(models.Model):
    _name = 'baseer.procurement.custody'
    _description = 'Purchasing representative custody'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'opened_on desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, readonly=True, default=lambda self: _('New'), copy=False, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True, ondelete='restrict', tracking=True)
    is_company_pool = fields.Boolean(
        string='Company custody pool', default=False, readonly=True, copy=False,
        help='The one shared purchasing-custody pool for a company. Legacy employee custodies remain individual records.',
    )
    # `employee_id` is kept for the original employee-custody records.  New
    # purchase representatives are external contacts and must not be created
    # as employees or suppliers just to hold an advance.
    employee_id = fields.Many2one('hr.employee', ondelete='restrict', check_company=True, tracking=True)
    representative_partner_id = fields.Many2one(
        'res.partner', string='Purchase representative', ondelete='restrict',
        check_company=True, tracking=True, index=True,
        help='External purchase representative.  Legacy employee custodies keep their employee link.',
    )
    opened_on = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    state = fields.Selection([('open', 'Open'), ('closed', 'Closed')], default='open', required=True, readonly=True, tracking=True)
    event_ids = fields.One2many('baseer.procurement.custody.event', 'custody_id', readonly=True)
    batch_line_ids = fields.One2many('baseer.purchase.batch.line', 'procurement_custody_id', readonly=True)
    settlement_ids = fields.One2many('baseer.procurement.custody.settlement', 'custody_id', readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    funded_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    returned_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    settled_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')
    balance = fields.Monetary(compute='_compute_totals', currency_field='currency_id')

    @api.constrains('employee_id', 'representative_partner_id')
    def _check_representative(self):
        for custody in self:
            if custody.is_company_pool:
                if custody.employee_id or custody.representative_partner_id:
                    raise ValidationError(_('The company custody pool does not have a fixed representative.'))
                continue
            if bool(custody.employee_id) == bool(custody.representative_partner_id):
                raise ValidationError(_('Choose exactly one employee or external purchase representative for a custody.'))

    def _representative_partner(self, representative_partner=False):
        """Return the native accounting partner for legacy and new custodies."""
        self.ensure_one()
        if self.employee_id and representative_partner:
            expected = self.employee_id.work_contact_id.commercial_partner_id
            supplied = representative_partner.commercial_partner_id
            if not expected or supplied != expected:
                raise ValidationError(_('A legacy employee custody cannot be posted for a different purchase representative.'))
        partner = representative_partner or self.representative_partner_id or self.employee_id.work_contact_id
        if not partner:
            raise ValidationError(_('The purchasing representative needs a contact before custody can be posted.'))
        partner = partner.commercial_partner_id
        if self.is_company_pool:
            if (not partner.active or 'is_purchase_representative' not in partner._fields
                    or not partner.with_company(self.company_id).is_purchase_representative):
                raise ValidationError(_('Choose an active contact marked as a purchase representative for the shared custody pool.'))
        return partner

    def _representative_matches_request(self, request, representative_partner=False):
        """Support the legacy employee request and the contact field added by PRC-CUSTODY2.

        The small field-name fallback deliberately lets this accounting module
        coexist with the operational request extension during rolling module
        upgrades; no request is silently matched by display name.
        """
        self.ensure_one()
        # Validate an explicit override even for legacy employee records;
        # otherwise a wrong UI value would be silently ignored.
        if representative_partner:
            self._representative_partner(representative_partner)
        if self.employee_id:
            # Compare ids rather than recordsets: batch allocation validation
            # may carry a request scoped to a different allowed-company env.
            return bool(request.purchaser_id and request.purchaser_id.id == self.employee_id.id)
        representative = self._representative_partner(representative_partner)
        partner_field = next((name for name in (
            'purchase_representative_id', 'procurement_representative_id',
            'representative_partner_id',
        ) if name in request._fields), False)
        if partner_field and request[partner_field]:
            return request[partner_field].commercial_partner_id == representative
        # Requests created before PRC-CUSTODY2 retain their employee-public
        # purchaser.  Match that employee's explicit work contact; never infer
        # a representative by display name.
        legacy_purchaser = request.purchaser_id
        legacy_contact = (
            legacy_purchaser.work_contact_id
            if legacy_purchaser and 'work_contact_id' in legacy_purchaser._fields else False
        )
        return bool(legacy_contact and legacy_contact.commercial_partner_id == representative)

    def _representative_balance(self, representative_partner=False):
        """Open custody balance for one representative within the shared pool."""
        self.ensure_one()
        representative = self._representative_partner(representative_partner)
        Event = self.env['baseer.procurement.custody.event']
        Settlement = self.env['baseer.procurement.custody.settlement']
        Event.flush_model(['custody_id', 'representative_partner_id', 'state', 'event_type', 'amount'])
        Settlement.flush_model(['custody_id', 'representative_partner_id', 'state', 'amount'])
        representative_filter = 'AND representative_partner_id = %s' if self.is_company_pool else ''
        event_params = [self.id] + ([representative.id] if self.is_company_pool else [])
        settlement_params = [self.id] + ([representative.id] if self.is_company_pool else [])
        self.env.cr.execute(f"""
            SELECT COALESCE(SUM(CASE WHEN event_type = 'funding' THEN amount ELSE -amount END), 0)
              FROM baseer_procurement_custody_event
             WHERE custody_id = %s AND state = 'posted' {representative_filter}
        """, event_params)
        event_balance = self.env.cr.fetchone()[0]
        self.env.cr.execute(f"""
            SELECT COALESCE(SUM(amount), 0)
              FROM baseer_procurement_custody_settlement
             WHERE custody_id = %s AND state = 'active' {representative_filter}
        """, settlement_params)
        settled = self.env.cr.fetchone()[0]
        return float(event_balance - settled)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if {'state'} & set(vals):
                raise AccessError(_('Custody state is controlled by the server.'))
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('baseer.procurement.custody') or _('New')
            if vals.get('is_company_pool'):
                company_id = vals.get('company_id') or self.env.company.id
                self.env.cr.execute('SELECT id FROM res_company WHERE id = %s FOR UPDATE', [company_id])
                if self.search_count([('company_id', '=', company_id), ('is_company_pool', '=', True)]):
                    raise ValidationError(_('This company already has a purchasing-custody pool.'))
        return super().create(vals_list)

    def _lock(self):
        self.flush_recordset(['state'])
        ids = tuple(sorted(self.ids))
        if not ids:
            return
        self.env.cr.execute(
            'SELECT id FROM baseer_procurement_custody WHERE id IN %s ORDER BY id FOR UPDATE',
            [ids],
        )
        # A no-op write turns the custody row into an MVCC mutex.  Under
        # Odoo/PostgreSQL repeatable-read, a waiter is retried with a fresh
        # snapshot instead of continuing after a concurrent month close with
        # a stale view of the close record.
        self.env.cr.execute(
            'UPDATE baseer_procurement_custody SET id = id WHERE id IN %s',
            [ids],
        )
        self.invalidate_recordset()

    @api.depends('event_ids.state', 'event_ids.event_type', 'event_ids.amount', 'settlement_ids.state', 'settlement_ids.amount')
    def _compute_totals(self):
        if not self:
            return
        Event = self.env['baseer.procurement.custody.event']
        Settlement = self.env['baseer.procurement.custody.settlement']
        Event.flush_model(['custody_id', 'state', 'event_type', 'amount'])
        Settlement.flush_model(['custody_id', 'state', 'amount'])
        self.env.cr.execute("""
            SELECT custody_id,
                   COALESCE(SUM(amount) FILTER (WHERE event_type = 'funding'), 0),
                   COALESCE(SUM(amount) FILTER (WHERE event_type = 'return'), 0)
              FROM baseer_procurement_custody_event
             WHERE custody_id IN %s AND state = 'posted'
             GROUP BY custody_id
        """, [tuple(self.ids)])
        event_totals = {row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()}
        self.env.cr.execute("""
            SELECT custody_id, COALESCE(SUM(amount), 0)
              FROM baseer_procurement_custody_settlement
             WHERE custody_id IN %s AND state = 'active'
             GROUP BY custody_id
        """, [tuple(self.ids)])
        settlement_totals = dict(self.env.cr.fetchall())
        for custody in self:
            funded, returned = event_totals.get(custody.id, (0, 0))
            settled = settlement_totals.get(custody.id, 0)
            custody.funded_amount = float(funded)
            custody.returned_amount = float(returned)
            custody.settled_amount = float(settled)
            custody.balance = custody.funded_amount - custody.returned_amount - custody.settled_amount

    def _require_manager(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_manager'):
            raise AccessError(_('Only a procurement manager can manage purchasing custody.'))

    def action_close(self):
        self._require_manager()
        for custody in self:
            custody._lock()
            if custody.currency_id.compare_amounts(custody.balance, 0):
                raise UserError(_('Custody %s cannot close while its balance is not zero.') % custody.display_name)
            super(ProcurementCustody, custody).write({'state': 'closed'})

    def write(self, vals):
        if 'state' in vals:
            raise AccessError(_('Custody state is controlled by the server.'))
        identity = {'name', 'company_id', 'is_company_pool', 'employee_id', 'representative_partner_id', 'opened_on'}
        if identity & set(vals):
            Event = self.env['baseer.procurement.custody.event']
            Settlement = self.env['baseer.procurement.custody.settlement']
            if (Event.search_count([('custody_id', 'in', self.ids), ('state', '=', 'posted')])
                    or Settlement.search_count([('custody_id', 'in', self.ids)])):
                raise UserError(_('Custody identity cannot change after financial activity. Use a new custody record or an offsetting correction.'))
        return super().write(vals)


class ProcurementCustodyMonthlyStatement(models.Model):
    """Read-only monthly reconciliation from posted native source documents."""

    _name = 'baseer.procurement.custody.monthly.statement'
    _description = 'Purchasing custody monthly statement'
    _auto = False
    _order = 'month_start desc, id desc'
    _check_company_auto = True

    custody_id = fields.Many2one('baseer.procurement.custody', readonly=True, ondelete='restrict', index=True)
    company_id = fields.Many2one('res.company', readonly=True, index=True)
    employee_id = fields.Many2one('hr.employee', readonly=True, index=True)
    representative_partner_id = fields.Many2one('res.partner', readonly=True, index=True)
    month_start = fields.Date(readonly=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    opening_balance = fields.Monetary(readonly=True, currency_field='currency_id')
    funded_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    settled_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    returned_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    closing_balance = fields.Monetary(readonly=True, currency_field='currency_id')

    def init(self):
        # Never mutate regular model tables here.  On a fresh installation this
        # report model can initialize before those tables exist; the post-init
        # hook rebuilds the view after ORM schema creation.  Upgrade-only DDL is
        # isolated in the versioned migration.
        tools.drop_view_if_exists(self.env.cr, self._table)
        if self._view_dependencies_ready():
            self._rebuild_view()

    @api.model
    def _view_dependencies_ready(self):
        self.env.cr.execute("""
            SELECT to_regclass('baseer_procurement_custody_event') IS NOT NULL
               AND to_regclass('baseer_procurement_custody_settlement') IS NOT NULL
               AND to_regclass('baseer_procurement_custody') IS NOT NULL
               AND to_regclass('account_move') IS NOT NULL
               AND to_regclass('hr_employee') IS NOT NULL
        """)
        return bool(self.env.cr.fetchone()[0])

    @api.model
    def _rebuild_view(self):
        if not self._view_dependencies_ready():
            return
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH activity AS (
                    SELECT event.custody_id, event.company_id,
                           COALESCE(event.representative_partner_id, employee.work_contact_id) AS representative_partner_id,
                           event.event_date::date AS activity_date,
                           CASE WHEN event.event_type = 'funding' THEN event.amount ELSE 0 END AS funded_amount,
                           CASE WHEN event.event_type = 'return' THEN event.amount ELSE 0 END AS returned_amount,
                           0::numeric AS settled_amount
                      FROM baseer_procurement_custody_event event
                      JOIN baseer_procurement_custody custody ON custody.id = event.custody_id
                 LEFT JOIN hr_employee employee ON employee.id = custody.employee_id
                     WHERE event.state = 'posted'
                    UNION ALL
                    -- Preserve the original supplier settlement in the
                    -- original accounting month, even after it is reversed.
                    SELECT settlement.custody_id, settlement.company_id,
                           COALESCE(settlement.representative_partner_id, employee.work_contact_id) AS representative_partner_id,
                           move.date::date AS activity_date,
                           0::numeric, 0::numeric, settlement.amount
                      FROM baseer_procurement_custody_settlement settlement
                      JOIN account_move move ON move.id = settlement.move_id
                      JOIN baseer_procurement_custody custody ON custody.id = settlement.custody_id
                 LEFT JOIN hr_employee employee ON employee.id = custody.employee_id
                     WHERE move.state = 'posted'
                    UNION ALL
                    -- The correction is a negative settlement in the month
                    -- of its own posted reversal move; it never rewrites the
                    -- original period's monthly evidence.
                    SELECT settlement.custody_id, settlement.company_id,
                           COALESCE(settlement.representative_partner_id, employee.work_contact_id) AS representative_partner_id,
                           reversal.date::date AS activity_date,
                           0::numeric, 0::numeric, -settlement.amount
                      FROM baseer_procurement_custody_settlement settlement
                      JOIN account_move reversal ON reversal.id = settlement.reversal_move_id
                      JOIN baseer_procurement_custody custody ON custody.id = settlement.custody_id
                 LEFT JOIN hr_employee employee ON employee.id = custody.employee_id
                     WHERE reversal.state = 'posted' AND settlement.state = 'reversed'
                ), monthly AS (
                    SELECT custody_id, company_id, representative_partner_id, date_trunc('month', activity_date)::date AS month_start,
                           SUM(funded_amount) AS funded_amount,
                           SUM(returned_amount) AS returned_amount,
                           SUM(settled_amount) AS settled_amount
                      FROM activity
                     GROUP BY custody_id, company_id, representative_partner_id, date_trunc('month', activity_date)::date
                ), balances AS (
                    SELECT monthly.*,
                           COALESCE(SUM(funded_amount - returned_amount - settled_amount) OVER (
                               PARTITION BY custody_id, representative_partner_id ORDER BY month_start
                               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                           ), 0::numeric) AS opening_balance
                      FROM monthly
                )
                SELECT ROW_NUMBER() OVER (
                           ORDER BY balances.month_start DESC, balances.custody_id DESC,
                                    balances.representative_partner_id DESC NULLS LAST
                       ) AS id,
                       balances.custody_id, balances.company_id, custody.employee_id,
                       COALESCE(balances.representative_partner_id, custody.representative_partner_id) AS representative_partner_id,
                       balances.month_start,
                       balances.opening_balance, balances.funded_amount, balances.settled_amount,
                       balances.returned_amount,
                       balances.opening_balance + balances.funded_amount - balances.settled_amount - balances.returned_amount AS closing_balance
                  FROM balances
                  JOIN baseer_procurement_custody custody ON custody.id = balances.custody_id
            )
        """)


class ProcurementCustodyPeriodClose(models.Model):
    """Immutable, non-financial evidence that a representative balance was carried.

    Funding, supplier settlement and returned cash remain native posted entries.
    Closing a month only snapshots those entries and carries the resulting balance
    into the next monthly statement; it never creates an accounting move.
    """

    _name = 'baseer.procurement.custody.period.close'
    _description = 'Purchasing custody month close'
    _order = 'month_start desc, id desc'
    _check_company_auto = True

    custody_id = fields.Many2one(
        'baseer.procurement.custody', required=True, ondelete='restrict',
        check_company=True, index=True,
    )
    company_id = fields.Many2one(
        related='custody_id.company_id', store=True, readonly=True, index=True,
    )
    representative_partner_id = fields.Many2one(
        'res.partner', string='Purchase representative', required=True,
        ondelete='restrict', check_company=True, index=True,
    )
    month_start = fields.Date(required=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    opening_balance = fields.Monetary(readonly=True, currency_field='currency_id')
    funded_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    settled_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    returned_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    carry_forward_amount = fields.Monetary(readonly=True, currency_field='currency_id')
    state = fields.Selection(
        [('draft', 'Draft'), ('closed', 'Closed')], default='draft',
        required=True, readonly=True, index=True,
    )
    closed_by_id = fields.Many2one('res.users', readonly=True, ondelete='restrict')
    closed_at = fields.Datetime(readonly=True)
    note = fields.Char()

    _baseer_procurement_custody_period_unique = models.Constraint(
        'unique(company_id, custody_id, representative_partner_id, month_start)',
        'This purchase representative already has a custody close for this month.',
    )

    @api.constrains('month_start')
    def _check_month_start(self):
        for close in self:
            if close.month_start and close.month_start.day != 1:
                raise ValidationError(_('Choose the first day of the month to close.'))

    @api.constrains('custody_id', 'representative_partner_id')
    def _check_representative_company(self):
        for close in self:
            partner = close.representative_partner_id
            if partner.company_id and partner.company_id != close.company_id:
                raise ValidationError(_('The purchase representative must belong to the custody company or be shared.'))
            close.custody_id._representative_partner(partner)

    def _require_accountant(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can close a custody month.'))

    @api.model_create_multi
    def create(self, vals_list):
        protected = {
            'company_id', 'opening_balance', 'funded_amount', 'settled_amount',
            'returned_amount', 'carry_forward_amount', 'state', 'closed_by_id', 'closed_at',
        }
        if any(protected & set(values) for values in vals_list):
            raise AccessError(_('Custody month-close totals and state are controlled by the server.'))
        normalized = []
        for values in vals_list:
            values = dict(values)
            if values.get('representative_partner_id'):
                partner = self.env['res.partner'].browse(values['representative_partner_id']).exists()
                values['representative_partner_id'] = partner.commercial_partner_id.id
            normalized.append(values)
        return super().create(normalized)

    @api.model
    def _ensure_month_open(self, custody, representative_partner, activity_date):
        custody._representative_partner(representative_partner)
        month_start = fields.Date.to_date(activity_date).replace(day=1)
        if self.search_count([
            ('company_id', '=', custody.company_id.id),
            ('custody_id', '=', custody.id),
            ('representative_partner_id', '=', representative_partner.commercial_partner_id.id),
            ('month_start', '=', month_start), ('state', '=', 'closed'),
        ]):
            raise ValidationError(_('This representative custody month is closed. Record any correction in an open month.'))

    def _snapshot(self):
        self.ensure_one()
        start = fields.Date.to_date(self.month_start)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        partner = self.representative_partner_id.commercial_partner_id
        Event = self.env['baseer.procurement.custody.event']
        Settlement = self.env['baseer.procurement.custody.settlement']
        Move = self.env['account.move']
        Event.flush_model([
            'custody_id', 'representative_partner_id', 'state',
            'event_type', 'event_date', 'amount',
        ])
        Settlement.flush_model([
            'custody_id', 'representative_partner_id', 'state',
            'move_id', 'reversal_move_id', 'amount',
        ])
        Move.flush_model(['date', 'state'])
        self.env.cr.execute("""
            SELECT
                COALESCE(SUM(amount) FILTER (
                    WHERE event_type = 'funding' AND event_date < %s
                ), 0),
                COALESCE(SUM(amount) FILTER (
                    WHERE event_type = 'return' AND event_date < %s
                ), 0),
                COALESCE(SUM(amount) FILTER (
                    WHERE event_type = 'funding' AND event_date >= %s AND event_date < %s
                ), 0),
                COALESCE(SUM(amount) FILTER (
                    WHERE event_type = 'return' AND event_date >= %s AND event_date < %s
                ), 0)
              FROM baseer_procurement_custody_event
             WHERE custody_id = %s
               AND representative_partner_id = %s
               AND state = 'posted'
        """, [start, start, start, next_month, start, next_month,
               self.custody_id.id, partner.id])
        prior_funded, prior_returned, funded, returned = self.env.cr.fetchone()
        # A reversed settlement remains evidence in its original month.  Its
        # reversal is a negative settlement on the correction move's date.
        self.env.cr.execute("""
            SELECT
                COALESCE(SUM(settlement.amount) FILTER (
                    WHERE original.date < %s
                ), 0),
                COALESCE(SUM(settlement.amount) FILTER (
                    WHERE reversal.date < %s AND reversal.state = 'posted'
                ), 0),
                COALESCE(SUM(settlement.amount) FILTER (
                    WHERE original.date >= %s AND original.date < %s
                ), 0),
                COALESCE(SUM(settlement.amount) FILTER (
                    WHERE reversal.date >= %s AND reversal.date < %s
                      AND reversal.state = 'posted'
                ), 0)
              FROM baseer_procurement_custody_settlement settlement
              JOIN account_move original ON original.id = settlement.move_id
         LEFT JOIN account_move reversal ON reversal.id = settlement.reversal_move_id
             WHERE settlement.custody_id = %s
               AND settlement.representative_partner_id = %s
               AND settlement.state IN ('active', 'reversed')
               AND original.state = 'posted'
        """, [start, start, start, next_month, start, next_month,
               self.custody_id.id, partner.id])
        prior_settled, prior_reversed, month_settled, month_reversed = self.env.cr.fetchone()
        opening = prior_funded - prior_returned - prior_settled + prior_reversed
        settled = month_settled - month_reversed
        closing = opening + funded - returned - settled
        return {
            'opening_balance': float(opening), 'funded_amount': float(funded),
            'settled_amount': float(settled), 'returned_amount': float(returned),
            'carry_forward_amount': float(closing),
        }

    def action_close(self):
        self._require_accountant()
        current_month = fields.Date.context_today(self).replace(day=1)
        for close in self:
            if close.state == 'closed':
                continue
            if close.month_start >= current_month:
                raise ValidationError(_('Only a completed month can be closed and carried forward.'))
            close.custody_id._lock()
            self.env.cr.execute(
                'SELECT id FROM baseer_procurement_custody_period_close WHERE id = %s FOR UPDATE',
                [close.id],
            )
            close.invalidate_recordset()
            if close.state == 'closed':
                continue
            values = close._snapshot()
            values.update({
                'state': 'closed', 'closed_by_id': self.env.user.id,
                'closed_at': fields.Datetime.now(),
            })
            super(ProcurementCustodyPeriodClose, close).write(values)
        return True

    def write(self, values):
        protected = {
            'custody_id', 'company_id', 'representative_partner_id', 'month_start',
            'opening_balance', 'funded_amount', 'settled_amount', 'returned_amount',
            'carry_forward_amount', 'state', 'closed_by_id', 'closed_at',
        }
        if self.filtered(lambda close: close.state == 'closed') and protected & set(values):
            raise UserError(_('A closed custody month is immutable. Record corrections in a later open month.'))
        if {'state', 'closed_by_id', 'closed_at'} & set(values):
            raise AccessError(_('Custody close state is controlled by the server.'))
        return super().write(values)

    def unlink(self):
        if self.filtered(lambda close: close.state == 'closed'):
            raise UserError(_('A closed custody month cannot be deleted.'))
        return super().unlink()


class ProcurementCustodyEvent(models.Model):
    _name = 'baseer.procurement.custody.event'
    _description = 'Purchasing custody event'
    _order = 'event_date desc, id desc'
    _check_company_auto = True

    custody_id = fields.Many2one('baseer.procurement.custody', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='custody_id.company_id', store=True, readonly=True, index=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    event_type = fields.Selection([('funding', 'Funding given to buyer'), ('return', 'Cash returned by buyer')], required=True, default='funding')
    event_date = fields.Date(required=True, default=fields.Date.context_today)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    cash_journal_id = fields.Many2one('account.journal', required=True, check_company=True, ondelete='restrict')
    custody_account_id = fields.Many2one(
        related='company_id.baseer_procurement_custody_account_id',
        string='Custody destination / source account', readonly=True,
    )
    representative_partner_id = fields.Many2one(
        'res.partner', string='Purchase representative', ondelete='restrict',
        check_company=True, index=True,
        help='Required for new movements in the shared company custody pool.',
    )
    procurement_request_id = fields.Many2one(
        'baseer.procurement.request', string='Received purchase request',
        ondelete='restrict', check_company=True, index=True, copy=False,
        help='Required once for funding the shared company custody pool; returns never carry a request.',
    )
    reference = fields.Char(
        help='Optional bank-transfer or cash-receipt reference. The accounting entry keeps the custody movement number when omitted.',
    )
    state = fields.Selection([('draft', 'Draft'), ('posted', 'Posted')], default='draft', required=True, readonly=True)
    move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict', check_company=True)

    @api.constrains('amount')
    def _check_amount(self):
        if any(event.amount <= 0 for event in self):
            raise ValidationError(_('Custody event amount must be positive.'))

    _baseer_procurement_custody_funding_request_unique = models.Constraint(
        'unique(procurement_request_id)',
        'A received purchase request can fund the shared custody pool only once.',
    )

    @api.constrains('custody_id', 'representative_partner_id', 'procurement_request_id', 'event_type')
    def _check_event_representative(self):
        for event in self:
            if event.custody_id.is_company_pool and not event.representative_partner_id:
                raise ValidationError(_('Choose the purchase representative for a company custody-pool movement.'))
            if event.event_type == 'return' and event.procurement_request_id:
                raise ValidationError(_('A custody return cannot be linked to a purchase request.'))
            if event.custody_id.is_company_pool and event.event_type == 'funding':
                request = event.procurement_request_id
                if not request:
                    raise ValidationError(_('Shared custody funding must be linked to a completed purchase request.'))
                if request.company_id != event.company_id:
                    raise ValidationError(_('The funding request must belong to the custody company.'))
                if request.state != 'purchased':
                    raise ValidationError(_('Only a completed quantity receipt can fund the shared custody pool.'))
                if not event.custody_id._representative_matches_request(request, event.representative_partner_id):
                    raise ValidationError(_('The funding representative must match the completed purchase request.'))

    def _representative_partner(self):
        self.ensure_one()
        return self.custody_id._representative_partner(self.representative_partner_id)

    @api.model_create_multi
    def create(self, vals_list):
        protected = {'company_id', 'state', 'move_id'}
        if any(protected & set(vals) for vals in vals_list):
            raise AccessError(_('Custody accounting links and state are controlled by the server.'))
        normalized = []
        for values in vals_list:
            values = dict(values)
            if values.get('representative_partner_id'):
                partner = self.env['res.partner'].browse(values['representative_partner_id']).exists()
                values['representative_partner_id'] = partner.commercial_partner_id.id
            normalized.append(values)
        return super().create(normalized)

    def _require_accountant(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can post purchasing-custody transfers.'))

    def _cash_account(self):
        self.ensure_one()
        journal, account = self.cash_journal_id, self.cash_journal_id.default_account_id
        if (journal.company_id != self.company_id or not journal.active or journal.type not in ('cash', 'bank')
                or not account or self.company_id not in account.company_ids or account.account_type != 'asset_cash'):
            raise ValidationError(_('Choose an active cash or bank journal from this company.'))
        return account

    def action_post(self):
        self._require_accountant()
        for event in self:
            event.custody_id._lock()
            locked_request_id = (
                event.procurement_request_id.id
                if event.custody_id.is_company_pool and event.event_type == 'funding'
                else False
            )
            if locked_request_id:
                self.env.cr.execute(
                    'SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE',
                    [locked_request_id],
                )
                self.env.cr.execute(
                    'UPDATE baseer_procurement_request SET id = id WHERE id = %s',
                    [locked_request_id],
                )
            self.env.cr.execute('SELECT id FROM baseer_procurement_custody_event WHERE id = %s FOR UPDATE', [event.id])
            event.invalidate_recordset()
            if event.state == 'posted':
                continue
            if event.custody_id.state != 'open':
                raise UserError(_('Custody must be open before posting an event.'))
            account, journal = event.company_id._baseer_procurement_custody_ready()
            cash, partner = event._cash_account(), event._representative_partner()
            if event.custody_id.is_company_pool and event.event_type == 'funding':
                request = event.procurement_request_id
                if request.id != locked_request_id:
                    raise UserError(_(
                        'The funding request changed concurrently. Reload the custody movement and try again.'
                    ))
                request.invalidate_recordset()
                # Validate again after the ordered custody -> request -> event
                # locks. `action_post` is idempotent for the same event; the
                # unique source link is the durable duplicate guard.
                if (request.company_id != event.company_id or request.state != 'purchased'
                        or not event.custody_id._representative_matches_request(request, partner)):
                    raise ValidationError(_('The shared custody funding no longer matches its completed purchase request.'))
                self.env.cr.execute(
                    '''SELECT id FROM baseer_procurement_custody_event
                         WHERE procurement_request_id = %s AND id != %s AND state = 'posted'
                         FOR KEY SHARE''', [request.id, event.id]
                )
                if self.env.cr.fetchone():
                    raise ValidationError(_('This completed purchase request already funded the shared custody pool.'))
            self.env['baseer.procurement.custody.period.close']._ensure_month_open(
                event.custody_id, partner, event.event_date
            )
            if event.company_id._get_violated_lock_dates(event.event_date, False, journal):
                raise ValidationError(_('The custody transfer date is locked. Choose an open accounting period.'))
            event_label = (event.reference or '').strip() or dict(event._fields['event_type'].selection).get(event.event_type)
            label = '%s — %s' % (event.custody_id.name, event_label)
            if (event.event_type == 'return'
                    and event.currency_id.compare_amounts(event.amount, event.custody_id._representative_balance(partner)) > 0):
                raise ValidationError(_('Returned cash cannot exceed the available custody balance.'))
            debit, credit = (account, cash) if event.event_type == 'funding' else (cash, account)
            move = self.env['account.move'].sudo().with_company(event.company_id).with_context(**{INTERNAL: True}).create({
                'move_type': 'entry', 'company_id': event.company_id.id, 'journal_id': journal.id, 'date': event.event_date, 'ref': label,
                'line_ids': [
                    Command.create({'name': label, 'account_id': debit.id, 'partner_id': partner.id, 'debit': event.amount,
                                    'baseer_procurement_custody_id': event.custody_id.id if debit == account else False}),
                    Command.create({'name': label, 'account_id': credit.id, 'partner_id': partner.id, 'credit': event.amount,
                                    'baseer_procurement_custody_id': event.custody_id.id if credit == account else False}),
                ],
            })
            move.action_post()
            custody_line = move.line_ids.filtered(lambda line: line.account_id == account and line.partner_id == partner)
            open_lines = self.env['account.move.line'].search([
                ('account_id', '=', account.id), ('partner_id', '=', partner.id), ('reconciled', '=', False),
                ('parent_state', '=', 'posted'), ('baseer_procurement_custody_id', '=', event.custody_id.id), ('id', '!=', custody_line.id),
            ])
            if custody_line.credit:
                (open_lines.filtered(lambda line: line.debit > 0) | custody_line).reconcile()
            super(ProcurementCustodyEvent, event).write({'state': 'posted', 'move_id': move.id})
        return True

    def write(self, vals):
        protected = {'custody_id', 'event_type', 'event_date', 'amount', 'cash_journal_id', 'representative_partner_id', 'procurement_request_id', 'reference', 'move_id', 'state', 'company_id'}
        if {'move_id', 'state', 'company_id'} & set(vals):
            raise AccessError(_('Custody accounting links and state are controlled by the server.'))
        if self.filtered(lambda event: event.state == 'posted') and protected & set(vals):
            raise UserError(_('Posted custody events are immutable. Post an offsetting event instead.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda event: event.state == 'posted'):
            raise UserError(_('Posted custody events cannot be deleted.'))
        return super().unlink()


class BaseerPurchaseBatchLine(models.Model):
    _inherit = 'baseer.purchase.batch.line'

    procurement_request_id = fields.Many2one('baseer.procurement.request', string='Procurement request', ondelete='restrict', check_company=True, index=True, copy=False)
    procurement_custody_id = fields.Many2one('baseer.procurement.custody', string='Purchasing custody', ondelete='restrict', check_company=True, index=True, copy=False)
    procurement_allocation_ids = fields.One2many('baseer.procurement.bill.allocation', 'batch_line_id', string='Request allocations', copy=False)
    procurement_allocated_amount = fields.Monetary(compute='_compute_procurement_allocation_totals', currency_field='currency_id', readonly=True)
    procurement_unallocated_amount = fields.Monetary(compute='_compute_procurement_allocation_totals', currency_field='currency_id', readonly=True)
    procurement_settlement_id = fields.Many2one('baseer.procurement.custody.settlement', compute='_compute_procurement_settlement', readonly=True)
    procurement_settlement_move_id = fields.Many2one('account.move', string='Custody settlement entry', compute='_compute_procurement_settlement', readonly=True)

    def _compute_procurement_settlement(self):
        records = self.env['baseer.procurement.custody.settlement'].sudo().search([('batch_line_id', 'in', self.ids)])
        by_line = {record.batch_line_id.id: record for record in records}
        by_line.update({record.batch_line_id.id: record for record in records.filtered(lambda record: record.state == 'active')})
        for line in self:
            settlement = by_line.get(line.id)
            line.procurement_settlement_id = settlement
            line.procurement_settlement_move_id = settlement.move_id if settlement else False

    @api.depends('gross_amount', 'procurement_allocation_ids.amount')
    def _compute_procurement_allocation_totals(self):
        for line in self:
            line.procurement_allocated_amount = sum(line.procurement_allocation_ids.mapped('amount'))
            line.procurement_unallocated_amount = line.gross_amount - line.procurement_allocated_amount

    @api.constrains('procurement_request_id', 'procurement_custody_id')
    def _check_procurement_link(self):
        for line in self:
            if line.procurement_request_id and line.procurement_request_id.company_id != line.company_id:
                raise ValidationError(_('The procurement request must belong to the batch company.'))
            if line.procurement_custody_id and line.procurement_custody_id.company_id != line.company_id:
                raise ValidationError(_('The custody must belong to the batch company.'))
            if line.procurement_custody_id:
                if line.procurement_custody_id.state != 'open':
                    raise ValidationError(_('Only an open custody can be linked to a supplier bill.'))
                if line.procurement_request_id and not line.procurement_custody_id._representative_matches_request(line.procurement_request_id):
                    raise ValidationError(_('The custody representative must match the request purchasing representative.'))

    def _normalize_procurement_custody_values(self, values):
        result = dict(values)
        custody_id = result.get('procurement_custody_id', self.procurement_custody_id.id if self else False)
        if custody_id:
            result.update({'is_credit': True, 'payment_method_line_id': False})
        return result

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._normalize_procurement_custody_values(values) for values in vals_list])

    def write(self, values):
        protected = {'procurement_request_id', 'procurement_custody_id'}
        if self.filtered(lambda line: line.batch_state == 'approved') and protected & set(values):
            raise UserError(_('Approved procurement links are immutable.'))
        if 'procurement_custody_id' in values and self.filtered('procurement_allocation_ids'):
            raise UserError(_('Clear request allocations before changing the purchasing custody.'))
        return super().write(self._normalize_procurement_custody_values(values))

    def _baseer_existing_request_allocations(self, request_ids):
        """Return active settled amounts without materializing settlement history.

        The request rows are locked by the caller, so this aggregate is both a
        bounded historical read and the final authority for over-allocation.
        It intentionally covers every custody in the company: the same
        completed request must never be consumed twice through two legacy
        custodies belonging to the same representative.
        """
        self.ensure_one()
        request_ids = tuple(sorted(set(request_ids)))
        if not request_ids:
            return {}
        Settlement = self.env['baseer.procurement.custody.settlement']
        Allocation = self.env['baseer.procurement.bill.allocation']
        BatchLine = self.env['baseer.purchase.batch.line']
        Batch = self.env['baseer.purchase.batch']
        Settlement.flush_model(['company_id', 'state', 'batch_line_id'])
        Allocation.flush_model(['request_id', 'batch_line_id', 'amount'])
        BatchLine.flush_model(['batch_id', 'procurement_request_id', 'gross_amount'])
        Batch.flush_model(['procurement_request_id'])
        self.env.cr.execute("""
            WITH consumed AS (
                SELECT line.procurement_request_id AS request_id,
                       line.gross_amount AS amount
                  FROM baseer_procurement_custody_settlement settlement
                  JOIN baseer_purchase_batch_line line ON line.id = settlement.batch_line_id
                 WHERE settlement.company_id = %s
                   AND settlement.state = 'active'
                   AND settlement.batch_line_id != %s
                   AND line.procurement_request_id IN %s
                UNION ALL
                SELECT batch.procurement_request_id AS request_id,
                       line.gross_amount AS amount
                  FROM baseer_procurement_custody_settlement settlement
                  JOIN baseer_purchase_batch_line line ON line.id = settlement.batch_line_id
                  JOIN baseer_purchase_batch batch ON batch.id = line.batch_id
                 WHERE settlement.company_id = %s
                   AND settlement.state = 'active'
                   AND settlement.batch_line_id != %s
                   AND line.procurement_request_id IS NULL
                   AND batch.procurement_request_id IN %s
                UNION ALL
                SELECT allocation.request_id, allocation.amount
                  FROM baseer_procurement_custody_settlement settlement
                  JOIN baseer_procurement_bill_allocation allocation
                    ON allocation.batch_line_id = settlement.batch_line_id
                 WHERE settlement.company_id = %s
                   AND settlement.state = 'active'
                   AND settlement.batch_line_id != %s
                   AND allocation.request_id IN %s
            )
            SELECT request_id, COALESCE(SUM(amount), 0)
              FROM consumed
             WHERE request_id IS NOT NULL
             GROUP BY request_id
        """, [
            self.company_id.id, self.id, request_ids,
            self.company_id.id, self.id, request_ids,
            self.company_id.id, self.id, request_ids,
        ])
        return {request_id: float(amount) for request_id, amount in self.env.cr.fetchall()}

    def _baseer_procurement_settle_custody(self):
        for line in self:
            custody = line.procurement_custody_id or line.batch_id.procurement_custody_id
            if not custody:
                continue
            if line.procurement_settlement_id and line.procurement_settlement_id.state == 'active':
                continue
            if not line.is_credit or line.payment_method_line_id:
                raise ValidationError(_('A custody-linked supplier bill must be credit-only.'))
            currency = line.company_id.currency_id
            request_link = line.procurement_request_id or line.batch_id.procurement_request_id
            representative = custody._representative_partner(line.batch_id.procurement_representative_partner_id)
            allocations = line.procurement_allocation_ids
            if allocations and request_link:
                raise ValidationError(_('Use either one legacy request link or request allocations, not both.'))
            if allocations:
                if currency.compare_amounts(sum(allocations.mapped('amount')), line.gross_amount):
                    raise ValidationError(_('Request allocations must equal the supplier-bill total before approval.'))
                allocation_amounts = [(allocation.request_id, allocation.amount) for allocation in allocations]
            elif request_link:
                allocation_amounts = [(request_link, line.gross_amount)]
            else:
                raise ValidationError(_('Link a procurement request or add request allocations before approving a custody bill.'))

            # The batch is locked by both approval and resettlement callers.
            # Financial ordering is then custody -> requests -> source work.
            custody._lock()
            if custody.state != 'open':
                raise UserError(_('The purchasing custody must remain open for settlement.'))
            requests = self.env['baseer.procurement.request'].browse(sorted({
                request.id for request, amount in allocation_amounts
            }))
            request_ids = tuple(requests.ids)
            self.env.cr.execute(
                'SELECT id FROM baseer_procurement_request WHERE id IN %s ORDER BY id FOR UPDATE',
                [request_ids],
            )
            # See ProcurementCustody._lock(): the no-op write forces a stale
            # concurrent allocator to retry rather than reuse an old snapshot.
            self.env.cr.execute(
                'UPDATE baseer_procurement_request SET id = id WHERE id IN %s',
                [request_ids],
            )
            requests.invalidate_recordset()
            existing = line._baseer_existing_request_allocations(request_ids)
            for request, amount in allocation_amounts:
                if request.state != 'purchased':
                    raise ValidationError(_('Only a completed quantity receipt can be settled against custody.'))
                if request.company_id != line.company_id or not custody._representative_matches_request(request, representative):
                    raise ValidationError(_('Each allocated request must belong to the custody representative and company.'))
                already = existing.get(request.id, 0.0)
                if currency.compare_amounts(already + amount, request.actual_total) > 0:
                    raise ValidationError(_('The request allocation exceeds its remaining actual-purchase total.'))
            if not line.move_id or line.move_id.state != 'posted':
                raise UserError(_('Approve the supplier bill before settling it against custody.'))
            account, journal = line.company_id._baseer_procurement_custody_ready()
            partner = representative
            # Recheck after the custody mutex.  If close won the race, its
            # committed state is authoritative and this settlement creates no
            # move. If settlement won, close waits and snapshots this move.
            self.env['baseer.procurement.custody.period.close']._ensure_month_open(
                custody, partner, line.invoice_date
            )
            if line.company_id._get_violated_lock_dates(line.invoice_date, False, journal):
                raise ValidationError(_('The custody settlement date is locked. Choose an open accounting period.'))
            if line.company_id.currency_id.compare_amounts(custody._representative_balance(partner), line.gross_amount) < 0:
                raise UserError(_('The available custody balance is not sufficient for this supplier bill.'))
            payable = line.move_id.line_ids.filtered(lambda entry: entry.account_id.account_type == 'liability_payable' and not entry.reconciled)
            if len(payable) != 1 or currency.compare_amounts(abs(payable.amount_residual), line.gross_amount):
                raise UserError(_('The supplier bill payable is not available for a full custody settlement.'))
            label = '%s — %s' % (custody.name, line.move_id.name)
            move = self.env['account.move'].sudo().with_company(line.company_id).with_context(**{INTERNAL: True}).create({
                'move_type': 'entry', 'company_id': line.company_id.id, 'journal_id': journal.id, 'date': line.invoice_date, 'ref': label,
                'line_ids': [
                    Command.create({'name': label, 'account_id': payable.account_id.id, 'partner_id': line.partner_id.id, 'debit': line.gross_amount}),
                    Command.create({'name': label, 'account_id': account.id, 'partner_id': partner.id, 'credit': line.gross_amount,
                                    'baseer_procurement_custody_id': custody.id}),
                ],
            })
            move.action_post()
            settlement_payable = move.line_ids.filtered(lambda entry: entry.account_id == payable.account_id)
            (payable | settlement_payable).reconcile()
            if line.move_id.payment_state != 'paid':
                raise UserError(_('The native supplier bill did not reconcile after custody settlement.'))
            custody_line = move.line_ids.filtered(lambda entry: entry.account_id == account and entry.partner_id == partner)
            open_custody = self.env['account.move.line'].search([
                ('account_id', '=', account.id), ('partner_id', '=', partner.id), ('reconciled', '=', False),
                ('parent_state', '=', 'posted'), ('baseer_procurement_custody_id', '=', custody.id), ('id', '!=', custody_line.id),
            ])
            (open_custody.filtered(lambda entry: entry.debit > 0) | custody_line).reconcile()
            self.env['baseer.procurement.custody.settlement'].sudo().create({
                'company_id': line.company_id.id, 'custody_id': custody.id, 'batch_line_id': line.id,
                'move_id': move.id, 'representative_partner_id': partner.id, 'amount': line.gross_amount,
            })
            line.invalidate_recordset(['procurement_settlement_id', 'procurement_settlement_move_id'])


class ProcurementBillAllocation(models.Model):
    """Immutable amount allocation of one supplier-bill row across requests.

    The native bill and its custody settlement still exist once per batch row.
    These rows only define which completed operational requests consume that
    amount, so an invoice may be partial or shared without duplicate bills.
    """

    _name = 'baseer.procurement.bill.allocation'
    _description = 'Supplier bill procurement-request allocation'
    _order = 'id'
    _check_company_auto = True

    batch_line_id = fields.Many2one('baseer.purchase.batch.line', required=True, ondelete='cascade', index=True, check_company=True)
    company_id = fields.Many2one(related='batch_line_id.company_id', store=True, readonly=True, index=True)
    custody_id = fields.Many2one(related='batch_line_id.procurement_custody_id', readonly=True, store=True, check_company=True)
    request_id = fields.Many2one('baseer.procurement.request', required=True, ondelete='restrict', index=True, check_company=True)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')

    _baseer_procurement_allocation_unique = models.Constraint(
        'unique(batch_line_id, request_id)',
        'A supplier-bill row can allocate a procurement request only once.',
    )

    @api.constrains('batch_line_id', 'request_id', 'amount')
    def _check_allocation(self):
        for allocation in self:
            line, request, custody = allocation.batch_line_id, allocation.request_id, allocation.custody_id
            if allocation.amount <= 0:
                raise ValidationError(_('A request allocation amount must be positive.'))
            if line.batch_state != 'draft':
                raise UserError(_('Approved supplier-bill allocations are immutable.'))
            if not custody:
                raise ValidationError(_('Choose the purchasing custody before allocating supplier-bill requests.'))
            if line.procurement_request_id:
                raise ValidationError(_('Clear the single procurement-request link before using request allocations.'))
            if request.company_id != line.company_id:
                raise ValidationError(_('Allocated requests must belong to the supplier-bill company.'))
            if request.state != 'purchased':
                raise ValidationError(_('Only completed quantity receipts can be allocated to a supplier bill.'))
            if not custody._representative_matches_request(request):
                raise ValidationError(_('Each allocated request must belong to the custody representative.'))
            if line.company_id.currency_id.compare_amounts(sum(line.procurement_allocation_ids.mapped('amount')), line.gross_amount) > 0:
                raise ValidationError(_('Request allocations cannot exceed the supplier-bill total.'))

    def write(self, vals):
        if self.filtered(lambda allocation: allocation.batch_line_id.batch_state == 'approved'):
            raise UserError(_('Approved supplier-bill allocations are immutable.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda allocation: allocation.batch_line_id.batch_state == 'approved'):
            raise UserError(_('Approved supplier-bill allocations cannot be deleted.'))
        return super().unlink()


class ProcurementCustodySettlement(models.Model):
    _name = 'baseer.procurement.custody.settlement'
    _description = 'Purchasing custody supplier settlement'
    _order = 'id desc'
    _check_company_auto = True

    company_id = fields.Many2one('res.company', required=True, readonly=True, index=True, ondelete='restrict')
    custody_id = fields.Many2one('baseer.procurement.custody', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    # Nullable only for historical settlements created before PRC-CUSTODY2.
    representative_partner_id = fields.Many2one('res.partner', readonly=True, index=True, ondelete='restrict', check_company=True)
    batch_line_id = fields.Many2one('baseer.purchase.batch.line', required=True, readonly=True, index=True, ondelete='restrict', check_company=True)
    move_id = fields.Many2one('account.move', required=True, readonly=True, ondelete='restrict', check_company=True)
    reversal_move_id = fields.Many2one('account.move', readonly=True, copy=False, ondelete='restrict', check_company=True)
    state = fields.Selection([('active', 'Active'), ('reversed', 'Reversed')], default='active', required=True, readonly=True, index=True)
    reversal_reason = fields.Char(copy=False)
    currency_id = fields.Many2one(related='company_id.currency_id', readonly=True)
    amount = fields.Monetary(required=True, readonly=True, currency_field='currency_id')

    @api.constrains('company_id', 'custody_id', 'batch_line_id', 'move_id', 'reversal_move_id')
    def _check_settlement_company(self):
        for settlement in self:
            if (settlement.custody_id.company_id != settlement.company_id
                    or (settlement.representative_partner_id.company_id and settlement.representative_partner_id.company_id != settlement.company_id)
                    or settlement.batch_line_id.company_id != settlement.company_id
                    or settlement.move_id.company_id != settlement.company_id
                    or (settlement.reversal_move_id and settlement.reversal_move_id.company_id != settlement.company_id)):
                raise ValidationError(_('Custody settlement records must stay within one company.'))

    def write(self, vals):
        allowed = {'reversal_reason'}
        if set(vals) - allowed or self.filtered(lambda settlement: settlement.state != 'active'):
            raise UserError(_('Custody settlements are immutable native-accounting links.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('Custody settlements cannot be deleted. Reverse the native accounting correction instead.'))

    def action_reverse(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can reverse a custody settlement.'))
        for settlement in self:
            with self.env.cr.savepoint():
                settlement.custody_id._lock()
                self.env.cr.execute('SELECT id FROM baseer_procurement_custody_settlement WHERE id = %s FOR UPDATE', [settlement.id])
                settlement.invalidate_recordset()
                if settlement.state != 'active' or settlement.reversal_move_id:
                    raise UserError(_('This custody settlement has already been reversed.'))
                if settlement.custody_id.state != 'open':
                    raise UserError(_('A settlement on a closed purchasing custody cannot be reversed. Contact the procurement accountant for an authorized correction.'))
                if not settlement.reversal_reason or not settlement.reversal_reason.strip():
                    raise ValidationError(_('Enter a reversal reason before reversing the custody settlement.'))
                if settlement.move_id.state != 'posted':
                    raise UserError(_('Only a posted native custody-settlement entry can be reversed.'))
                account, journal = settlement.company_id._baseer_procurement_custody_ready()
                reversal_date = fields.Date.context_today(self)
                representative = settlement.representative_partner_id or settlement.custody_id._representative_partner()
                self.env['baseer.procurement.custody.period.close']._ensure_month_open(
                    settlement.custody_id, representative, reversal_date
                )
                if settlement.company_id._get_violated_lock_dates(reversal_date, False, journal):
                    raise ValidationError(_('The reversal date is locked. Choose an open accounting period through the authorized correction process.'))
                original_payable = settlement.move_id.line_ids.filtered(lambda entry: entry.account_id.account_type == 'liability_payable')
                original_custody = settlement.move_id.line_ids.filtered(lambda entry: entry.account_id == account and entry.baseer_procurement_custody_id == settlement.custody_id)
                if len(original_payable) != 1 or len(original_custody) != 1:
                    raise UserError(_('The native custody-settlement entry is incomplete and cannot be reversed automatically.'))
                (original_payable | original_custody).remove_move_reconcile()
                label = '%s — %s' % (settlement.custody_id.name, _('Custody settlement reversal'))
                reversal = self.env['account.move'].sudo().with_company(settlement.company_id).with_context(**{INTERNAL: True}).create({
                'move_type': 'entry', 'company_id': settlement.company_id.id, 'journal_id': journal.id,
                'date': reversal_date, 'ref': '%s — %s' % (label, settlement.reversal_reason.strip()),
                'line_ids': [
                    Command.create({'name': label, 'account_id': account.id, 'partner_id': representative.id,
                                    'debit': settlement.amount, 'baseer_procurement_custody_id': settlement.custody_id.id}),
                    Command.create({'name': label, 'account_id': original_payable.account_id.id, 'partner_id': original_payable.partner_id.id,
                                    'credit': settlement.amount}),
                ],
                })
                reversal.action_post()
                reversal_payable = reversal.line_ids.filtered(lambda entry: entry.account_id == original_payable.account_id)
                reversal_custody = reversal.line_ids.filtered(lambda entry: entry.account_id == account and entry.baseer_procurement_custody_id == settlement.custody_id)
                (original_payable | reversal_payable).reconcile()
                (original_custody | reversal_custody).reconcile()
                super(ProcurementCustodySettlement, settlement).write({'state': 'reversed', 'reversal_move_id': reversal.id})
        return True


class ProcurementRequestCustodyBatch(models.Model):
    _inherit = 'baseer.procurement.request'

    procurement_batch_ids = fields.One2many(
        'baseer.purchase.batch', 'procurement_request_id',
        string='Supplier invoice batch', readonly=True,
    )


class BaseerPurchaseBatch(models.Model):
    _inherit = 'baseer.purchase.batch'

    # A purchase receipt is selected once in the batch header.  Keeping this
    # link on the batch prevents one invoice row accidentally consuming a
    # different operational request from the rest of the supplier entry.
    procurement_request_id = fields.Many2one(
        'baseer.procurement.request', string='Received purchase request',
        ondelete='restrict', check_company=True, index=True, copy=False,
    )
    procurement_custody_id = fields.Many2one(
        'baseer.procurement.custody', string='Purchasing custody',
        ondelete='restrict', check_company=True, index=True, copy=False,
    )
    procurement_representative_partner_id = fields.Many2one(
        'res.partner', string='Purchase representative', ondelete='restrict',
        check_company=True, index=True, copy=False,
        help='Required when the selected custody is the shared company pool.',
    )
    procurement_request_actual_total = fields.Monetary(
        related='procurement_request_id.actual_total', string='Received request total',
        currency_field='currency_id', readonly=True,
    )
    procurement_representative_balance = fields.Monetary(
        compute='_compute_procurement_representative_balance',
        string='Representative custody balance', currency_field='currency_id', readonly=True,
    )

    @api.depends(
        'procurement_custody_id', 'procurement_representative_partner_id',
        'procurement_custody_id.event_ids.state', 'procurement_custody_id.event_ids.event_type',
        'procurement_custody_id.event_ids.amount',
        'procurement_custody_id.settlement_ids.state', 'procurement_custody_id.settlement_ids.amount',
    )
    def _compute_procurement_representative_balance(self):
        for batch in self:
            if batch.procurement_custody_id and batch.procurement_representative_partner_id:
                batch.procurement_representative_balance = batch.procurement_custody_id._representative_balance(
                    batch.procurement_representative_partner_id
                )
            elif batch.procurement_custody_id and not batch.procurement_custody_id.is_company_pool:
                batch.procurement_representative_balance = batch.procurement_custody_id.balance
            else:
                batch.procurement_representative_balance = 0.0

    @api.onchange('procurement_request_id', 'procurement_custody_id')
    def _onchange_procurement_custody_header(self):
        for batch in self:
            request = batch.procurement_request_id
            if not request:
                batch.procurement_representative_partner_id = False
                continue
            representative = request.representative_partner_id
            if not representative and request.purchaser_id and 'work_contact_id' in request.purchaser_id._fields:
                representative = request.purchaser_id.work_contact_id
            batch.procurement_representative_partner_id = representative.commercial_partner_id if representative else False

    _baseer_procurement_batch_request_unique = models.Constraint(
        'unique(procurement_request_id)',
        'A received procurement request can be linked to only one purchase batch.',
    )

    @api.constrains('procurement_request_id', 'procurement_custody_id', 'procurement_representative_partner_id', 'company_id')
    def _check_procurement_header(self):
        for batch in self:
            request, custody = batch.procurement_request_id, batch.procurement_custody_id
            if request and request.company_id != batch.company_id:
                raise ValidationError(_('The received procurement request must belong to the batch company.'))
            if custody and custody.company_id != batch.company_id:
                raise ValidationError(_('The purchasing custody must belong to the batch company.'))
            if custody and custody.state != 'open':
                raise ValidationError(_('Only an open purchasing custody can be used by a supplier batch.'))
            if custody and custody.is_company_pool and not batch.procurement_representative_partner_id:
                raise ValidationError(_('Choose the purchase representative for a shared custody-pool batch.'))
            if request and custody and not custody._representative_matches_request(request, batch.procurement_representative_partner_id):
                raise ValidationError(_('The custody representative must match the received purchase request.'))

    def _header_custody_lines(self):
        return self.filtered('procurement_custody_id').line_ids

    def _force_header_custody_route(self):
        """No native direct payment is allowed when a batch uses custody."""
        for batch in self.filtered('procurement_custody_id'):
            batch.line_ids.write({'is_credit': True, 'payment_method_line_id': False})

    def create(self, vals_list):
        records = super().create(vals_list)
        with self.env.cr.savepoint():
            records._force_header_custody_route()
        return records

    def write(self, values):
        protected = {'procurement_request_id', 'procurement_custody_id', 'procurement_representative_partner_id'}
        if protected & set(values) and self.filtered(lambda batch: batch.state == 'approved'):
            raise UserError(_('Approved batch custody and request links are immutable.'))
        with self.env.cr.savepoint():
            result = super().write(values)
            if 'procurement_custody_id' in values:
                self._force_header_custody_route()
            return result

    def _validate_header_custody_batch(self):
        """Lock the receipt before native bills are created.

        The unique header link is the durable lock.  The row lock provides a
        useful deterministic error during concurrent approval before the SQL
        unique index is encountered, and protects installations upgrading from
        the older row-level model.
        """
        for batch in self:
            request, custody = batch.procurement_request_id, batch.procurement_custody_id
            if custody and not request:
                raise ValidationError(_('Choose the received purchase request before using purchasing custody.'))
            if custody and custody.is_company_pool and not batch.procurement_representative_partner_id:
                raise ValidationError(_('Choose the purchase representative for a shared custody-pool batch.'))
            if not request:
                continue
            if custody:
                custody._lock()
                if custody.state != 'open':
                    raise ValidationError(_('Only an open purchasing custody can be used by a supplier batch.'))
            self.env.cr.execute(
                'SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [request.id]
            )
            self.env.cr.execute(
                'UPDATE baseer_procurement_request SET id = id WHERE id = %s', [request.id]
            )
            request.invalidate_recordset()
            if request.state != 'purchased':
                raise ValidationError(_('Only a completed quantity receipt can be entered through purchasing custody.'))
            if request.company_id != batch.company_id:
                raise ValidationError(_('The received purchase request must belong to the batch company.'))
            if custody and not custody._representative_matches_request(request, batch.procurement_representative_partner_id):
                raise ValidationError(_('The received request and custody representative must belong together in this company.'))
            if batch.company_id.currency_id.compare_amounts(batch.amount_gross, request.actual_total):
                raise ValidationError(_('The total supplier-bill amount must equal the received purchase-request total.'))
            self.env.cr.execute(
                '''SELECT id FROM baseer_purchase_batch
                     WHERE procurement_request_id = %s AND id != %s
                     FOR KEY SHARE''', [request.id, batch.id]
            )
            if self.env.cr.fetchone():
                raise ValidationError(_('This received procurement request is already reserved by another purchase batch.'))
            if any(line.procurement_request_id or line.procurement_allocation_ids for line in batch.line_ids):
                raise ValidationError(_('Use the batch header request link; legacy row request allocations cannot be mixed with it.'))
            if custody and any(line.procurement_custody_id and line.procurement_custody_id != custody for line in batch.line_ids):
                raise ValidationError(_('All supplier rows must use the custody selected in the batch header.'))
            if custody and any(not line.is_credit or line.payment_method_line_id for line in batch.line_ids):
                raise ValidationError(_('A custody batch is credit-only and cannot create direct native payments.'))

    def action_approve(self):
        self.ensure_one()
        if (self.procurement_custody_id or self.line_ids.filtered('procurement_custody_id')) and not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can approve a custody-linked supplier bill.'))
        with self.env.cr.savepoint():
            # Super also locks, but taking the batch lock here establishes one
            # ordering for every custody approval before custody/request locks.
            self._lock_batches()
            if self.state != 'approved':
                self._force_header_custody_route()
                self._validate_header_custody_batch()
            result = super().action_approve()
            for batch in self:
                batch.line_ids._baseer_procurement_settle_custody()
            return result

    def action_resettle_custody(self):
        if not self.env.user.has_group('baseer_procurement_requests.group_procurement_accountant'):
            raise AccessError(_('Only a procurement accountant can resettle a custody-linked supplier bill.'))
        for batch in self:
            if batch.state != 'approved':
                raise UserError(_('Only an approved supplier-bill batch can be resettled.'))
            with self.env.cr.savepoint():
                batch._lock_batches()
                batch.line_ids._baseer_procurement_settle_custody()
        return self.action_view_bills()
