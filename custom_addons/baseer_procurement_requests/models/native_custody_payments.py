from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        enabled_by_default = self.env.context.get('default_is_purchase_representative')
        enabled = [vals.get('is_purchase_representative', enabled_by_default) for vals in vals_list]
        account = False
        if any(enabled) and self._baseer_can_provision_custody_journal():
            account = self._baseer_lock_custody_journal_creation()
        partners = super().create(vals_list)
        if account:
            partners.browse([
                partner.id for partner, is_enabled in zip(partners, enabled) if is_enabled
            ])._baseer_provision_custody_journals(account)
        return partners

    def write(self, vals):
        activating = self.browse()
        if vals.get('is_purchase_representative') and self._baseer_can_provision_custody_journal():
            activating = self.filtered(lambda partner: not partner.is_purchase_representative)
        account = activating and self._baseer_lock_custody_journal_creation()
        result = super().write(vals)
        if account:
            activating._baseer_provision_custody_journals(account)
        return result

    def _baseer_can_provision_custody_journal(self):
        user = self.env.user
        return self.env.su or user.has_group('baseer_procurement_requests.group_procurement_manager') or user.has_group(
            'account.group_account_manager',
        )

    def _baseer_is_custody_representative(self, company):
        self.ensure_one()
        return (
            self.active and not self.is_company and not self.parent_id
            and (not self.company_id or self.company_id == company)
            and self.with_company(company).is_purchase_representative
        )

    def _baseer_lock_custody_journal_creation(self):
        company = self.env.company
        account = company.sudo().baseer_procurement_representative_petty_cash_account_id
        if not account.active or company not in account.company_ids:
            return False
        # Keep the company-before-contact lock order used by custody settlement.
        # A row update makes concurrent journal creation retry in a fresh snapshot.
        self.env.cr.execute('UPDATE res_company SET id = id WHERE id = %s', [company.id])
        return account

    def _baseer_provision_custody_journals(self, account):
        company = self.env.company
        representatives = self.filtered(lambda partner: partner._baseer_is_custody_representative(company))
        if not representatives:
            return
        journals = self.env['account.journal'].sudo().with_context({}, lang=self.env.lang).with_company(company)
        linked = journals.with_context(active_test=False).search([
            ('company_id', '=', company.id),
            ('baseer_custody_representative_id', 'in', representatives.ids),
        ])
        pending = representatives - linked.baseer_custody_representative_id
        if pending:
            journals.create([{
                'name': _('Custody %s', representative.name),
                'company_id': company.id,
                'type': 'cash',
                'default_account_id': account.id,
                'baseer_custody_representative_id': representative.id,
            } for representative in pending])

    def action_baseer_open_custody_journal(self):
        self.ensure_one()
        self.check_access('read')
        if not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can set up a custody journal.'))
        company = self.env.company
        if not self._baseer_is_custody_representative(company):
            raise ValidationError(_('Select an active purchasing representative of this company.'))
        journal_domain = [
            ('company_id', '=', company.id),
            ('baseer_custody_representative_id', '=', self.id),
        ]
        journals = self.env['account.journal'].with_context(active_test=False).search(journal_domain)
        account = company.baseer_procurement_representative_petty_cash_account_id
        if not journals and not account:
            raise ValidationError(_('Configure the company’s representative custody account first.'))
        action = self.env['ir.actions.actions']._for_xml_id('account.action_account_journal_form')
        action.update(
            name=_('Custody journal'),
            context=dict(
                self.env.context,
                default_name=_('Custody %s', self.name),
                default_company_id=company.id,
                default_type='cash',
                default_baseer_custody_representative_id=self.id,
                default_default_account_id=account.id,
                active_test=False,
            ),
            domain=journal_domain,
        )
        if len(journals) <= 1:
            action.update(
                view_mode='form',
                views=[(self.env.ref('account.view_account_journal_form').id, 'form')],
                res_id=journals.id,
            )
        return action


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    baseer_custody_representative_id = fields.Many2one(
        'res.partner',
        string='Custody representative',
        check_company=True,
        ondelete='restrict',
        copy=False,
        groups='account.group_account_manager',
        help=(
            'This permanent assignment includes past and future posted supplier payments from this journal '
            'in this representative’s custody.'
        ),
    )

    @api.onchange('baseer_custody_representative_id')
    def _onchange_baseer_custody_representative_id(self):
        if not self._origin and self.baseer_custody_representative_id and self.type in ('cash', 'bank'):
            self.default_account_id = self.company_id.baseer_procurement_representative_petty_cash_account_id

    @api.model_create_multi
    def create(self, vals_list):
        context = self.env.context
        for vals in vals_list:
            representative_id = vals.get(
                'baseer_custody_representative_id', context.get('default_baseer_custody_representative_id'),
            )
            journal_type = vals.get('type', context.get('default_type'))
            if representative_id and journal_type in ('cash', 'bank'):
                company_id = vals.get('company_id', context.get('default_company_id'))
                company = self.env['res.company'].browse(company_id) or self.env.company
                vals.setdefault('baseer_custody_representative_id', representative_id)
                vals.setdefault('type', journal_type)
                vals.setdefault('company_id', company.id)
                if context.get('default_name'):
                    vals.setdefault('name', context['default_name'])
                if not vals.get('default_account_id'):
                    vals['default_account_id'] = company.baseer_procurement_representative_petty_cash_account_id.id
        journals = super().create(vals_list)
        mapped_journals = journals.sudo().filtered('baseer_custody_representative_id')
        for journal in journals & mapped_journals:
            methods = journal.inbound_payment_method_line_ids | journal.outbound_payment_method_line_ids
            methods.filtered(lambda method: method.code == 'manual' and not method.payment_account_id).write({
                'payment_account_id': journal.default_account_id.id,
            })
        return journals

    @api.constrains('baseer_custody_representative_id', 'company_id', 'type', 'default_account_id')
    def _check_baseer_custody_representative(self):
        for journal in self.sudo().filtered('baseer_custody_representative_id'):
            company = journal.company_id
            if not journal.baseer_custody_representative_id._baseer_is_custody_representative(company):
                raise ValidationError(_('Select an active purchasing representative of this company.'))
            if (journal.type not in ('cash', 'bank') or not journal.default_account_id.active
                    or journal.default_account_id != company.baseer_procurement_representative_petty_cash_account_id):
                raise ValidationError(_(
                    'Use a cash or bank journal whose default account is the company’s representative custody account.'
                ))

    def write(self, vals):
        protected_fields = {
            'baseer_custody_representative_id', 'company_id', 'type', 'default_account_id',
        } & vals.keys()
        if protected_fields and self:
            self.check_access('write')
            for name in protected_fields:
                self._check_field_access(self._fields[name], 'write')
            self.env.cr.execute(
                'SELECT id FROM account_journal WHERE id IN %s ORDER BY id FOR NO KEY UPDATE', [tuple(self.ids)],
            )
            self.invalidate_recordset(['baseer_custody_representative_id', *sorted(protected_fields)])
            journals = self.sudo().filtered('baseer_custody_representative_id')
            for journal in journals:
                if any(
                    vals[name] != (journal[name].id if name != 'type' else journal[name])
                    for name in protected_fields
                ):
                    raise ValidationError(_(
                        'This custody journal already belongs to a representative. '
                        'Use a separate journal for the new representative.'
                    ))
        return super().write(vals)


