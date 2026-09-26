import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    baseer_receipt_enqueue_error = fields.Char(readonly=True, copy=False)

    @api.model
    def _process_order(self, order, existing_order):
        raw_action = order.pop('baseer_preparation_action', False)
        if not raw_action:
            return super()._process_order(order, existing_order)

        State = self.env['baseer.print.preparation.state']
        Event = self.env['baseer.print.preparation.event']
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can submit kitchen changes.'))
        action = State._normalize_action(raw_action)
        if order.get('state', 'draft') != 'draft':
            raise AccessError(_('Kitchen changes cannot be submitted while paying or closing an order.'))

        if existing_order:
            State._lock_order_state(existing_order)
        retry_events = Event._retry_events(action)
        if retry_events:
            retry_orders = retry_events.order_id
            if len(retry_orders) != 1 or not retry_orders.exists():
                raise ValidationError(_('The previous kitchen action no longer has a valid order.'))
            retry_order = retry_orders.ensure_one()
            retry_order.check_access_rights('read')
            retry_order.check_access_rule('read')
            if (retry_order.company_id not in self.env.companies
                    or (existing_order and retry_order != existing_order)
                    or retry_order.uuid != order.get('uuid')
                    or retry_order.session_id.id != order.get('session_id')):
                raise AccessError(_('This kitchen action does not belong to the synchronized order.'))
            return retry_order.id

        if existing_order:
            State._assert_order_can_prepare(existing_order)
            State._validate_expected_quantities(existing_order, action)
        elif any(line['expected_quantity'] for line in action['lines']):
            raise ValidationError(_('A new order cannot have an existing kitchen quantity.'))

        order_id = super()._process_order(order, existing_order)
        pos_order = self.browse(order_id).exists()
        if not pos_order:
            raise ValidationError(_('The synchronized point of sale order was not found.'))
        if not existing_order:
            State._lock_order_state(pos_order)
        State._apply_action(pos_order, action)
        return order_id

    def _baseer_assert_cancellation_batch(self, session_id):
        if not self or not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can cancel a kitchen order.'))
        self.check_access('read')
        if any(order.company_id not in self.env.companies for order in self):
            raise AccessError(_('This kitchen order does not belong to an allowed company.'))
        if len(self.company_id) != 1 or len(self.config_id) != 1 or len(self.session_id) != 1:
            raise ValidationError(_('Kitchen cancellations must contain orders from one point of sale session.'))
        session = self.env['pos.session'].browse(session_id).exists()
        if not session:
            raise AccessError(_('The point of sale session was not found.'))
        session.check_access_rights('read')
        session.check_access_rule('read')
        if (session != self.session_id or session.config_id != self.config_id
                or session.config_id.company_id != self.company_id or session.state not in ('opened', 'closing_control')):
            raise AccessError(_('The kitchen cancellation session is not active for these orders.'))
        if any(order.state != 'draft' for order in self):
            raise ValidationError(_('Only draft point of sale orders can be cancelled from the kitchen workflow.'))
        if any(order.payment_ids or order.account_move or order.is_refund
               or not order.currency_id.is_zero(order.amount_paid)
               or not order.currency_id.is_zero(order.amount_return) for order in self):
            raise ValidationError(_(
                'An order with payments, refunds or an invoice cannot be cancelled from the kitchen workflow. Resolve it through the native payment or refund workflow.'
            ))
        if not self.config_id.baseer_direct_print_enabled:
            raise AccessError(_('Baseer direct kitchen printing is disabled for this point of sale.'))
        return session

    def _baseer_preparation_states(self):
        return self.env['baseer.print.preparation.state']._states_for_orders(self)

    def baseer_preview_preparation_cancellations(self, session_id):
        self._baseer_assert_cancellation_batch(session_id)
        states = self._baseer_preparation_states()
        return {
            'order_ids': sorted(set(states.order_id.ids)),
            'count': len(set(states.order_id.ids)),
        }

    def baseer_cancel_with_preparation(self, session_id, reason_code, reason_note=False):
        return self.baseer_cancel_with_preparation_reasons(session_id, {
            str(order.id): {'reason_code': reason_code, 'reason_note': reason_note or ''}
            for order in self
        })

    def baseer_cancel_with_preparation_reasons(self, session_id, reasons_by_order):
        self._baseer_assert_cancellation_batch(session_id)
        Cancellation = self.env['baseer.print.cancellation']
        if not isinstance(reasons_by_order, dict) or set(reasons_by_order) != {str(order.id) for order in self}:
            raise ValidationError(_('Choose one cancellation reason for every kitchen order.'))
        normalized_reasons = {}
        for order in self:
            reason = reasons_by_order.get(str(order.id))
            if not isinstance(reason, dict):
                raise ValidationError(_('Choose one cancellation reason for every kitchen order.'))
            normalized_reasons[order.id] = Cancellation._normalized_reason(
                reason.get('reason_code'), reason.get('reason_note'),
            )
        State = self.env['baseer.print.preparation.state']
        State._lock_orders_states(self)
        # Refresh after the ordered locks so two overlapping cancellation batches
        # cannot create different records or printer jobs for the same order.
        orders = self.browse(sorted(self.ids)).exists()
        orders.invalidate_recordset()
        orders._baseer_assert_cancellation_batch(session_id)
        states = State._states_for_orders(orders)
        if set(states.order_id.ids) != set(orders.ids):
            raise ValidationError(_('Every order in this cancellation must already have a kitchen ticket.'))
        events = Cancellation
        jobs = self.env['baseer.print.job']
        for order in orders:
            order_states = states.filtered(lambda state: state.order_id == order)
            reason_code, reason_note = normalized_reasons[order.id]
            event = Cancellation._get_or_create_for_order(order, order_states, reason_code, reason_note)
            events |= event
            jobs |= State._enqueue_cancellation_jobs(order, event, order_states)
        # Native Odoo cancellation is deliberately invoked inside this same ORM
        # transaction. A failure rolls back the immutable audit event and jobs.
        orders._baseer_native_action_pos_order_cancel()
        return {
            'cancellation_ids': events.ids,
            'job_ids': jobs.ids,
            'pending': bool(jobs.filtered(lambda job: job.state == 'pending')),
        }

    def _baseer_native_action_pos_order_cancel(self):
        return super().action_pos_order_cancel()

    def _baseer_requires_cancellation_event(self):
        states = self.env['baseer.print.preparation.state'].sudo().search([('order_id', 'in', self.ids)])
        return states.mapped('order_id')

    def _baseer_assert_cancellation_events_exist(self):
        protected = self._baseer_requires_cancellation_event().filtered(lambda order: order.state == 'draft')
        if not protected:
            return
        events = self.env['baseer.print.cancellation'].sudo().search([('order_id', 'in', protected.ids)])
        missing = protected - events.mapped('order_id')
        if missing:
            raise AccessError(_('A kitchen order must be cancelled through the documented kitchen cancellation workflow.'))

    def action_pos_order_paid(self):
        result = super().action_pos_order_paid()
        for order in self:
            if (order.config_id.baseer_direct_print_enabled
                    and not order.config_id.baseer_native_receipt_enabled):
                # A printer failure must never roll back native payment.
                try:
                    with self.env.cr.savepoint():
                        job = self.env['baseer.print.job']._enqueue_receipt(order)
                        if not job:
                            raise ValidationError(_('The customer receipt printer is not ready.'))
                        order.baseer_receipt_enqueue_error = False
                except Exception as error:
                    _logger.exception('Customer receipt enqueue failed for POS order %s', order.id)
                    order.baseer_receipt_enqueue_error = (
                        str(error) if isinstance(error, UserError)
                        else _('The receipt service failed. Ask a manager to inspect the server log.')
                    )
        return result

    def baseer_customer_receipt_status(self):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can print customer receipts.'))
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('This order does not belong to an allowed company.'))
        job = self.env['baseer.print.job'].sudo().search([
            ('source_order_id', '=', self.id), ('ticket_type', '=', 'receipt'),
        ], order='id desc', limit=1)
        return {'job_id': job.id, 'state': job.state,
                'error': self.baseer_receipt_enqueue_error or False}

    def baseer_enqueue_native_receipt(self, jpeg_base64):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can print customer receipts.'))
        self.check_access_rights('read')
        self.check_access_rule('read')
        job = self.env['baseer.print.job']._enqueue_native_receipt(self, jpeg_base64)
        return {'job_id': job.id, 'state': job.state}

    def action_pos_order_cancel(self):
        self._baseer_assert_cancellation_events_exist()
        return super().action_pos_order_cancel()

    def write(self, vals):
        if vals.get('state') == 'cancel':
            self._baseer_assert_cancellation_events_exist()
        return super().write(vals)

    def unlink(self):
        self._baseer_assert_cancellation_events_exist()
        return super().unlink()

    def baseer_enqueue_preparation_jobs(
            self, client_event_uuid=False, reason_code=False, reason_note=False):
        self.ensure_one()
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can send preparation tickets.'))
        return self.env['baseer.print.preparation.state']._enqueue_order(
            self, client_event_uuid, reason_code, reason_note,
        )
