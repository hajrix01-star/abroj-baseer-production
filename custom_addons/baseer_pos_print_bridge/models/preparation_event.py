import hashlib
import json
from uuid import UUID

from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .cancellation import CANCELLATION_REASONS


PREPARATION_ACTIONS = [
    ('new', 'New'),
    ('add', 'Added quantity'),
    ('reduce', 'Reduced quantity'),
    ('cancel', 'Cancelled'),
]


class BaseerPrintPreparationEvent(models.Model):
    _name = 'baseer.print.preparation.event'
    _description = 'Baseer Kitchen Preparation Event'
    _order = 'create_date, id'
    _check_company_auto = False

    company_id = fields.Many2one(
        'res.company', required=True, ondelete='restrict', index=True, readonly=True,
    )
    pos_config_id = fields.Many2one('pos.config', ondelete='set null', index=True, readonly=True)
    session_id = fields.Many2one('pos.session', ondelete='set null', index=True, readonly=True)
    order_id = fields.Many2one('pos.order', ondelete='set null', index=True, readonly=True)
    order_reference = fields.Char(required=True, readonly=True, index=True)
    order_line_id = fields.Many2one('pos.order.line', ondelete='set null', index=True, readonly=True)
    line_uuid = fields.Char(required=True, readonly=True, index=True)
    product_id = fields.Many2one('product.product', ondelete='set null', index=True, readonly=True)
    action = fields.Selection(PREPARATION_ACTIONS, required=True, readonly=True, index=True)
    previous_quantity = fields.Float(required=True, readonly=True)
    delta_quantity = fields.Float(required=True, readonly=True)
    new_quantity = fields.Float(required=True, readonly=True)
    reason_code = fields.Selection(CANCELLATION_REASONS, readonly=True, index=True)
    reason_note = fields.Char(readonly=True)
    cashier_name = fields.Char(required=True, readonly=True, index=True)
    requested_by = fields.Many2one('res.users', ondelete='set null', readonly=True, index=True)
    action_uuid = fields.Char(required=True, readonly=True, index=True)
    snapshot = fields.Json(required=True, readonly=True)
    job_ids = fields.Many2many(
        'baseer.print.job', compute='_compute_job_ids', readonly=True,
        string='Print Jobs',
    )

    _action_line_unique = models.Constraint(
        'unique(action_uuid, line_uuid)',
        'This kitchen line action has already been recorded.',
    )

    def init(self):
        self._cr.execute(
            'CREATE INDEX IF NOT EXISTS baseer_prep_event_company_created_idx '
            'ON baseer_print_preparation_event (company_id, create_date DESC, id DESC)'
        )
        self._cr.execute(
            'CREATE INDEX IF NOT EXISTS baseer_prep_event_order_created_idx '
            'ON baseer_print_preparation_event (order_id, create_date, id)'
        )
        self._cr.execute(
            'CREATE INDEX IF NOT EXISTS baseer_prep_event_line_created_idx '
            'ON baseer_print_preparation_event (line_uuid, create_date, id)'
        )

    def _compute_job_ids(self):
        jobs = self.env['baseer.print.job'].sudo().search([
            '|', ('preparation_event_id', 'in', self.ids), ('preparation_event_ids', 'in', self.ids),
        ]) if self.ids else self.env['baseer.print.job']
        for event in self:
            event.job_ids = jobs.filtered(
                lambda job: job.preparation_event_id == event or event in job.preparation_event_ids
            )

    @api.model
    def _canonical_uuid(self, value):
        if not isinstance(value, str) or len(value) > 36:
            raise ValidationError(_('The kitchen action identifier is invalid.'))
        try:
            canonical = str(UUID(value))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValidationError(_('The kitchen action identifier is invalid.')) from error
        if canonical != value.lower():
            raise ValidationError(_('The kitchen action identifier must use canonical UUID format.'))
        return canonical

    @api.constrains(
        'company_id', 'pos_config_id', 'session_id', 'order_id', 'order_line_id',
        'product_id', 'action', 'previous_quantity', 'delta_quantity',
        'new_quantity', 'reason_code', 'reason_note', 'action_uuid',
    )
    def _check_event(self):
        for event in self:
            event._canonical_uuid(event.action_uuid)
            if event.previous_quantity < 0 or event.new_quantity < 0:
                raise ValidationError(_('Kitchen event quantities cannot be negative.'))
            if abs((event.new_quantity - event.previous_quantity) - event.delta_quantity) > 0.000001:
                raise ValidationError(_('The kitchen event quantity delta is inconsistent.'))
            expected_action = (
                'new' if event.previous_quantity == 0 and event.new_quantity > 0 else
                'add' if event.new_quantity > event.previous_quantity else
                'cancel' if event.previous_quantity > 0 and event.new_quantity == 0 else
                'reduce' if 0 < event.new_quantity < event.previous_quantity else False
            )
            if not expected_action or event.action != expected_action:
                raise ValidationError(_('The kitchen event action is inconsistent with its quantities.'))
            if event.action == 'cancel' and not event.reason_code:
                raise ValidationError(_('A reason is required to cancel a kitchen item.'))
            if event.action != 'cancel' and event.reason_code:
                raise ValidationError(_('A cancellation reason is only valid for a cancelled kitchen item.'))
            note = (event.reason_note or '').strip()
            if event.reason_code == 'other' and not note:
                raise ValidationError(_('A description is required when the cancellation reason is Other.'))
            if event.reason_code != 'other' and note:
                raise ValidationError(_('Only the Other cancellation reason may include a description.'))
            if len(note) > 240:
                raise ValidationError(_('The cancellation description is too long.'))
            if event.pos_config_id and event.company_id and event.pos_config_id.company_id != event.company_id:
                raise ValidationError(_('The kitchen event point of sale belongs to another company.'))
            if event.session_id and event.pos_config_id and event.session_id.config_id != event.pos_config_id:
                raise ValidationError(_('The kitchen event session belongs to another point of sale.'))
            if event.order_id and event.company_id and event.order_id.company_id != event.company_id:
                raise ValidationError(_('The kitchen event order belongs to another company.'))
            if event.order_line_id and event.order_id and event.order_line_id.order_id != event.order_id:
                raise ValidationError(_('The kitchen event line belongs to another order.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('baseer_preparation_event_create'):
            raise AccessError(_('Kitchen preparation events can only be created by the preparation workflow.'))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_('Kitchen preparation events are immutable.'))

    def unlink(self):
        raise AccessError(_('Kitchen preparation events cannot be deleted.'))

    @api.model
    def _create_once(self, vals):
        domain = [('action_uuid', '=', vals['action_uuid']), ('line_uuid', '=', vals['line_uuid'])]
        existing = self.sudo().search(domain, limit=1)
        if existing:
            self._assert_same_request(existing, vals)
            return existing
        try:
            with self.env.cr.savepoint():
                return self.sudo().with_context(baseer_preparation_event_create=True).create(vals)
        except IntegrityError:
            existing = self.sudo().search(domain, limit=1)
            self._assert_same_request(existing, vals)
            return existing

    @api.model
    def _assert_same_request(self, event, vals):
        if not event or any([
            event.order_id.id != vals.get('order_id'),
            event.action != vals.get('action'),
            abs(event.previous_quantity - vals.get('previous_quantity', 0)) > 0.000001,
            abs(event.new_quantity - vals.get('new_quantity', 0)) > 0.000001,
            (event.reason_code or False) != (vals.get('reason_code') or False),
            (event.reason_note or '') != (vals.get('reason_note') or ''),
        ]):
            raise ValidationError(_('This kitchen action identifier was already used for different data.'))

    @api.model
    def _action_request_fingerprint(self, action):
        """Fingerprint the complete browser intent, including unrouted lines.

        Only routed lines create events, so their event snapshots must retain a
        digest of the full request for an exact and safe idempotent retry.
        """
        lines = [{
            'line_uuid': line['line_uuid'],
            'expected_quantity': format(line['expected_quantity'], '.6f'),
            'new_quantity': format(line['new_quantity'], '.6f'),
            'reason_code': line['reason_code'] or '',
            'reason_note': (line['reason_note'] or '').strip(),
        } for line in sorted(action['lines'], key=lambda item: item['line_uuid'])]
        canonical = json.dumps({
            'action_type': action['action_type'],
            'lines': lines,
        }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    @api.model
    def _retry_events(self, action):
        action_uuid = self._canonical_uuid(action['action_uuid'])
        events = self.sudo().search([('action_uuid', '=', action_uuid)], order='line_uuid, id')
        if not events:
            return events
        request_fingerprint = self._action_request_fingerprint(action)
        stored_fingerprints = {
            event.snapshot.get('request_fingerprint') for event in events
            if event.snapshot.get('request_fingerprint')
        }
        if stored_fingerprints:
            if stored_fingerprints != {request_fingerprint}:
                raise ValidationError(_('This kitchen action identifier was already used for different lines.'))
        elif set(events.mapped('line_uuid')) != {line['line_uuid'] for line in action['lines']}:
            # Compatibility for events created before the full-intent digest.
            raise ValidationError(_('This kitchen action identifier was already used for different lines.'))
        requested = {line['line_uuid']: line for line in action['lines']}
        if not set(events.mapped('line_uuid')).issubset(requested):
            raise ValidationError(_('This kitchen action identifier was already used for different lines.'))
        for event in events:
            line = requested[event.line_uuid]
            previous = line['expected_quantity']
            target = line['new_quantity']
            expected_action = (
                'new' if previous == 0 and target > 0 else
                'add' if target > previous else
                'cancel' if previous > 0 and target == 0 else
                'reduce' if 0 < target < previous else False
            )
            reason_code = line['reason_code'] or False
            reason_note = (line['reason_note'] or '').strip()
            if expected_action == 'cancel':
                reason_code, reason_note = self.env[
                    'baseer.print.cancellation'
                ]._normalized_reason(reason_code, reason_note)
            if (abs(event.previous_quantity - line['expected_quantity']) > 0.000001
                    or abs(event.new_quantity - line['new_quantity']) > 0.000001
                    or event.action != expected_action
                    or (event.reason_code or False) != reason_code
                    or (event.reason_note or '') != reason_note
                    or event.snapshot.get('request_action_type') != action['action_type']):
                raise ValidationError(_('This kitchen action identifier was already used for different quantities.'))
        return events

    @api.model
    def baseer_action_status(self, action_uuid, order_uuid):
        if not self.env.user.has_group('point_of_sale.group_pos_user'):
            raise AccessError(_('Only a Point of Sale user can inspect a kitchen action.'))
        action_uuid = self._canonical_uuid(action_uuid)
        events = self.sudo().search([('action_uuid', '=', action_uuid)])
        if not events:
            return {'accepted': False, 'pending': False, 'failed': False, 'done': False}
        orders = events.order_id
        if len(orders) != 1 or not orders.exists():
            raise ValidationError(_('The kitchen action does not have one valid order.'))
        order = orders.ensure_one()
        order.check_access_rights('read')
        order.check_access_rule('read')
        if order.company_id not in self.env.companies or order.uuid != order_uuid:
            raise AccessError(_('This kitchen action does not belong to the requested order.'))
        jobs = events.job_ids
        return {
            'accepted': True,
            'pending': bool(jobs.filtered(lambda job: job.state in ('pending', 'leased'))),
            'failed': bool(jobs.filtered(lambda job: job.state in ('failed', 'cancelled'))),
            'done': bool(jobs) and all(job.state == 'done' for job in jobs),
            'job_count': len(jobs),
        }

    @api.model
    def _snapshot_text(self, event):
        return json.dumps(event.snapshot, ensure_ascii=False, sort_keys=True)