class RepresentativeAdvance(models.Model):
    _inherit = 'baseer.procurement.representative.advance'

    @api.model
    def _flush_native_custody_activity(self):
        fields_by_model = {
            'account.journal': ['baseer_custody_representative_id', 'company_id', 'default_account_id'],
            'account.payment': ['company_id', 'journal_id', 'move_id', 'partner_type', 'invoice_ids'],
            'account.move': ['company_id', 'journal_id', 'state', 'date', 'name', 'ref', 'move_type', 'reversed_entry_id'],
            'account.move.line': ['company_id', 'move_id', 'account_id', 'balance'],
            'account.account': ['account_type'],
            'account.partial.reconcile': ['debit_move_id', 'credit_move_id'],
            'baseer.procurement.representative.advance': ['company_id', 'move_id'],
            'baseer.procurement.representative.advance.settlement': ['company_id', 'move_id'],
            'baseer.procurement.representative.petty.cash.invoice.settlement': ['company_id', 'move_id'],
            'baseer.procurement.custody.settlement': ['company_id', 'move_id', 'reversal_move_id'],
            'baseer.procurement.custody.event': ['company_id', 'move_id'],
        }
        for model, fields_to_flush in fields_by_model.items():
            self.env[model].flush_model(fields_to_flush)

    @api.model
    def _native_custody_activity_sql(self):
        """Read signed native custody movements, once per posted journal entry."""
        return """
            WITH RECURSIVE internal_entries AS (
                SELECT move_id FROM baseer_procurement_representative_advance
                 WHERE company_id = %(company)s
                UNION ALL
                SELECT move_id FROM baseer_procurement_representative_advance_settlement
                 WHERE company_id = %(company)s
                UNION ALL
                SELECT move_id FROM baseer_procurement_representative_petty_cash_invoice_settlement
                 WHERE company_id = %(company)s
                UNION ALL
                SELECT move_id FROM baseer_procurement_custody_settlement
                 WHERE company_id = %(company)s
                UNION ALL
                SELECT reversal_move_id FROM baseer_procurement_custody_settlement
                 WHERE company_id = %(company)s
                UNION ALL
                SELECT move_id FROM baseer_procurement_custody_event
                 WHERE company_id = %(company)s
            ), native_entries AS (
              (
                SELECT DISTINCT ON (entry.id)
                       entry.id, journal.baseer_custody_representative_id AS partner_id,
                       journal.default_account_id AS account_id, payment.id AS payment_id, entry.id AS payment_move_id
                  FROM account_journal journal
                  JOIN account_payment payment
                    ON payment.journal_id = journal.id AND payment.company_id = journal.company_id
                  JOIN account_move entry
                    ON entry.id = payment.move_id AND entry.company_id = journal.company_id
                   AND entry.journal_id = journal.id AND entry.state = 'posted' AND entry.move_type = 'entry'
                 WHERE journal.company_id = %(company)s AND journal.baseer_custody_representative_id IS NOT NULL
                   AND (%(partner)s IS NULL OR journal.baseer_custody_representative_id = %(partner)s)
                   AND payment.partner_type = 'supplier' AND entry.reversed_entry_id IS NULL
                   AND NOT EXISTS (SELECT 1 FROM internal_entries WHERE move_id = entry.id)
                 ORDER BY entry.id, payment.id
              )
                UNION
                SELECT reversal.id, original.partner_id, original.account_id,
                       original.payment_id, original.payment_move_id
                  FROM native_entries original
                  JOIN account_move reversal ON reversal.reversed_entry_id = original.id
                 WHERE reversal.company_id = %(company)s AND reversal.state = 'posted'
                   AND NOT EXISTS (SELECT 1 FROM internal_entries WHERE move_id = reversal.id)
            ), amounts AS (
                SELECT native.id, native.partner_id, native.payment_id, native.payment_move_id,
                       -SUM(line.balance::numeric) AS amount
                  FROM native_entries native
                  JOIN account_move_line line
                    ON line.move_id = native.id AND line.account_id = native.account_id
                   AND line.company_id = %(company)s
                 GROUP BY native.id, native.partner_id, native.payment_id, native.payment_move_id
                HAVING SUM(line.balance::numeric) <> 0
            )
            SELECT amounts.id, amounts.partner_id, entry.date AS day, amounts.amount,
                   COALESCE(bills.reference, NULLIF(entry.ref, ''), entry.name) AS reference
              FROM amounts
              JOIN account_move entry ON entry.id = amounts.id
              LEFT JOIN LATERAL (
                  SELECT STRING_AGG(DISTINCT bill.name, ' · ' ORDER BY bill.name) AS reference
                    FROM (
                        SELECT relation.invoice_id
                          FROM account_move__account_payment relation
                         WHERE relation.payment_id = amounts.payment_id
                        UNION
                        SELECT counterpart.move_id
                          FROM account_move_line payable
                          JOIN account_account account
                            ON account.id = payable.account_id AND account.account_type = 'liability_payable'
                          JOIN account_partial_reconcile part
                            ON payable.id IN (part.debit_move_id, part.credit_move_id)
                          JOIN account_move_line counterpart
                            ON counterpart.id = CASE WHEN payable.id = part.debit_move_id
                                                     THEN part.credit_move_id ELSE part.debit_move_id END
                         WHERE payable.move_id = amounts.payment_move_id
                           AND payable.company_id = %(company)s AND counterpart.company_id = %(company)s
                    ) linked
                    JOIN account_move bill ON bill.id = linked.invoice_id
                   WHERE bill.company_id = %(company)s AND bill.state = 'posted'
                     AND bill.move_type IN ('in_invoice', 'in_refund', 'in_receipt')
              ) bills ON TRUE
        """
