"""A narrow BChat path into existing procurement requests, not ERP ACL grants."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from psycopg2 import IntegrityError

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, ConcurrencyError, ValidationError

from odoo.addons.baseer_bchat.contracts import ProtocolError, canonical_uuid, positive_id
from odoo.addons.baseer_procurement_requests.models.procurement import (
    REQUEST_CREATE_INTERNAL, _decimal_input, _decimal_total,
)


PAGE_SIZE = 24
MAX_CART_LINES = 100
MAX_OPTIONS = 100
MAX_RESPONSE_BYTES = 65536
MAX_ROOM_MESSAGE_BYTES = 16384
ROOM_PAGE_SIZE = 50
PURCHASE_ROUTES = ('representative', 'cash', 'bank_transfer')


class BChatProcurementService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        grants = self._order_permissions()
        result['permissions'].update({
            'order_view': grants['can_view'],
            'order_create': grants['can_create'],
            'order_receive': grants['can_receive'],
        })
        return result

    @api.model
    def _order_publish_change(self, order):
        """Hint eligible readers; never carry amounts or catalogue data on Bus."""
        domain = [
            ('active', '=', True), ('share', '=', False),
            ('company_ids', 'in', [order.company_id.id]),
            ('bchat_order_view', '=', True),
        ]
        last_id = 0
        while True:
            users = self.env['res.users'].sudo().search(
                domain + [('id', '>', last_id)], order='id', limit=100,
            )
            if not users:
                break
            self._change_publish(users.ids, 'order', order_id=order.id,
                                 company_id=order.company_id.id)
            last_id = users[-1].id

    @api.model
    def _order_permissions(self):
        """Read only this authenticated user's flags, before searching with sudo."""
        user = self._require_user()
        grants = user.sudo()
        view = bool(grants.bchat_order_view and not grants.share)
        eligible = ('baseer_access_role' in user._fields
                    and user.baseer_access_role in ('owner', 'cashier', 'pos_cashier'))
        return {
            'can_view': view,
            'can_create': bool(view and eligible and grants.bchat_order_create),
            'can_receive': bool(view and eligible and grants.bchat_order_receive),
        }

    @api.model
    def _order_access(self):
        grants = self._order_permissions()
        if not grants['can_view']:
            raise AccessError('BChat procurement access is not assigned to this user.')
        return 'operator' if grants['can_create'] and grants['can_receive'] else 'viewer'

    @api.model
    def _require_order_reader(self):
        if not self._order_permissions()['can_view']:
            raise AccessError('BChat order viewing permission is required.')
        return self.env.user

    @api.model
    def _require_order_creator(self):
        if not self._order_permissions()['can_create']:
            raise AccessError('BChat order creation permission is required.')
        return self.env.user

    @api.model
    def _require_order_receiver(self):
        if not self._order_permissions()['can_receive']:
            raise AccessError('BChat receipt confirmation permission is required.')
        return self.env.user

    @api.model
    def _require_order_operator(self):
        """Legacy helper: full operator means both independent write rights."""
        grants = self._order_permissions()
        if not grants['can_create'] or not grants['can_receive']:
            raise AccessError('Both BChat procurement write permissions are required.')
        return self.env.user

    @api.model
    def _order_scope(self, company_id):
        """Keep the established signature for installed service extensions."""
        self._require_order_reader()
        return self._company_scope(positive_id(company_id, 'company_id'))

    @api.model
    def _order_create_scope(self, company_id):
        self._require_order_creator()
        return self._order_scope(company_id)

    @api.model
    def _order_receive_scope(self, company_id):
        self._require_order_receiver()
        return self._order_scope(company_id)

    @api.model
    def _order_read_scopes(self):
        """Verify every readable operator company before a sudo order search."""
        user = self._require_order_reader()
        scopes = {}
        for company in user.company_ids.sorted('id'):
            try:
                scopes[company.id] = self._company_scope(company.id)
            except AccessError:
                continue
        if not scopes:
            raise AccessError('No readable BChat procurement company is available.')
        return scopes

    @staticmethod
    def _label(value, limit=160):
        cleaned = ''.join(char for char in (value or '')
                          if not unicodedata.category(char).startswith('C')).strip()
        return cleaned[:limit].encode('utf-8')[:512].decode('utf-8', 'ignore') or '-'

    @staticmethod
    def _stamp(value):
        return value.strftime('%Y-%m-%dT%H:%M:%SZ') if value else None

    @staticmethod
    def _money(value):
        return format(Decimal(str(value or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')

    @api.model
    def _representatives(self):
        company = self.env.company
        partners = self.env['res.partner'].sudo().with_company(company).search([
            ('active', '=', True), ('is_purchase_representative', '=', True),
            ('is_company', '=', False), ('parent_id', '=', False),
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='name, id', limit=MAX_OPTIONS + 1)
        if len(partners) > MAX_OPTIONS:
            raise ProtocolError('too_many_representatives', 'Representative selection needs a narrower company list.', 409)
        return partners

    @api.model
    def _v2_order_options(self, company_id=None):
        permissions = self._order_permissions()
        access = self._order_access()
        scopes = self._order_read_scopes()
        if len(scopes) > 20:
            raise ProtocolError('too_many_companies', 'Company selection needs pagination.', 409)
        result = {'api_version': 2, 'workflow_version': 1, 'access': access, **permissions, 'companies': [
            {'id': company_id, 'name': self._label(scope.env.company.name)}
            for company_id, scope in scopes.items()
        ]}
        if permissions['can_create']:
            selection = dict(self.env['baseer.procurement.request']._fields[
                'purchase_route']._description_selection(self.env))
            result['purchase_routes'] = [
                {'code': code, 'name': self._label(selection[code])}
                for code in PURCHASE_ROUTES
            ]
        if company_id is None:
            return result
        scoped = self._order_create_scope(company_id)
        company = scoped.env.company
        warehouses = scoped.env['stock.warehouse'].sudo().search([
            ('company_id', '=', company.id), ('active', '=', True),
        ], order='name, id', limit=51)
        if len(warehouses) > 50:
            raise ProtocolError('too_many_warehouses', 'Warehouse selection needs pagination.', 409)
        representatives = scoped._representatives()
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(company)
        category_rows = scoped.env['product.product'].sudo().with_company(company)._read_group(
            Order._catalog_product_domain(), groupby=['categ_id'], aggregates=['__count'], limit=101,
        )
        if len(category_rows) > 100:
            raise ProtocolError('too_many_categories', 'Category selection needs pagination.', 409)
        categories = sorted((row[0] for row in category_rows if row[0]),
                            key=lambda category: (category.display_name or '', category.id))
        default_warehouse = company.baseer_procurement_default_warehouse_id
        result.update({
            'warehouses': [{'id': row.id, 'name': self._label(row.name)} for row in warehouses],
            'representatives': [{'id': row.id, 'name': self._label(row.display_name)} for row in representatives],
            'categories': [{'id': row.id, 'name': self._label(row.display_name)} for row in categories],
            'default_warehouse_id': default_warehouse.id if default_warehouse in warehouses else (warehouses[:1].id or None),
        })
        return result

    @api.model
    def _v2_order_rooms(self, company_id, search_term=None, after_id=None, preferred_room_id=None):
        """Names for an explicit sharing choice; never chat history or previews."""
        self._require_order_creator()
        self._require_bchat_permission('chat_send')
        scoped = self._order_create_scope(company_id)
        if search_term is not None:
            try:
                valid_search = isinstance(search_term, str) and len(search_term.encode('utf-8')) <= 256
            except UnicodeEncodeError:
                valid_search = False
            if not valid_search:
                raise ProtocolError('invalid_payload', 'Search text is too long.')
        if after_id is not None:
            after_id = positive_id(after_id, 'after_id')
        if preferred_room_id is not None:
            preferred_room_id = positive_id(preferred_room_id, 'preferred_room_id')
        company_id = scoped.env.company.id
        domain = [('user_id', '=', scoped.env.uid), ('company_id', '=', company_id),
                  ('room_id.company_id', '=', company_id), ('active', '=', True)]
        page_domain = list(domain)
        if after_id:
            page_domain.append(('room_id', '>', after_id))
        if search_term and search_term.strip():
            page_domain.append(('room_id.name', 'ilike', search_term.strip()))
        Membership = scoped.env['baseer.bchat.membership'].sudo()
        memberships = Membership.search(page_domain, order='room_id.id asc, id asc', limit=ROOM_PAGE_SIZE + 1)
        preferred = Membership.search(domain + [('room_id', '=', preferred_room_id)], limit=1) if preferred_room_id else Membership.browse()
        for room_id in sorted(set((memberships | preferred).mapped('room_id').ids)):
            scoped.env['baseer.bchat.room']._lock_for_read(room_id)
        (memberships | preferred).invalidate_recordset(['active'])
        if any(not member.active for member in (memberships | preferred)):
            # A removed probe must not turn a full page into a false final page.
            # Never scan beyond the bounded 51 candidates; require an explicit reload.
            raise ProtocolError('retry', 'Room membership changed; reload the room choices.', 409)
        page = memberships[:ROOM_PAGE_SIZE]

        def room_data(member):
            return {'id': member.room_id.id, 'name': self._label(member.room_id.name, 256)}

        result = {
            'api_version': 2, 'company_id': company_id,
            'rooms': [room_data(member) for member in page],
            'next_after_id': page[-1].room_id.id if len(memberships) > ROOM_PAGE_SIZE else None,
            'preferred_room': room_data(preferred) if preferred else None,
        }
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('page_too_large', 'Room page exceeds 64 KiB.', 413)
        return result

    @api.model
    def _v2_order_catalog(self, company_id, search_term=None, category_id=None, after_id=None):
        scoped = self._order_create_scope(company_id)
        if search_term is not None and (not isinstance(search_term, str)
                                        or len(search_term.encode('utf-8')) > 256):
            raise ProtocolError('invalid_payload', 'Search text is too long.')
        if category_id is not None:
            category_id = positive_id(category_id, 'category_id')
        if after_id is not None:
            after_id = positive_id(after_id, 'after_id')
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        product_domain = Order._catalog_product_domain((search_term or '').strip(), category_id)
        if after_id is not None:
            product_domain.append(('id', '>', after_id))
        products = scoped.env['product.product'].sudo().with_company(scoped.env.company).search(
            product_domain, order='id', limit=PAGE_SIZE + 1,
        )
        batch = products[:PAGE_SIZE]
        # Match Odoo's catalogue: a valid product without a configured option
        # receives its default purchase-UoM option under the existing locks.
        Order._default_options_for_products(batch)
        options = scoped.env['baseer.procurement.purchase.option'].sudo().with_company(
            scoped.env.company,
        ).search([
            ('company_id', '=', scoped.env.company.id), ('active', '=', True),
            ('product_id', 'in', batch.ids),
        ], order='product_id, id', limit=PAGE_SIZE * (PAGE_SIZE + 1))
        by_product = {product.id: [] for product in batch}
        for option in options:
            by_product[option.product_id.id].append(option)
        page = []
        last_product_id = None
        for product in batch:
            choices = by_product[product.id]
            if len(choices) > PAGE_SIZE:
                raise ProtocolError('too_many_options', 'This material has too many purchase options.', 409)
            if page and len(page) + len(choices) > PAGE_SIZE:
                break
            page.extend(choices)
            last_product_id = product.id
        if batch and not page:
            raise ProtocolError('invalid_catalog', 'No purchase option is available for this material.', 409)
        items = []
        for option in page:
            product = option.product_id
            items.append({
                'id': option.id, 'product_id': product.id,
                'product_name': self._label(product.name),
                'option_name': self._label(option.name),
                'uom_name': self._label(option.uom_id.display_name),
                'packaging_note': self._label(option.packaging_note) if option.packaging_note else '',
                'category_id': option.category_id.id,
                'category_name': self._label(option.category_id.display_name),
                'last_price': self._money(option.last_price),
                'currency_symbol': self._label(scoped.env.company.currency_id.symbol or scoped.env.company.currency_id.name, 16),
                'image_url': ('/bchat/api/v2/orders/image/%s?company_id=%s' % (product.id, scoped.env.company.id))
                             if product.image_128 else '',
            })
        has_more = bool(last_product_id and (
            len(products) > PAGE_SIZE or any(product.id > last_product_id for product in batch)
        ))
        result = {'api_version': 2, 'items': items,
                  'next_after_id': last_product_id if has_more else None}
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('page_too_large', 'Catalogue page exceeds 64 KiB.', 413)
        return result

    @api.model
    def _v2_order_image(self, company_id, product_id):
        scoped = self._order_create_scope(company_id)
        product_id = positive_id(product_id, 'product_id')
        product = scoped.env['product.product'].sudo().search([
            ('id', '=', product_id), ('company_id', '=', scoped.env.company.id),
            ('active', '=', True), ('purchase_ok', '=', True), ('type', '=', 'consu'),
        ], limit=1)
        if not product or not product.image_128:
            raise ProtocolError('not_found', 'This product image is unavailable.', 404)
        return product.image_128

    @api.model
    def _order_data(self, order):
        representative = order.representative_partner_id
        return {
            'id': order.id, 'name': self._label(order.name, 80),
            'company_id': order.company_id.id,
            'company_name': self._label(order.company_id.name),
            'requester_id': order.requester_id.id,
            'requester_name': self._label(order.requester_id.name),
            'state': order.state,
            'purchase_route': order.purchase_route,
            'purchase_route_name': self._label(order._purchase_route_label()),
            'representative_id': representative.id or None,
            'representative_name': self._label(representative.display_name) if representative else '',
            'requested_total': self._money(order.requested_total),
            'currency_symbol': self._label(order.currency_id.symbol or order.currency_id.name, 16),
            'submitted_at': self._stamp(order.internal_submitted_at),
            'room_id': order.bchat_room_id.id or None,
        }

    @api.model
    def _order_rows_for_scopes(self, orders, scopes):
        """Serialize one bounded page in company batches, preserving global ID order."""
        by_id = {}
        for company_id in {order.company_id.id for order in orders}:
            company_orders = orders.filtered(
                lambda order: order.company_id.id == company_id,
            ).with_company(scopes[company_id].env.company)
            for order in company_orders:
                by_id[order.id] = scopes[company_id]._order_data(order)
        return [by_id[order.id] for order in orders]

    @api.model
    def _order_room_text(self, order):
        currency = self._label(order.currency_id.symbol or order.currency_id.name, 16)
        lines = [f'طلب شراء {self._label(order.name, 80)}',
                 'الشركة: %s' % self._label(order.company_id.name),
                 'طريقة الشراء: %s' % self._label(order._purchase_route_label())]
        if order.representative_partner_id:
            lines.append('مندوب المشتريات: %s' % self._label(order.representative_partner_id.display_name))
        for number, line in enumerate(order.line_ids.sorted('id'), 1):
            option = line.option_id
            product_name = self._label(option.product_id.name)
            option_name = self._label(option.name)
            item_name = (f'{product_name} ({option_name})'
                         if option_name != '-' and option_name != product_name else product_name)
            lines.extend(['', '%s. %s' % (number, item_name),
                          'الكمية: %s %s' % (self._money(line.requested_qty), self._label(option.uom_id.display_name)),
                          'سعر الوحدة: %s %s' % (self._money(line.requested_price), currency),
                          'مجموع الصنف: %s %s' % (self._money(_decimal_total(line.requested_qty, line.requested_price)), currency)])
        lines.extend(['', 'الإجمالي: %s %s' % (self._money(order.requested_total), currency)])
        message = '\n'.join(lines)
        if len(message.encode('utf-8')) > MAX_ROOM_MESSAGE_BYTES:
            raise ProtocolError('room_message_too_long', 'The order message exceeds the room limit.', 413)
        return message

    @api.model
    def _v2_orders(self, company_id, before_id=None):
        scoped = self._order_scope(company_id)
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        domain = [('company_id', '=', scoped.env.company.id),
                  ('requester_id', '=', scoped.env.uid), ('source_channel', '=', 'bchat')]
        if before_id:
            domain.append(('id', '<', before_id))
        orders = scoped.env['baseer.procurement.request'].sudo().search(
            domain, order='id desc', limit=31,
        )
        page = orders[:30]
        return {'api_version': 2, 'orders': [scoped._order_data(order) for order in page],
                'next_before_id': page[-1].id if len(orders) > 30 else None}

    @api.model
    def _v2_orders_all(self, before_id=None, company_id=None):
        scopes = ({positive_id(company_id, 'company_id'): self._order_scope(company_id)}
                  if company_id is not None else self._order_read_scopes())
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        domain = [('company_id', 'in', list(scopes)), ('source_channel', '=', 'bchat')]
        if before_id:
            domain.append(('id', '<', before_id))
        scoped = self.with_context({
            'allowed_company_ids': list(scopes),
            'lang': self.env.lang,
            'tz': self.env.user.tz or 'UTC',
        })
        orders = scoped.env['baseer.procurement.request'].sudo().search(
            domain, order='id desc', limit=31,
        )
        page = orders[:30]
        response = {
            'api_version': 2,
            'orders': self._order_rows_for_scopes(page, scopes),
            'next_before_id': page[-1].id if len(orders) > 30 else None,
        }
        if len(json.dumps(response, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('page_too_large', 'Order page exceeds 64 KiB.', 413)
        return response

    @api.model
    def _v2_order_share(self, order_id, payload):
        """Attach one original room after creation, atomically with its message."""
        self._require_order_creator()
        self._require_bchat_permission('chat_send')
        if (type(payload) is not dict or set(payload) != {'api_version', 'company_id', 'room_id'}
                or type(payload['api_version']) is not int or payload['api_version'] != 2):
            raise ProtocolError('invalid_payload', 'Unexpected order sharing fields.')
        company_id = positive_id(payload['company_id'], 'company_id')
        room_id = positive_id(payload['room_id'], 'room_id')
        order_id = positive_id(order_id, 'order_id')
        scoped = self._order_create_scope(company_id)
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        domain = [('id', '=', order_id), ('company_id', '=', company_id),
                  ('requester_id', '=', scoped.env.uid), ('source_channel', '=', 'bchat')]
        if not Order.search(domain, limit=1):
            raise ProtocolError('not_found', 'This order is unavailable.', 404)
        scoped.env.cr.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
                              ('bchat-order-share:%s' % order_id,))
        if not scoped.env.cr.fetchone()[0]:
            raise ProtocolError('retry', 'Order sharing is in progress; retry.', 409)
        with scoped.env.cr.savepoint():
            scoped.env.cr.execute('SELECT id FROM baseer_procurement_request WHERE id = %s FOR UPDATE', [order_id])
            order = Order.browse(order_id).exists()
            order.invalidate_recordset()
            if (not order or order.company_id.id != company_id or order.requester_id.id != scoped.env.uid
                    or order.source_channel != 'bchat'):
                raise ProtocolError('not_found', 'This order is unavailable.', 404)
            linked_room = order.bchat_room_id
            linked_message = order.bchat_message_id
            if bool(linked_room) != bool(linked_message):
                raise ProtocolError('order_share_incomplete', 'The order sharing link needs review.', 409)
            if linked_room and linked_room.id != room_id:
                raise ProtocolError('order_share_conflict', 'The order already has an original room.', 409)
            if linked_message and (linked_room.company_id.id != company_id
                                   or linked_message.company_id.id != company_id
                                   or linked_message.room_id.id != room_id
                                   or linked_message.author_user_id.id != order.requester_id.id
                                   or linked_message.membership_id.room_id.id != room_id
                                   or linked_message.membership_id.company_id.id != company_id
                                   or linked_message.membership_id.user_id.id != order.requester_id.id):
                raise ProtocolError('order_share_incomplete', 'The order sharing link needs review.', 409)
            if not linked_message and order.state not in ('sent', 'received', 'purchased'):
                raise ProtocolError('order_share_unavailable', 'This order cannot be shared.', 409)
            # Bound the complete body before any message or order-link mutation.
            text = scoped._order_room_text(order) if not linked_message else None
            try:
                candidate = scoped.env['baseer.bchat.room'].sudo().search([
                    ('id', '=', room_id), ('company_id', '=', company_id),
                ], limit=1)
                if not candidate:
                    raise AccessError('The room is unavailable in this company.')
                scoped._v2_current_member(candidate)
                room = scoped._v2_lock_room(room_id, mutate=not bool(linked_message))
                if room.company_id.id != company_id:
                    raise AccessError('The room belongs to another company.')
                member = scoped._v2_current_member(room)
            except AccessError:
                raise ProtocolError('room_unavailable', 'Choose a room with current membership in this company.', 409) from None
            if linked_message:
                return {'api_version': 2, 'order_id': order.id, 'room_id': room.id,
                        'message_id': linked_message.id, 'shared': True, 'replayed': True}
            try:
                sent = scoped._v2_send(room.id, {
                    'api_version': 2, 'membership_id': member.id,
                    'client_uuid': str(uuid4()), 'text': text,
                })
            except AccessError:
                raise ProtocolError('room_unavailable', 'Choose a room with current membership in this company.', 409) from None
            order.with_context(**{REQUEST_CREATE_INTERNAL: True}).write({
                'bchat_room_id': room.id, 'bchat_message_id': sent['message_id'],
            })
            return {'api_version': 2, 'order_id': order.id, 'room_id': room.id,
                    'message_id': sent['message_id'], 'shared': True, 'replayed': False}

    @api.model
    def _v2_order_detail(self, company_id, order_id, scope=None):
        """Read an authorized BChat order without mutating the current catalogue."""
        permissions = self._order_permissions()
        self._require_order_reader()
        if scope not in (None, 'all'):
            raise ProtocolError('invalid_payload', 'Unknown order scope.')
        order_id = positive_id(order_id, 'order_id')
        try:
            scoped = self._order_scope(company_id)
        except AccessError:
            raise ProtocolError('not_found', 'The order is unavailable.', 404) from None
        company = scoped.env.company
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(company)
        domain = [('id', '=', order_id), ('company_id', '=', company.id),
                  ('source_channel', '=', 'bchat')]
        if scope is None:
            domain.append(('requester_id', '=', scoped.env.uid))
        order = Order.search(domain, limit=1)
        if not order:
            raise ProtocolError('not_found', 'The order is unavailable.', 404)
        rows = scoped.env['baseer.procurement.request.line'].sudo().with_company(company).search([
            ('request_id', '=', order.id),
        ], order='id', limit=MAX_CART_LINES + 1)
        if len(rows) > MAX_CART_LINES:
            raise ProtocolError('order_too_large', 'The order exceeds 100 lines.', 413)
        lines = []
        for row in rows:
            option = row.option_id
            available = bool(option) and permissions['can_create']
            if available:
                try:
                    Order._assert_catalog_options(option)
                except (AccessError, ValidationError):
                    available = False
            current = None
            if available:
                product = option.product_id
                current = {
                    'id': option.id, 'product_id': product.id,
                    'product_name': self._label(product.name),
                    'option_name': self._label(option.name),
                    'uom_name': self._label(option.uom_id.display_name),
                    'packaging_note': self._label(option.packaging_note) if option.packaging_note else '',
                    'category_id': option.category_id.id,
                    'category_name': self._label(option.category_id.display_name),
                    'last_price': self._money(option.last_price),
                    'currency_symbol': self._label(company.currency_id.symbol or company.currency_id.name, 16),
                    'image_url': ('/bchat/api/v2/orders/image/%s?company_id=%s' % (product.id, company.id))
                                 if product.image_128 else '',
                }
            lines.append({
                'line_id': row.id, 'option_id': option.id,
                'product_name': self._label(option.product_id.name) if option else '-',
                'option_name': self._label(option.name) if option else '-',
                'requested_qty': self._money(row.requested_qty),
                'available': available, 'current_option': current,
            })
        summary = scoped._order_data(order)
        summary.update({'company_id': company.id, 'warehouse_id': order.warehouse_id.id})
        result = {'api_version': 2, 'order': summary, 'lines': lines}
        if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_RESPONSE_BYTES:
            raise ProtocolError('order_too_large', 'Order details exceed 64 KiB.', 413)
        return result

    @api.model
    def _v2_order_quote(self, payload):
        """Read-only estimate of the current catalogue cost, never an order reservation."""
        self._require_order_creator()
        if type(payload) is not dict or set(payload) != {
                'api_version', 'company_id', 'warehouse_id', 'cart_revision', 'lines'}:
            raise ProtocolError('invalid_payload', 'Unexpected quote fields.')
        if type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported order API version.')
        company_id = positive_id(payload['company_id'], 'company_id')
        warehouse_id = positive_id(payload['warehouse_id'], 'warehouse_id')
        revision = positive_id(payload['cart_revision'], 'cart_revision')
        lines = payload['lines']
        if type(lines) is not list or not 1 <= len(lines) <= MAX_CART_LINES:
            raise ProtocolError('invalid_payload', 'Add 1–100 order lines.')
        normalized = []
        seen = set()
        for row in lines:
            if type(row) is not dict or set(row) != {'option_id', 'quantity'}:
                raise ProtocolError('invalid_payload', 'An order line is invalid.')
            option_id = positive_id(row['option_id'], 'option_id')
            raw_qty = row['quantity']
            if (not isinstance(raw_qty, str) or len(raw_qty) > 9
                    or not re.fullmatch(r'(?:[1-9][0-9]{0,5}|0)(?:\.[0-9]{1,2})?', raw_qty)):
                raise ProtocolError('invalid_payload', 'Quantity is outside the supported six-digit range.')
            try:
                qty = _decimal_input(raw_qty, 'Quantity', positive=True)
            except ValidationError:
                raise ProtocolError('invalid_payload', 'Quantity must be positive.') from None
            if option_id in seen:
                raise ProtocolError('invalid_payload', 'An option appears twice in the cart.')
            seen.add(option_id)
            normalized.append((option_id, qty))
        scoped = self._order_create_scope(company_id)
        warehouse = scoped.env['stock.warehouse'].sudo().browse(warehouse_id).exists()
        if not warehouse or warehouse.company_id.id != company_id or not warehouse.active:
            raise ProtocolError('invalid_warehouse', 'Choose a warehouse in this company.', 403)
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        options = scoped.env['baseer.procurement.purchase.option'].sudo().with_company(
            scoped.env.company).browse([option_id for option_id, _ in normalized]).exists()
        if len(options) != len(normalized):
            raise ProtocolError('invalid_option', 'The cart has an unavailable option.', 409)
        try:
            Order._assert_catalog_options(options)
        except (AccessError, ValidationError):
            raise ProtocolError('invalid_option', 'The cart has an unavailable option.', 409) from None
        by_id = {option.id: option for option in options}
        if len({by_id[option_id].product_id.id for option_id, _ in normalized}) != len(normalized):
            raise ProtocolError('invalid_option', 'A material appears twice in the cart.', 409)
        response_lines = []
        total = Decimal('0.00')
        for option_id, quantity in normalized:
            option = by_id[option_id]
            if option.last_price is None or type(option.last_price) is bool:
                raise ProtocolError('quote_unavailable', 'The current price is unavailable.', 503)
            try:
                unit_price = _decimal_input(option.last_price, 'Unit price')
            except ValidationError:
                raise ProtocolError('quote_unavailable', 'The current price is unavailable.', 503) from None
            line_total = _decimal_total(quantity, unit_price)
            total += line_total
            response_lines.append({
                'option_id': option_id, 'quantity': format(quantity, '.2f'),
                'unit_price': format(unit_price, '.2f'), 'line_total': format(line_total, '.2f'),
            })
        currency = scoped.env.company.currency_id
        return {
            'api_version': 2, 'company_id': company_id, 'cart_revision': revision,
            'lines': response_lines, 'estimated_total': format(total, '.2f'),
            'currency_code': currency.name,
            'currency_symbol': self._label(currency.symbol or currency.name, 16),
            'quoted_at': self._stamp(fields.Datetime.now()),
        }

    @api.model
    def _v2_order_create(self, payload):
        self._require_order_creator()
        legacy_fields = {
                'api_version', 'company_id', 'warehouse_id',
                'representative_partner_id', 'client_uuid', 'lines'}
        optional_fields = {'room_id', 'purchase_route'}
        if (type(payload) is not dict or not legacy_fields <= set(payload)
                or set(payload) - legacy_fields - optional_fields):
            raise ProtocolError('invalid_payload', 'Unexpected order fields.')
        if type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported order API version.')
        company_id = positive_id(payload['company_id'], 'company_id')
        warehouse_id = positive_id(payload['warehouse_id'], 'warehouse_id')
        purchase_route = payload.get('purchase_route', 'representative')
        if type(purchase_route) is not str or purchase_route not in PURCHASE_ROUTES:
            raise ProtocolError('invalid_purchase_route', 'Choose a valid purchase route.')
        selected = payload['representative_partner_id']
        if purchase_route != 'representative' and selected is not None:
            raise ProtocolError('invalid_representative', 'This purchase route cannot have a representative.')
        if selected is not None:
            selected = positive_id(selected, 'representative_partner_id')
        token = canonical_uuid(payload['client_uuid'])
        room_id = payload.get('room_id')
        if room_id is not None:
            room_id = positive_id(room_id, 'room_id')
            self._require_bchat_permission('chat_send')
        lines = payload['lines']
        if type(lines) is not list or not 1 <= len(lines) <= MAX_CART_LINES:
            raise ProtocolError('invalid_payload', 'Add 1–100 order lines.')
        normalized = []
        seen = set()
        for row in lines:
            if type(row) is not dict or set(row) != {'option_id', 'quantity'}:
                raise ProtocolError('invalid_payload', 'An order line is invalid.')
            option_id = positive_id(row['option_id'], 'option_id')
            raw_qty = row['quantity']
            if (not isinstance(raw_qty, str) or len(raw_qty) > 9
                    or not re.fullmatch(r'(?:[1-9][0-9]{0,5}|0)(?:\.[0-9]{1,2})?', raw_qty)):
                raise ProtocolError('invalid_payload', 'Quantity is outside the supported six-digit range.')
            try:
                qty = _decimal_input(raw_qty, 'Quantity', positive=True)
            except ValidationError:
                raise ProtocolError('invalid_payload', 'Quantity must be positive.') from None
            if option_id in seen:
                raise ProtocolError('invalid_payload', 'An option appears twice in the cart.')
            seen.add(option_id)
            normalized.append({'option_id': option_id, 'quantity': format(qty, '.2f')})
        normalized.sort(key=lambda row: row['option_id'])
        intent = {'company_id': company_id, 'warehouse_id': warehouse_id,
                  'representative_partner_id': selected, 'lines': normalized}
        # Explicit representative matches old v48 fingerprints byte for byte.
        if purchase_route != 'representative':
            intent['purchase_route'] = purchase_route
        if 'room_id' in payload:
            intent['room_id'] = room_id
        digest = hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        scoped = self._order_create_scope(company_id)
        user_id = scoped.env.uid
        scoped.env.cr.execute('SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))',
                              ('bchat-order:%s:%s:%s' % (company_id, user_id, token),))
        if not scoped.env.cr.fetchone()[0]:
            raise ConcurrencyError('Concurrent BChat order submission; retry the transaction.')
        Order = scoped.env['baseer.procurement.request'].sudo().with_company(scoped.env.company)
        existing = Order.search([('company_id', '=', company_id), ('requester_id', '=', user_id),
                                 ('client_token', '=', token)], limit=1)
        if existing:
            if existing.source_channel != 'bchat' or existing.client_payload_hash != digest:
                raise ProtocolError('idempotency_conflict', 'This order token was already used differently.', 409)
            return {'api_version': 2, 'order': scoped._order_data(existing),
                    'client_uuid': token, 'replayed': True}
        warehouse = scoped.env['stock.warehouse'].sudo().browse(warehouse_id).exists()
        if not warehouse or warehouse.company_id.id != company_id or not warehouse.active:
            raise ProtocolError('invalid_warehouse', 'Choose a warehouse in this company.', 400)
        representative = False
        if purchase_route == 'representative':
            representatives = scoped._representatives()
            if not representatives:
                raise ProtocolError('no_representative', 'No purchase representative is available in this company.', 409)
            if len(representatives) == 1:
                representative = representatives[0]
                if selected is not None and selected != representative.id:
                    raise ProtocolError('invalid_representative', 'The selected representative is unavailable.', 409)
            else:
                if selected is None:
                    raise ProtocolError('representative_required', 'Choose a purchase representative.', 409)
                representative = representatives.filtered(lambda row: row.id == selected)
                if not representative:
                    raise ProtocolError('invalid_representative', 'The selected representative is unavailable.', 409)
        options = scoped.env['baseer.procurement.purchase.option'].sudo().browse(
            [row['option_id'] for row in normalized]).exists()
        if len(options) != len(normalized):
            raise ProtocolError('invalid_option', 'The cart has an unavailable option.', 400)
        try:
            Order._assert_catalog_options(options)
        except (AccessError, ValidationError):
            raise ProtocolError('invalid_option', 'The cart has an unavailable option.', 400) from None
        by_id = {option.id: option for option in options}
        if len({by_id[row['option_id']].product_id.id for row in normalized}) != len(normalized):
            raise ProtocolError('invalid_option', 'A material appears twice in the cart.', 400)
        values = {
            'company_id': company_id, 'warehouse_id': warehouse_id,
            'purchase_route': purchase_route,
            'representative_partner_id': representative.id if representative else False,
            'requester_id': user_id,
            'state': 'sent', 'source_channel': 'bchat',
            'internal_submitted_at': fields.Datetime.now(),
            'client_token': token, 'client_payload_hash': digest,
            'line_ids': [Command.create({
                'option_id': row['option_id'], 'requested_qty': float(Decimal(row['quantity'])),
                'requested_price': by_id[row['option_id']].last_price,
            }) for row in normalized],
        }
        internal = Order.with_context(**{REQUEST_CREATE_INTERNAL: True})
        try:
            with scoped.env.cr.savepoint():
                member = None
                if room_id is not None:
                    try:
                        room = scoped._v2_lock_room(room_id, mutate=True)
                        if room.company_id.id != company_id:
                            raise AccessError('The room is outside the order company.')
                        member = scoped._v2_current_member(room)
                    except AccessError:
                        raise ProtocolError('room_unavailable', 'Choose an active room in this company.', 409) from None
                    values['bchat_room_id'] = room.id
                created = internal.create(values)
                if member:
                    try:
                        sent = scoped._v2_send(room_id, {
                            'api_version': 2, 'membership_id': member.id,
                            'client_uuid': str(uuid4()), 'text': scoped._order_room_text(created),
                        })
                    except AccessError:
                        raise ProtocolError('room_unavailable', 'Choose an active room in this company.', 409) from None
                    internal.browse(created.id).write({'bchat_message_id': sent['message_id']})
                internal.flush_model(['client_token', 'client_payload_hash'])
                scoped._order_publish_change(created)
                return {'api_version': 2, 'order': scoped._order_data(created),
                        'client_uuid': token, 'replayed': False}
        except IntegrityError as error:
            if getattr(error, 'pgcode', None) != '23505':
                raise
            raise ConcurrencyError('Concurrent BChat order submission; retry the transaction.') from None
