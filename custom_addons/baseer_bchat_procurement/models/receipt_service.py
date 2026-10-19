"""A bounded BChat receipt boundary reusing the native procurement workflow."""
import hashlib
import json
import logging
import re
from decimal import Decimal
from uuid import uuid4

from odoo import api, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.baseer_bchat.contracts import ProtocolError, canonical_uuid, positive_id
from odoo.addons.baseer_procurement_requests.models.procurement import (
    BCHAT_RECEIPT_INTERNAL, _decimal_input, _decimal_total,
)

from .service import MAX_CART_LINES, MAX_RESPONSE_BYTES, MAX_ROOM_MESSAGE_BYTES


RECEIPT_PAGE_SIZE = 30
QUANTITY_PATTERN = re.compile(r'(?:[1-9][0-9]{0,5}|0)(?:\.[0-9]{1,2})?\Z')
PRICE_PATTERN = re.compile(r'(?:[1-9][0-9]{0,8}|0)(?:\.[0-9]{1,2})?\Z')
_logger = logging.getLogger(__name__)


class BChatReceiptService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _receipt_scope(self, company_id):
        return self._order_receive_scope(company_id)

    @api.model
    def _receipt_order(self, scoped, order_id):
        order_id = positive_id(order_id, 'order_id')
        order = scoped.env['baseer.procurement.request'].sudo().with_company(
            scoped.env.company,
        ).search([
            ('id', '=', order_id), ('company_id', '=', scoped.env.company.id),
            ('source_channel', '=', 'bchat'),
        ], limit=1)
        if not order:
            raise ProtocolError('not_found', 'This receipt request is unavailable.', 404)
        return order

    @api.model
    def _receipt_line_data(self, line):
        option = line.option_id
        return {
            'line_id': line.id,
            'product_name': self._label(option.product_id.name),
            'option_name': self._label(option.name),
            'uom_name': self._label(option.uom_id.display_name, 80),
            'requested_qty': format(Decimal(str(line.requested_qty)), '.2f'),
            'manager_received_qty': format(Decimal(str(line.manager_received_qty)), '.2f'),
        }

    @api.model
    def _receipt_summary(self, order):
        return {
            'id': order.id, 'name': self._label(order.name, 80),
            'state': order.state, 'company_id': order.company_id.id,
            'warehouse_name': self._label(order.warehouse_id.display_name),
            'submitted_at': self._stamp(order.internal_submitted_at),
            'requester_name': self._label(order.requester_id.name),
            'requested_total': self._money(order.requested_total),
            'currency_symbol': self._label(order.currency_id.symbol or order.currency_id.name, 16),
        }

    @api.model
    def _v2_receipts(self, company_id, before_id=None):
        scoped = self._receipt_scope(company_id)
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        domain = [('company_id', '=', scoped.env.company.id),
                  ('source_channel', '=', 'bchat'), ('state', 'in', ('sent', 'received'))]
        if before_id:
            domain.append(('id', '<', before_id))
        orders = scoped.env['baseer.procurement.request'].sudo().with_company(
            scoped.env.company,
        ).search(domain, order='id desc', limit=RECEIPT_PAGE_SIZE + 1)
        page = orders[:RECEIPT_PAGE_SIZE]
        response = {
            'api_version': 2,
            'orders': [scoped._receipt_summary(order) for order in page],
            'next_before_id': page[-1].id if len(orders) > RECEIPT_PAGE_SIZE else None,
        }
        if len(json.dumps(response, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('page_too_large', 'Receipt page exceeds 64 KiB.', 413)
        return response

    @api.model
    def _v2_receipt_detail(self, company_id, order_id):
        scoped = self._receipt_scope(company_id)
        order = scoped._receipt_order(scoped, order_id)
        lines = order.line_ids.sorted('id')
        if not lines or len(lines) > MAX_CART_LINES:
            raise ProtocolError('too_many_lines', 'Receipt needs 1–100 lines.', 413)
        response = {
            'api_version': 2, 'order': scoped._receipt_summary(order),
            'lines': [scoped._receipt_line_data(line) for line in lines],
        }
        if len(json.dumps(response, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('page_too_large', 'Receipt detail exceeds 64 KiB.', 413)
        return response

    @staticmethod
    def _receipt_decimal(raw, label, pattern):
        if not isinstance(raw, str) or len(raw) > 12 or not pattern.fullmatch(raw):
            raise ProtocolError('invalid_payload', '%s is invalid.' % label)
        try:
            return _decimal_input(raw, label)
        except ValidationError:
            raise ProtocolError('invalid_payload', '%s is invalid.' % label) from None

    @api.model
    def _v2_receipt_confirm(self, order_id, payload):
        if type(payload) is not dict or set(payload) != {
                'api_version', 'company_id', 'client_uuid', 'lines'}:
            raise ProtocolError('invalid_payload', 'Unexpected receipt fields.')
        if type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported receipt API version.')
        company_id = positive_id(payload['company_id'], 'company_id')
        order_id = positive_id(order_id, 'order_id')
        token = canonical_uuid(payload['client_uuid'])
        raw_lines = payload['lines']
        if type(raw_lines) is not list or not 1 <= len(raw_lines) <= MAX_CART_LINES:
            raise ProtocolError('invalid_payload', 'Receipt needs 1–100 lines.')
        normalized = []
        seen = set()
        for row in raw_lines:
            if type(row) is not dict or set(row) != {'line_id', 'actual_qty', 'actual_price'}:
                raise ProtocolError('invalid_payload', 'A receipt line is invalid.')
            line_id = positive_id(row['line_id'], 'line_id')
            if line_id in seen:
                raise ProtocolError('invalid_payload', 'A receipt line appears twice.')
            seen.add(line_id)
            quantity = self._receipt_decimal(row['actual_qty'], 'Quantity', QUANTITY_PATTERN)
            price = self._receipt_decimal(row['actual_price'], 'Unit price', PRICE_PATTERN)
            if quantity < 0 or price < 0 or (quantity > 0 and price <= 0) or (quantity == 0 and price != 0):
                raise ProtocolError('invalid_payload', 'Actual quantity and price are inconsistent.')
            normalized.append({
                'line_id': line_id, 'actual_qty': format(quantity, '.2f'),
                'actual_price': format(price, '.2f'),
            })
        if not any(Decimal(row['actual_qty']) > 0 for row in normalized):
            raise ProtocolError('invalid_payload', 'At least one item must be received.')
        normalized.sort(key=lambda row: row['line_id'])
        digest = hashlib.sha256(json.dumps({
            'company_id': company_id, 'order_id': order_id, 'lines': normalized,
        }, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

        # These checks precede both sudo and any foreign-row lock.
        scoped = self._receipt_scope(company_id)
        initial = scoped._receipt_order(scoped, order_id)
        if initial.state not in ('sent', 'received', 'purchased'):
            raise ProtocolError('receipt_unavailable', 'This request cannot be received.', 409)
        scoped.env.cr.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
                              ('bchat-receipt:%s' % token,))
        if not scoped.env.cr.fetchone()[0]:
            raise ProtocolError('retry', 'This receipt is being processed; retry with the same UUID.', 409)
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        with scoped.env.cr.savepoint():
            scoped.env.cr.execute(
                'SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [order_id],
            )
            order = Order.browse(order_id).exists()
            order.invalidate_recordset()
            if (not order or order.company_id.id != company_id
                    or order.source_channel != 'bchat'):
                raise ProtocolError('not_found', 'This receipt request is unavailable.', 404)
            if order.state == 'purchased':
                if order.receipt_client_token == token and order.receipt_payload_hash == digest:
                    return scoped._receipt_success(order, token, replayed=True)
                raise ProtocolError('receipt_closed', 'This request was already received.', 409)
            if order.state not in ('sent', 'received') or order.receipt_client_token:
                raise ProtocolError('receipt_unavailable', 'This request cannot be received.', 409)
            lines = order.line_ids.sorted('id')
            if len(lines) != len(normalized) or set(lines.ids) != seen:
                raise ProtocolError('receipt_changed', 'Receipt lines changed; refresh the request.', 409)
            # Actual quantities may differ from the request in either direction.
            # The unchanged requested/manager quantities remain the audit baseline;
            # the native model only permits an overage through this guarded BChat
            # channel, never through ordinary Odoo manager/cashier actions.
            existing_token = Order.search([('receipt_client_token', '=', token)], limit=1)
            if existing_token:
                raise ProtocolError('idempotency_conflict', 'This receipt token was already used.', 409)
            internal = Order.with_context({
                'allowed_company_ids': [company_id], BCHAT_RECEIPT_INTERNAL: True,
            })
            try:
                internal.confirm_actual_from_catalog(order.id, normalized)
            except (UserError, ValidationError, AccessError) as error:
                _logger.warning(
                    'BChat receipt rejected by Odoo: order_id=%s company_id=%s cause=%s',
                    order.id, company_id, type(error).__name__,
                )
                raise ProtocolError('receipt_invalid', 'The receipt was rejected by Odoo.', 409) from None
            completed = internal.browse(order.id)
            completed.invalidate_recordset()
            if completed.state != 'purchased' or completed.actual_confirmed_by_id.id != scoped.env.uid:
                raise ProtocolError('receipt_incomplete', 'Odoo did not complete the receipt.', 409)
            completed.write({
                'receipt_client_token': token, 'receipt_payload_hash': digest,
                'receipt_share_uuid': str(uuid4()),
            })
            return scoped._receipt_success(completed, token, replayed=False)

    @api.model
    def _receipt_result_text(self, order):
        """Use the committed receipt values, never a client-supplied summary."""
        currency = self._label(order.currency_id.symbol or order.currency_id.name, 16)
        lines = ['تم استلام طلب الشراء %s' % self._label(order.name, 80),
                 'الشركة: %s' % self._label(order.company_id.name),
                 'طريقة الشراء: %s' % self._label(order._purchase_route_label())]
        if order.representative_partner_id:
            lines.append('مندوب المشتريات: %s' % self._label(order.representative_partner_id.display_name))
        for number, line in enumerate(order.line_ids.sorted('id'), 1):
            option = line.option_id
            product = self._label(option.product_id.name)
            option_name = self._label(option.name)
            name = ('%s (%s)' % (product, option_name)
                    if option_name != '-' and option_name != product else product)
            unit = self._label(option.uom_id.display_name, 80)
            difference = Decimal(str(line.actual_qty)) - Decimal(str(line.requested_qty))
            lines.extend(['', '%s. %s' % (number, name),
                          'الكمية المطلوبة: %s %s' % (self._money(line.requested_qty), unit),
                          'الكمية الفعلية: %s %s' % (self._money(line.actual_qty), unit),
                          'فرق الكمية: %s %s' % (self._money(difference), unit),
                          'سعر الوحدة المطلوب: %s %s' % (self._money(line.requested_price), currency),
                          'سعر الوحدة الفعلي: %s %s' % (self._money(line.actual_price), currency),
                          'مجموع الصنف الفعلي: %s %s' % (self._money(_decimal_total(line.actual_qty, line.actual_price)), currency)])
        total_difference = Decimal(str(order.actual_total)) - Decimal(str(order.requested_total))
        lines.extend(['', 'الإجمالي المطلوب: %s %s' % (self._money(order.requested_total), currency),
                      'الإجمالي الفعلي: %s %s' % (self._money(order.actual_total), currency),
                      'فرق الإجمالي: %s %s' % (self._money(total_difference), currency)])
        message = '\n'.join(lines)
        if len(message.encode('utf-8')) > MAX_ROOM_MESSAGE_BYTES:
            raise ProtocolError('room_message_too_long', 'Receipt result exceeds the room limit.', 413)
        return message

    @api.model
    def _v2_receipt_share(self, order_id, payload):
        self._require_order_receiver()
        self._require_bchat_permission('chat_send')
        if type(payload) is not dict or set(payload) != {'api_version', 'company_id'}:
            raise ProtocolError('invalid_payload', 'Unexpected receipt sharing fields.')
        if type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported receipt API version.')
        company_id = positive_id(payload['company_id'], 'company_id')
        order_id = positive_id(order_id, 'order_id')
        scoped = self._receipt_scope(company_id)
        scoped._receipt_order(scoped, order_id)
        scoped.env.cr.execute(
            'SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
            ('bchat-receipt-share:%s' % order_id,),
        )
        if not scoped.env.cr.fetchone()[0]:
            raise ProtocolError('retry', 'Receipt sharing is in progress; retry.', 409)
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        with scoped.env.cr.savepoint():
            scoped.env.cr.execute(
                'SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [order_id],
            )
            order = Order.browse(order_id).exists()
            order.invalidate_recordset()
            if (not order or order.company_id.id != company_id
                    or order.source_channel != 'bchat'):
                raise ProtocolError('not_found', 'This receipt request is unavailable.', 404)
            if order.state != 'purchased':
                raise ProtocolError('receipt_unavailable', 'Receipt is not complete.', 409)
            room = order.bchat_room_id
            if not room or room.company_id.id != company_id:
                raise ProtocolError('room_unavailable', 'Original room is unavailable.', 409)
            try:
                member = scoped._v2_current_member(room)
            except AccessError:
                raise ProtocolError('room_unavailable', 'Original room membership is unavailable.', 409) from None
            linked = order.receipt_result_message_id
            if linked:
                if (linked.room_id.id != order.bchat_room_id.id
                        or linked.company_id.id != company_id):
                    raise ProtocolError('receipt_unavailable', 'Receipt message link is invalid.', 409)
                return {
                    'api_version': 2, 'order_id': order.id, 'room_id': linked.room_id.id,
                    'message_id': linked.id, 'shared': True, 'replayed': True,
                }
            token = order.receipt_share_uuid or str(uuid4())
            if not order.receipt_share_uuid:
                Order.with_context({
                    'allowed_company_ids': [company_id], BCHAT_RECEIPT_INTERNAL: True,
                }).browse(order.id).write({'receipt_share_uuid': token})
            message = scoped._receipt_result_text(order)
            try:
                ack = scoped._v2_send(room.id, {
                    'api_version': 2, 'membership_id': member.id,
                    'client_uuid': token, 'text': message,
                })
            except AccessError:
                raise ProtocolError('room_unavailable', 'Original room membership is unavailable.', 409) from None
            Order.with_context({
                'allowed_company_ids': [company_id], BCHAT_RECEIPT_INTERNAL: True,
            }).browse(order.id).write({'receipt_result_message_id': ack['message_id']})
            return {
                'api_version': 2, 'order_id': order.id, 'room_id': room.id,
                'message_id': ack['message_id'], 'shared': True, 'replayed': False,
            }

    @api.model
    def _receipt_success(self, order, token, replayed):
        return {
            'api_version': 2, 'client_uuid': token, 'replayed': replayed,
            'receipt': {
                'order_id': order.id, 'name': self._label(order.name, 80),
                'state': order.state, 'company_id': order.company_id.id,
                'actual_total': self._money(order.actual_total),
                'currency_symbol': self._label(order.currency_id.symbol or order.currency_id.name, 16),
                'picking_id': order.picking_id.id or None,
                'confirmed_at': self._stamp(order.actual_confirmed_at),
                'confirmed_by_id': order.actual_confirmed_by_id.id,
            },
        }
