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


class BChatProcurementService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _order_publish_change(self, order):
        """Hint eligible readers; never carry amounts or catalogue data on Bus."""
        if 'baseer_access_role' not in self.env['res.users']._fields:
            return
        operator_group = self.env.ref(
            'baseer_bchat_procurement.group_bchat_procurement_operator',
        )
        users = self.env['res.users'].sudo().search([
            ('active', '=', True), ('share', '=', False),
            ('company_ids', 'in', [order.company_id.id]),
            '|', ('group_ids', 'in', [operator_group.id]),
            ('baseer_access_role', '=', 'owner'),
        ], limit=101)
        recipients = [user.id for user in users if (
            user.baseer_access_role == 'owner'
            or (user.baseer_access_role in ('cashier', 'pos_cashier')
                and user.has_group('baseer_bchat_procurement.group_bchat_procurement_operator'))
        )]
        if len(recipients) > 100:
            raise ProtocolError('too_many_operators', 'BChat order event recipients need pagination.', 409)
        self._change_publish(recipients, 'order', order_id=order.id,
                             company_id=order.company_id.id)

    @api.model
    def _order_access(self):
        user = self._require_user()
        if 'baseer_access_role' not in user._fields:
            raise AccessError('Baseer access roles are required for BChat procurement.')
        if user.baseer_access_role == 'owner':
            return 'viewer'
        if (user.baseer_access_role in ('cashier', 'pos_cashier')
                and user.has_group('baseer_bchat_procurement.group_bchat_procurement_operator')):
            return 'operator'
        raise AccessError('BChat procurement access is not assigned to this user.')

    @api.model
    def _require_order_reader(self):
        self._order_access()
        return self.env.user

    @api.model
    def _require_order_operator(self):
        if self._order_access() != 'operator':
            raise AccessError('BChat procurement operator permission is required.')
        user = self.env.user
        return user

    @api.model
    def _order_scope(self, company_id):
        self._require_order_operator()
        return self._company_scope(positive_id(company_id, 'company_id'))

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
        access = self._order_access()
        scopes = self._order_read_scopes()
        if len(scopes) > 20:
            raise ProtocolError('too_many_companies', 'Company selection needs pagination.', 409)
        result = {'api_version': 2, 'access': access, 'companies': [
            {'id': company_id, 'name': self._label(scope.env.company.name)}
            for company_id, scope in scopes.items()
        ]}
        if company_id is None:
            return result
        self._require_order_operator()
        scoped = self._order_scope(company_id)
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
    def _v2_order_catalog(self, company_id, search_term=None, category_id=None, after_id=None):
        scoped = self._order_scope(company_id)
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
        scoped = self._order_scope(company_id)
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
        return {
            'id': order.id, 'name': self._label(order.name, 80),
            'company_id': order.company_id.id,
            'company_name': self._label(order.company_id.name),
            'requester_id': order.requester_id.id,
            'requester_name': self._label(order.requester_id.name),
            'state': order.state,
            'representative_id': order.representative_partner_id.id,
            'representative_name': self._label(order.representative_partner_id.display_name),
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
        lines = [f'طلب شراء {self._label(order.name, 80)}']
        for line in order.line_ids.sorted('id'):
            option = line.option_id
            product_name = self._label(option.product_id.name)
            option_name = self._label(option.name)
            item_name = (f'{product_name} ({option_name})'
                         if option_name != '-' and option_name != product_name else product_name)
            lines.append('%s — الكمية: %s %s' % (
                item_name,
                format(Decimal(str(line.requested_qty)), '.2f'),
                self._label(option.uom_id.display_name),
            ))
        lines.append('الإجمالي: %s %s' % (
            self._money(order.requested_total),
            self._label(order.currency_id.symbol or order.currency_id.name, 16),
        ))
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
    def _v2_orders_all(self, before_id=None):
        scopes = self._order_read_scopes()
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
    def _v2_order_detail(self, company_id, order_id, scope=None):
        """Read an authorized BChat order without mutating the current catalogue."""
        access = self._order_access()
        if scope is None and access != 'operator':
            raise AccessError('BChat procurement operator permission is required.')
        if scope not in (None, 'all'):
            raise ProtocolError('invalid_payload', 'Unknown order scope.')
        order_id = positive_id(order_id, 'order_id')
        try:
            scoped = self._company_scope(company_id) if scope == 'all' else self._order_scope(company_id)
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
            available = bool(option) and access == 'operator'
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
        self._require_order_operator()
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
        scoped = self._order_scope(company_id)
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
        self._require_order_operator()
        legacy_fields = {
                'api_version', 'company_id', 'warehouse_id',
                'representative_partner_id', 'client_uuid', 'lines'}
        if type(payload) is not dict or set(payload) not in (legacy_fields, legacy_fields | {'room_id'}):
            raise ProtocolError('invalid_payload', 'Unexpected order fields.')
        if type(payload['api_version']) is not int or payload['api_version'] != 2:
            raise ProtocolError('invalid_payload', 'Unsupported order API version.')
        company_id = positive_id(payload['company_id'], 'company_id')
        warehouse_id = positive_id(payload['warehouse_id'], 'warehouse_id')
        selected = payload['representative_partner_id']
        if selected is not None:
            selected = positive_id(selected, 'representative_partner_id')
        token = canonical_uuid(payload['client_uuid'])
        room_id = payload.get('room_id')
        if room_id is not None:
            room_id = positive_id(room_id, 'room_id')
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
        if 'room_id' in payload:
            intent['room_id'] = room_id
        digest = hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        scoped = self._order_scope(company_id)
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
            'representative_partner_id': representative.id, 'requester_id': user_id,
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
