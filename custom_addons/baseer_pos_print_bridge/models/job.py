import base64
import binascii
import hashlib
import io
import json
import logging
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from psycopg2 import IntegrityError
from PIL import Image, UnidentifiedImageError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .common import constant_time_equal, new_secret

RETRYABLE_ERRORS = {'spooler_unavailable', 'printer_offline', 'transport_error'}
BACKOFF_SECONDS = (15, 60, 300)
_logger = logging.getLogger(__name__)
NATIVE_RECEIPT_MAX_BYTES = 256 * 1024
NATIVE_RECEIPT_MAX_PIXELS = 5_000_000


class BaseerPrintJob(models.Model):
    _name = 'baseer.print.job'
    _description = 'Baseer Print Job'
    _order = 'create_date desc, id desc'
    _check_company_auto = False

    name = fields.Char(required=True, readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    pos_config_id = fields.Many2one('pos.config', ondelete='set null', index=True)
    agent_id = fields.Many2one('baseer.print.agent', required=True, ondelete='restrict', index=True)
    printer_id = fields.Many2one('baseer.print.printer', required=True, ondelete='restrict', index=True)
    route_id = fields.Many2one('baseer.print.route', ondelete='set null')
    source_order_id = fields.Many2one('pos.order', ondelete='set null', index=True)
    source_session_id = fields.Many2one('pos.session', ondelete='set null', index=True, readonly=True)
    cancellation_id = fields.Many2one('baseer.print.cancellation', ondelete='restrict', readonly=True, index=True)
    preparation_event_id = fields.Many2one(
        'baseer.print.preparation.event', ondelete='restrict', readonly=True, index=True,
    )
    preparation_event_ids = fields.Many2many(
        'baseer.print.preparation.event', 'baseer_print_job_preparation_event_rel',
        'job_id', 'event_id', readonly=True,
    )
    ticket_type = fields.Selection([
        ('receipt', 'Receipt'), ('preparation', 'Preparation'),
        ('session_close', 'Session closing report'), ('test', 'Test'),
    ],
                                   required=True, index=True)
    payload = fields.Json(required=True, readonly=True)
    receipt_image = fields.Binary(attachment=True, readonly=True, groups='base.group_system')
    receipt_image_sha256 = fields.Char(readonly=True, index=True)
    receipt_image_purged_at = fields.Datetime(readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection([
        ('pending', 'Pending'), ('leased', 'Leased'), ('done', 'Accepted by Windows'),
        ('failed', 'Failed'), ('cancelled', 'Cancelled'),
    ], required=True, default='pending', index=True)
    available_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    lease_token = fields.Char(copy=False, readonly=True, groups='base.group_system')
    lease_expires_at = fields.Datetime(readonly=True, index=True)
    attempt_count = fields.Integer(readonly=True, default=0)
    max_attempts = fields.Integer(required=True, default=3, readonly=True)
    sent_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    queue_latency_seconds = fields.Float(
        string='Queue latency (seconds)', compute='_compute_latency', readonly=True,
    )
    agent_latency_seconds = fields.Float(
        string='Agent latency (seconds)', compute='_compute_latency', readonly=True,
    )
    acceptance_latency_seconds = fields.Float(
        string='Windows acceptance latency (seconds)', compute='_compute_latency', readonly=True,
    )
    error_code = fields.Char(readonly=True)
    error_detail = fields.Char(readonly=True)
    paper_confirmed_at = fields.Datetime(readonly=True)
    paper_confirmed_by = fields.Many2one('res.users', readonly=True, ondelete='set null')
    reprint_of_id = fields.Many2one('baseer.print.job', ondelete='restrict', readonly=True)
    reprint_sequence = fields.Integer(readonly=True, default=0)

    _idempotency_unique = models.Constraint('unique(idempotency_key)', 'This print job has already been created.')

    @api.depends('create_date', 'sent_at', 'completed_at')
    def _compute_latency(self):
        for job in self:
            job.queue_latency_seconds = max(
                0.0,
                (job.sent_at - job.create_date).total_seconds(),
            ) if job.sent_at and job.create_date else 0.0
            job.agent_latency_seconds = max(
                0.0,
                (job.completed_at - job.sent_at).total_seconds(),
            ) if job.completed_at and job.sent_at else 0.0
            job.acceptance_latency_seconds = max(
                0.0,
                (job.completed_at - job.create_date).total_seconds(),
            ) if job.completed_at and job.create_date else 0.0

    def init(self):
        self._cr.execute('CREATE INDEX IF NOT EXISTS baseer_print_job_company_state_created_idx '
                         'ON baseer_print_job (company_id, state, create_date DESC)')
        self._cr.execute('CREATE INDEX IF NOT EXISTS baseer_print_job_pos_created_idx '
                         'ON baseer_print_job (pos_config_id, create_date DESC)')
        self._cr.execute('CREATE INDEX IF NOT EXISTS baseer_print_job_session_created_idx '
                         'ON baseer_print_job (source_session_id, create_date DESC)')

    @api.constrains(
        'company_id', 'pos_config_id', 'agent_id', 'printer_id', 'route_id',
        'source_order_id', 'source_session_id', 'cancellation_id',
        'preparation_event_id', 'preparation_event_ids',
    )
    def _check_links(self):
        for record in self:
            if record.pos_config_id and record.pos_config_id.company_id != record.company_id:
                raise ValidationError(_('The print job and point of sale must belong to the same company.'))
            if record.source_order_id and record.source_order_id.company_id != record.company_id:
                raise ValidationError(_('The print job and source order must belong to the same company.'))
            if record.source_session_id and record.source_session_id.company_id != record.company_id:
                raise ValidationError(_('The print job and source session must belong to the same company.'))
            if (record.source_session_id and record.pos_config_id
                    and record.source_session_id.config_id != record.pos_config_id):
                raise ValidationError(_('The print job and source session must belong to the same point of sale.'))
            if record.cancellation_id and record.cancellation_id.company_id != record.company_id:
                raise ValidationError(_('The print job and kitchen cancellation must belong to the same company.'))
            if (record.preparation_event_id and record.preparation_event_id.company_id
                    and record.preparation_event_id.company_id != record.company_id):
                raise ValidationError(_('The print job and kitchen event must belong to the same company.'))
            if (record.preparation_event_id and record.source_order_id
                    and record.preparation_event_id.order_id != record.source_order_id):
                raise ValidationError(_('The print job and kitchen event must belong to the same order.'))
            if any(event.company_id != record.company_id for event in record.preparation_event_ids):
                raise ValidationError(_('Every kitchen event must belong to the print-job company.'))
            if (record.source_order_id
                    and any(event.order_id != record.source_order_id for event in record.preparation_event_ids)):
                raise ValidationError(_('Every kitchen event must belong to the print-job order.'))
            if record.route_id and record.route_id.company_id != record.company_id:
                raise ValidationError(_('The print job and preparation binding must belong to the same company.'))
            if record.printer_id.agent_id != record.agent_id:
                raise ValidationError(_('The selected printer does not belong to the selected agent.'))
            if not record.printer_id._allows_company(record.company_id):
                raise ValidationError(_('This printer is not authorized for the print-job company.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].sudo().next_by_code('baseer.print.job') or _('Print job')
        return super().create(vals_list)

    @api.model
    def _canonical_key(self, *parts):
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()

    @api.model
    def _agent_supports_native_receipts(self, agent):
        try:
            version = tuple(int(part) for part in (agent.agent_version or '').split('.')[:3])
        except ValueError:
            return False
        return version >= (1, 4, 0)

    @api.model
    def _create_once(self, vals):
        existing = self.sudo().search([('idempotency_key', '=', vals['idempotency_key'])], limit=1)
        if existing:
            return existing
        try:
            with self.env.cr.savepoint():
                creator = self.sudo()
                if vals.get('receipt_image'):
                    # ir.attachment normally resizes JPEGs taller than 1920px.
                    # This is a validated, immutable thermal snapshot: resizing
                    # would change both printed detail and the signed job hash.
                    # Scope the native opt-out to this image, never global ICP.
                    creator = creator.with_context(image_no_postprocess=True)
                return creator.create(vals)
        except IntegrityError:
            return self.sudo().search([('idempotency_key', '=', vals['idempotency_key'])], limit=1)

    @api.model
    def _job_payload(self, ticket_type, order, printer, lines=None, copies=1, cancellation=False):
        order_payload = {
            'id': order.id if order else False,
            'reference': order.pos_reference or order.name if order else _('Printer test'),
            'created_at': fields.Datetime.to_string(fields.Datetime.now()),
        }
        if order:
            cashier = (
                order.employee_id
                if 'employee_id' in order._fields and order.employee_id
                else order.user_id
            )
            if cashier:
                order_payload['requested_by'] = cashier.display_name
        if order and 'table_id' in order._fields and order.table_id:
            order_payload['table'] = order.table_id.display_name
        payload = {'schema': 2, 'ticket_type': ticket_type,
                   'printer': {'machine_identifier': printer.machine_identifier, 'paper_width': printer.paper_width,
                               'copies': copies}, 'order': order_payload, 'lines': lines or []}
        if cancellation:
            payload['cancellation'] = {
                'id': cancellation.id,
                'reason_code': cancellation.reason_code,
                'reason_label': cancellation._reason_label(cancellation.reason_code),
                'reason_note': cancellation.reason_note or '',
                'requested_by': cancellation.requested_by.display_name,
            }
        return payload

    @api.model
    def _enqueue_receipt(self, order):
        config = order.config_id
        if not config.baseer_direct_print_enabled or order.state != 'paid' or order.is_refund:
            return self.browse()
        printer = config.baseer_receipt_printer_id
        if not printer or not printer.active or not printer._allows_company(order.company_id):
            return self.browse()
        # A receipt is an immutable snapshot of the paid POS order, not a kitchen change.
        # Monetary strings are prepared by Odoo in the POS currency; the agent never totals them.
        paid_order = order.sudo().with_company(order.company_id)
        currency = paid_order.currency_id
        digits = currency.decimal_places

        def money(amount):
            return f'{currency.round(amount):.{digits}f}'

        lines = [{
            'name': line.full_product_name or line.product_id.display_name,
            'quantity': line.qty,
            'unit_price': money(line.price_unit),
            'discount': line.discount,
            'price': money(line.price_subtotal_incl),
        } for line in paid_order.lines]
        line_subtotal = sum(paid_order.lines.mapped('price_subtotal'))
        adjustment = currency.round(paid_order.amount_total - paid_order.amount_tax - line_subtotal)
        payload = self._job_payload('receipt', paid_order, printer, lines, config.baseer_receipt_copies)
        payload['schema'] = 3
        payload['order']['created_at'] = fields.Datetime.to_string(paid_order.date_order)
        payload['receipt'] = {
            'company': paid_order.company_id.name,
            'company_vat': paid_order.company_id.vat or '',
            'point_of_sale': config.name,
            'currency': currency.symbol or currency.name,
            'subtotal': money(line_subtotal),
            'tax': money(paid_order.amount_tax),
            'adjustment': money(adjustment),
            'has_adjustment': bool(adjustment),
            'total': money(paid_order.amount_total),
            'paid': money(sum(paid_order.payment_ids.filtered(lambda payment: not payment.is_change).mapped('amount'))),
            'change': money(paid_order.amount_return),
            'payments': [{
                'method': payment.payment_method_id.display_name,
                'amount': money(payment.amount),
            } for payment in paid_order.payment_ids if not payment.is_change],
        }
        return self._create_once({'company_id': order.company_id.id, 'pos_config_id': config.id,
                                  'agent_id': printer.agent_id.id, 'printer_id': printer.id,
                                  'source_order_id': order.id, 'ticket_type': 'receipt',
                                  'payload': payload,
                                  'idempotency_key': self._canonical_key('receipt', order.uuid)})

    @api.model
    def _validated_native_receipt_image(self, jpeg_base64):
        if not isinstance(jpeg_base64, str) or len(jpeg_base64) > ((NATIVE_RECEIPT_MAX_BYTES + 2) // 3) * 4:
            raise ValidationError(_('The customer receipt image is missing or too large.'))
        try:
            raw = base64.b64decode(jpeg_base64, validate=True)
            if len(raw) > NATIVE_RECEIPT_MAX_BYTES or not raw.startswith(b'\xff\xd8'):
                raise ValueError('invalid JPEG length or marker')
            with Image.open(io.BytesIO(raw)) as picture:
                width, height = picture.size
                if (picture.format != 'JPEG' or not 200 <= width <= 1000
                        or not 1 <= height <= 12000
                        or width * height > NATIVE_RECEIPT_MAX_PIXELS
                        or picture.getexif()):
                    raise ValueError('invalid receipt dimensions or metadata')
                picture.verify()
        except (ValueError, binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError(_('The customer receipt image is invalid.')) from None
        return raw, width, height, hashlib.sha256(raw).hexdigest()

    @api.model
    def _enqueue_native_receipt(self, order, jpeg_base64):
        order.ensure_one()
        config = order.config_id
        if (not config.baseer_direct_print_enabled or not config.baseer_native_receipt_enabled
                or order.state not in ('paid', 'done')
                or order.company_id not in self.env.companies
                or order.session_id.config_id != config):
            raise ValidationError(_('This order is not ready for an original Odoo customer receipt.'))
        printer = config.baseer_receipt_printer_id
        if (not printer or not printer.active or printer.paper_width != '80'
                or not printer._allows_company(order.company_id)):
            raise ValidationError(_('The 80 mm receipt printer is not available for this company.'))
        config._baseer_assert_native_receipt_company_ready()
        if order.company_id.country_id.code == 'SA':
            if not order.date_order:
                raise ValidationError(_('The customer receipt order date is missing.'))
            phase_two = self.env['ir.module.module'].sudo().search_count([
                ('name', '=', 'l10n_sa_edi_pos'), ('state', '=', 'installed'),
            ])
            if phase_two:
                move = order.account_move
                if (not move or move.company_id != order.company_id or move.state != 'posted'
                        or not move.l10n_sa_qr_code_str or move.edi_state != 'sent'):
                    raise ValidationError(_(
                        'The Saudi electronic invoice is not complete; the receipt cannot be printed yet.'
                    ))
        raw, width, height, digest = self._validated_native_receipt_image(jpeg_base64)
        key = self._canonical_key('receipt-native-v1', order.uuid)
        existing = self.sudo().search([('idempotency_key', '=', key)], limit=1)
        if existing:
            if existing.state in ('failed', 'cancelled'):
                raise ValidationError(_(
                    'This receipt job failed or was cancelled. Ask a Point of Sale manager to reprint it from Print Jobs.'
                ))
            if existing.receipt_image_purged_at:
                if not self.env.user.has_group('point_of_sale.group_pos_manager'):
                    raise AccessError(_('Only a Point of Sale manager can recapture a purged receipt.'))
                self.env.cr.execute('SELECT id FROM baseer_print_job WHERE id = %s FOR UPDATE', [existing.id])
                previous = self.sudo().search([('reprint_of_id', '=', existing.id)],
                                              order='reprint_sequence desc', limit=1)
                sequence = previous.reprint_sequence + 1 if previous else 1
                payload = dict(existing.payload)
                payload['receipt_image'] = {
                    'sha256': digest, 'width': width, 'height': height, 'format': 'jpeg',
                }
                return self._create_once({
                    'company_id': existing.company_id.id, 'pos_config_id': existing.pos_config_id.id,
                    'agent_id': printer.agent_id.id, 'printer_id': printer.id,
                    'source_order_id': order.id, 'ticket_type': 'receipt',
                    'payload': payload, 'receipt_image': base64.b64encode(raw),
                    'receipt_image_sha256': digest,
                    'idempotency_key': self._canonical_key('receipt-native-recapture-v1', existing.id, sequence),
                    'reprint_of_id': existing.id, 'reprint_sequence': sequence,
                })
            if existing.receipt_image_sha256 != digest:
                raise ValidationError(_('The receipt image differs from the first recorded copy. Ask a manager to review it.'))
            if not order.nb_print:
                order.sudo().write({'nb_print': 1})
            return existing
        payload = self._job_payload('receipt', order, printer, [], config.baseer_receipt_copies)
        payload.update({
            'schema': 4,
            'receipt_image': {'sha256': digest, 'width': width, 'height': height, 'format': 'jpeg'},
            'source_invoice_id': order.account_move.id or False,
        })
        job = self._create_once({
            'company_id': order.company_id.id, 'pos_config_id': config.id,
            'agent_id': printer.agent_id.id, 'printer_id': printer.id,
            'source_order_id': order.id, 'ticket_type': 'receipt',
            'payload': payload, 'receipt_image': base64.b64encode(raw),
            'receipt_image_sha256': digest, 'idempotency_key': key,
        })
        if job.receipt_image_sha256 != digest:
            raise ValidationError(_('The receipt image differs from the first recorded copy. Ask a manager to review it.'))
        # Match Odoo's payment-edit lock as soon as the receipt is accepted for
        # printing. The job state, not nb_print, records whether paper emerged.
        if not order.nb_print:
            order.sudo().write({'nb_print': 1})
        return job

    @api.model
    def _enqueue_preparation(self, order, printer, binding, change, copies=None, event=False):
        copies = copies if copies is not None else binding.copies
        key = self._canonical_key(
            'preparation-event', event.id, printer.id, copies,
        ) if event else self._canonical_key(
            'preparation', {'order_uuid': order.uuid, 'printer': printer.id,
                            'binding': binding.id if binding else False, 'change': change},
        )
        if event:
            change = {
                **change,
                'event_id': event.id,
                'action_uuid': event.action_uuid,
                'action': event.action,
                'previous_quantity': event.previous_quantity,
                'delta_quantity': event.delta_quantity,
                'new_quantity': event.new_quantity,
                'quantity': event.new_quantity,
                'reason_code': event.reason_code or '',
                'reason_label': (
                    self.env['baseer.print.cancellation']._reason_label(event.reason_code)
                    if event.reason_code else ''
                ),
                'reason_note': event.reason_note or '',
                'requested_by': event.requested_by.display_name,
            }
        return self._create_once({'company_id': order.company_id.id, 'pos_config_id': order.config_id.id,
                                  'agent_id': printer.agent_id.id, 'printer_id': printer.id,
                                  'route_id': binding.id if binding else False, 'source_order_id': order.id,
                                  'preparation_event_id': event.id if event else False,
                                  'ticket_type': 'preparation',
                                  'payload': self._job_payload('preparation', order, printer, [change], copies),
                                  'idempotency_key': key})

    @api.model
    def _enqueue_preparation_batch(self, order, printer, binding, changes, copies, events):
        events = events.sorted('id')
        if not events or not changes or len(events) != len(changes):
            raise ValidationError(_('A kitchen print batch must contain matching events and lines.'))
        action_uuids = set(events.mapped('action_uuid'))
        if len(action_uuids) != 1:
            raise ValidationError(_('A kitchen print batch must belong to one action.'))
        lines = []
        for event, change in zip(events, changes):
            lines.append({
                **change,
                'event_id': event.id,
                'action_uuid': event.action_uuid,
                'action': event.action,
                'previous_quantity': event.previous_quantity,
                'delta_quantity': event.delta_quantity,
                'new_quantity': event.new_quantity,
                'quantity': event.new_quantity,
                'reason_code': event.reason_code or '',
                'reason_label': (
                    self.env['baseer.print.cancellation']._reason_label(event.reason_code)
                    if event.reason_code else ''
                ),
                'reason_note': event.reason_note or '',
                'requested_by': event.requested_by.display_name,
            })
        key = self._canonical_key(
            'preparation-action', events[0].action_uuid, printer.id, copies,
        )
        return self._create_once({
            'company_id': order.company_id.id,
            'pos_config_id': order.config_id.id,
            'agent_id': printer.agent_id.id,
            'printer_id': printer.id,
            'route_id': binding.id if binding else False,
            'source_order_id': order.id,
            'preparation_event_id': events[0].id,
            'preparation_event_ids': [(6, 0, events.ids)],
            'ticket_type': 'preparation',
            'payload': self._job_payload('preparation', order, printer, lines, copies),
            'idempotency_key': key,
        })

    @api.model
    def _enqueue_preparation_cancellation(self, order, cancellation, printer, states, copies):
        lines = []
        for state in states:
            details = dict(state.details)
            lines.append({**details, 'action': 'cancel', 'delta_quantity': -state.quantity,
                          'previous_quantity': state.quantity})
        key = self._canonical_key('preparation-cancellation', cancellation.id, printer.id, copies)
        route = states[:1].route_id
        return self._create_once({
            'company_id': order.company_id.id, 'pos_config_id': order.config_id.id,
            'agent_id': printer.agent_id.id, 'printer_id': printer.id,
            'route_id': route.id if route else False, 'source_order_id': order.id,
            'cancellation_id': cancellation.id, 'ticket_type': 'preparation',
            'payload': self._job_payload('preparation', order, printer, lines, copies, cancellation),
            'idempotency_key': key,
        })

    @api.model
    def _enqueue_test(self, printer, config):
        if not printer.active or not printer._allows_company(config.company_id):
            raise ValidationError(_('This printer is inactive or unauthorized for this point of sale.'))
        key = self._canonical_key('test', printer.id, config.id, fields.Datetime.now().isoformat(), new_secret(8))
        return self._create_once({'company_id': config.company_id.id, 'pos_config_id': config.id,
                                  'agent_id': printer.agent_id.id, 'printer_id': printer.id, 'ticket_type': 'test',
                                  'payload': self._job_payload('test', False, printer,
                                                               [{'name': _('Baseer printer test'), 'quantity': 1}]),
                                  'idempotency_key': key})

    @api.model
    def _format_session_amount(self, amount, currency):
        quantizer = Decimal(1).scaleb(-currency.decimal_places)
        return format(Decimal(amount or 0).quantize(quantizer, rounding=ROUND_HALF_UP), 'f')

    @api.model
    def _session_close_payload(self, session, printer=None):
        """Build a bounded aggregate snapshot without loading session orders."""
        self.env.flush_all()
        self.env.cr.execute('''
            SELECT COALESCE(SUM(amount_total::numeric), 0), COUNT(*),
                   COUNT(*) FILTER (WHERE is_refund),
                   COALESCE(SUM(GREATEST(customer_count, 0)) FILTER (WHERE NOT is_refund), 0)
              FROM pos_order
             WHERE session_id = %s AND company_id = %s AND config_id = %s
               AND state NOT IN ('draft', 'cancel')
        ''', [session.id, session.company_id.id, session.config_id.id])
        total_amount, invoice_count, refund_count, guest_count = self.env.cr.fetchone()
        total_amount = Decimal(total_amount or 0)
        invoice_count = int(invoice_count or 0)
        refund_count = int(refund_count or 0)
        guest_count = int(guest_count or 0)

        self.env.cr.execute('''
            SELECT COALESCE(SUM(GREATEST(line.qty, 0)), 0),
                   COUNT(DISTINCT line.product_id)
              FROM pos_order_line AS line
              JOIN pos_order AS order_record ON order_record.id = line.order_id
             WHERE order_record.session_id = %s
               AND order_record.company_id = %s
               AND order_record.config_id = %s
               AND order_record.state NOT IN ('draft', 'cancel')
        ''', [session.id, session.company_id.id, session.config_id.id])
        units_sold, products_sold = self.env.cr.fetchone()

        self.env.cr.execute('''
            SELECT payment_method_id, COALESCE(SUM(payment.amount::numeric), 0)
              FROM pos_payment AS payment
              JOIN pos_order AS order_record ON order_record.id = payment.pos_order_id
             WHERE order_record.session_id = %s
               AND order_record.company_id = %s
               AND order_record.config_id = %s
               AND order_record.state NOT IN ('draft', 'cancel')
             GROUP BY payment_method_id
             ORDER BY payment_method_id
        ''', [session.id, session.company_id.id, session.config_id.id])
        payment_rows = self.env.cr.fetchall()
        payment_total = sum((Decimal(amount or 0) for _method_id, amount in payment_rows), Decimal(0))
        methods = self.env['pos.payment.method'].sudo().with_company(session.company_id).browse(
            [row[0] for row in payment_rows]
        ).exists()
        method_names = {method.id: method.display_name for method in methods}

        self.env.cr.execute(
            """SELECT COUNT(*) FROM pos_order
                 WHERE session_id = %s AND company_id = %s AND config_id = %s AND state = 'cancel'""",
            [session.id, session.company_id.id, session.config_id.id],
        )
        cancelled_orders = int(self.env.cr.fetchone()[0] or 0)
        cancelled_items = self.env['baseer.print.preparation.event'].sudo().with_company(
            session.company_id
        ).search_count([
            ('session_id', '=', session.id),
            ('company_id', '=', session.company_id.id),
            ('pos_config_id', '=', session.config_id.id),
            ('action', '=', 'cancel'),
        ])

        closed_at = session.stop_at or fields.Datetime.now()
        opened_at = session.start_at or session.create_date or closed_at
        duration_seconds = max(0, int((closed_at - opened_at).total_seconds()))
        hours, remainder = divmod(duration_seconds, 3600)
        minutes = remainder // 60
        currency = session.currency_id
        average = total_amount / invoice_count if invoice_count else Decimal(0)
        average_per_guest = total_amount / guest_count if guest_count else Decimal(0)

        return {
            'schema': 3,
            'ticket_type': 'session_close',
            'printer': {
                'machine_identifier': printer.machine_identifier,
                'paper_width': printer.paper_width,
                'copies': 1,
            } if printer else False,
            'session': {
                'id': session.id,
                'reference': session.name,
                'point_of_sale': session.config_id.display_name,
                'cashier': session.user_id.display_name,
                'opened_at': fields.Datetime.to_string(opened_at),
                'closed_at': fields.Datetime.to_string(closed_at),
                'duration_seconds': duration_seconds,
                'duration_label': f'{hours:02d}:{minutes:02d}',
                'currency_code': currency.name,
            },
            'payments': [{
                'method': method_names.get(method_id, _('Unknown payment method')),
                'amount': self._format_session_amount(amount, currency),
            } for method_id, amount in payment_rows],
            'summary': {
                'invoice_count': invoice_count,
                'refund_count': refund_count,
                'payment_total': self._format_session_amount(payment_total, currency),
                'total_amount': self._format_session_amount(total_amount, currency),
                'average_invoice': self._format_session_amount(average, currency),
                'guest_count': guest_count,
                'average_per_guest': self._format_session_amount(average_per_guest, currency),
                'units_sold': self._format_session_amount(units_sold, currency),
                'products_sold': int(products_sold or 0),
                'cancelled_orders': cancelled_orders,
                'cancelled_items': cancelled_items,
                'cancellation_count': cancelled_orders + cancelled_items,
            },
        }

    @api.model
    def _enqueue_session_close(self, session):
        session.ensure_one()
        session = session.sudo().with_company(session.company_id)
        config = session.config_id
        if session.state != 'closed' or not config.baseer_print_session_close_report:
            return self.browse()
        existing = self.sudo().search([
            ('ticket_type', '=', 'session_close'),
            ('source_session_id', '=', session.id),
            ('reprint_of_id', '=', False),
            ('company_id', '=', session.company_id.id),
            ('pos_config_id', '=', config.id),
        ], order='id', limit=1)
        if existing:
            return existing
        printer = config.baseer_receipt_printer_id
        if not config.baseer_direct_print_enabled or not printer or not printer.active:
            raise ValidationError(_('The receipt printer is not ready for the session closing report.'))
        if not printer._allows_company(session.company_id):
            raise ValidationError(_('The receipt printer is not authorized for this company.'))
        return self._create_once({
            'company_id': session.company_id.id,
            'pos_config_id': config.id,
            'agent_id': printer.agent_id.id,
            'printer_id': printer.id,
            'source_session_id': session.id,
            'ticket_type': 'session_close',
            'payload': self._session_close_payload(session, printer),
            'idempotency_key': self._canonical_key('session-close', session.id),
        })

    @api.model
    def _release_expired_leases(self):
        self.sudo().search([('state', '=', 'leased'), ('lease_expires_at', '<', fields.Datetime.now())]).write({
            'state': 'failed', 'completed_at': fields.Datetime.now(), 'error_code': 'outcome_unknown',
            'error_detail': _('The agent lease expired before it confirmed the print result.'), 'lease_token': False,
        })

    @api.model
    def _claim_for_agent(self, agent):
        self._release_expired_leases()
        # Odoo 19 may defer ORM writes until flush. The claim query is raw SQL,
        # so make freshly created/rescheduled jobs visible before SKIP LOCKED.
        self.flush_model(['agent_id', 'state', 'available_at'])
        native_filter = '' if self._agent_supports_native_receipts(agent) else (
            "AND NOT (ticket_type = 'receipt' AND payload->>'schema' = '4')"
        )
        self.env.cr.execute(f'''SELECT id FROM baseer_print_job WHERE agent_id = %s AND state = 'pending'
            AND available_at <= NOW() {native_filter}
            ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1''', [agent.id])
        row = self.env.cr.fetchone()
        if not row:
            return False
        job = self.sudo().browse(row[0]).exists()
        payload = dict(job.payload)
        if job.ticket_type == 'receipt' and payload.get('schema') == 4:
            image_b64 = job.receipt_image
            try:
                raw = base64.b64decode(image_b64 or b'', validate=True)
            except (ValueError, binascii.Error):
                raw = b''
            if (not raw or len(raw) > NATIVE_RECEIPT_MAX_BYTES
                    or hashlib.sha256(raw).hexdigest() != job.receipt_image_sha256
                    or payload.get('receipt_image', {}).get('sha256') != job.receipt_image_sha256):
                job.write({'state': 'failed', 'completed_at': fields.Datetime.now(),
                           'error_code': 'invalid_receipt', 'error_detail': _('The stored receipt image is missing or invalid.')})
                return False
            payload['receipt_image'] = {**payload['receipt_image'], 'base64': base64.b64encode(raw).decode('ascii')}
        token, now = new_secret(24), fields.Datetime.now()
        job.write({'state': 'leased', 'lease_token': token, 'lease_expires_at': now + timedelta(minutes=2),
                   'sent_at': now, 'attempt_count': job.attempt_count + 1})
        return {'id': job.id, 'lease_token': token, 'lease_expires_at': fields.Datetime.to_string(job.lease_expires_at),
                'payload': payload}

    @api.model
    def _purge_accepted_native_receipt_images(self):
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        jobs = self.sudo().search([
            ('ticket_type', '=', 'receipt'), ('receipt_image_sha256', '!=', False),
            ('receipt_image_purged_at', '=', False), ('state', '=', 'done'),
            ('completed_at', '<', cutoff),
        ], limit=100)
        for job in jobs:
            job.write({'receipt_image': False, 'receipt_image_purged_at': fields.Datetime.now()})
        backlog = self.sudo().search_count([
            ('ticket_type', '=', 'receipt'), ('receipt_image_sha256', '!=', False),
            ('state', 'in', ('pending', 'leased')), ('create_date', '<', cutoff),
        ])
        if backlog:
            _logger.warning('Baseer native receipt backlog older than 24h: %s jobs', backlog)
        return len(jobs)

    def _validate_lease(self, agent, lease_token):
        self.ensure_one()
        if (self.agent_id != agent or self.state != 'leased' or not self.lease_expires_at
                or self.lease_expires_at < fields.Datetime.now() or not constant_time_equal(self.lease_token, lease_token)):
            raise AccessError(_('The print job lease is no longer valid.'))

    def _renew_for_agent(self, agent, lease_token):
        self._validate_lease(agent, lease_token)
        self.sudo().write({'lease_expires_at': fields.Datetime.now() + timedelta(minutes=2)})
        return fields.Datetime.to_string(self.lease_expires_at)

    def _complete_for_agent(self, agent, lease_token):
        self._validate_lease(agent, lease_token)
        self.sudo().write({'state': 'done', 'completed_at': fields.Datetime.now(), 'lease_token': False,
                           'lease_expires_at': False, 'error_code': False, 'error_detail': False})
        if self.ticket_type == 'receipt' and self.payload.get('schema') == 4 and self.source_order_id:
            order = self.source_order_id.sudo()
            accepted = self.sudo().search_count([
                ('source_order_id', '=', order.id), ('ticket_type', '=', 'receipt'),
                ('receipt_image_sha256', '!=', False), ('state', '=', 'done'),
            ])
            if order.nb_print < accepted:
                order.write({'nb_print': accepted})

    def _fail_for_agent(self, agent, lease_token, error_code, retryable=False):
        self._validate_lease(agent, lease_token)
        code = error_code if error_code in RETRYABLE_ERRORS | {'outcome_unknown', 'paper_unsupported', 'print_failed', 'invalid_receipt'} else 'print_failed'
        vals = {'error_code': code, 'error_detail': code, 'lease_token': False, 'lease_expires_at': False}
        if retryable and code in RETRYABLE_ERRORS and self.attempt_count < self.max_attempts:
            vals.update({'state': 'pending', 'available_at': fields.Datetime.now() + timedelta(seconds=BACKOFF_SECONDS[self.attempt_count - 1])})
        else:
            vals.update({'state': 'failed', 'completed_at': fields.Datetime.now()})
        self.sudo().write(vals)

    def action_confirm_paper_output(self):
        for job in self:
            if job.state != 'done':
                raise ValidationError(_('Only a Windows-accepted job can be confirmed physically.'))
            job.sudo().write({'paper_confirmed_at': fields.Datetime.now(), 'paper_confirmed_by': self.env.user.id})

    def action_reprint(self):
        for job in self:
            if not self.env.user.has_group('point_of_sale.group_pos_manager'):
                raise AccessError(_('Only a Point of Sale manager can reprint a job.'))
            if job.state not in ('done', 'failed', 'cancelled'):
                raise ValidationError(_('Only a completed, failed, or cancelled job can be reprinted.'))
            if job.ticket_type == 'receipt' and job.payload.get('schema') == 4 and not job.receipt_image:
                raise ValidationError(_(
                    'The receipt image has expired. A manager must recapture it from the original Odoo receipt screen.'
                ))
            self.env.cr.execute('SELECT id FROM baseer_print_job WHERE id = %s FOR UPDATE', [job.id])
            previous = self.sudo().search([('reprint_of_id', '=', job.id)], order='reprint_sequence desc', limit=1)
            sequence = previous.reprint_sequence + 1 if previous else 1
            self._create_once({'company_id': job.company_id.id, 'pos_config_id': job.pos_config_id.id,
                               'agent_id': job.agent_id.id, 'printer_id': job.printer_id.id,
                               'route_id': job.route_id.id, 'source_order_id': job.source_order_id.id,
                               'source_session_id': job.source_session_id.id,
                               'cancellation_id': job.cancellation_id.id,
                               'preparation_event_id': job.preparation_event_id.id,
                               'preparation_event_ids': [(6, 0, job.preparation_event_ids.ids)],
                               'ticket_type': job.ticket_type, 'payload': job.payload,
                               'receipt_image': job.receipt_image if job.ticket_type == 'receipt' else False,
                               'receipt_image_sha256': job.receipt_image_sha256,
                               'idempotency_key': self._canonical_key('manual-reprint', job.id, sequence),
                               'reprint_of_id': job.id, 'reprint_sequence': sequence})
        return True

