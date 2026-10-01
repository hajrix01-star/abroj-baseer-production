import hashlib
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class BaseerPrintPreparationAttempt(models.Model):
    _name = 'baseer.print.preparation.attempt'
    _description = 'Baseer Kitchen Preparation Attempt Receipt'
    _order = 'id'

    action_uuid = fields.Char(required=True, readonly=True, index=True)
    order_uuid = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, ondelete='restrict')
    session_id = fields.Many2one('pos.session', required=True, readonly=True, ondelete='restrict')
    order_id = fields.Many2one('pos.order', readonly=True, ondelete='set null', index=True)
    request_fingerprint = fields.Char(required=True, readonly=True)
    outcome = fields.Selection([('accepted', 'Accepted'), ('skipped', 'Skipped')], required=True, readonly=True)
    requested_by = fields.Many2one('res.users', readonly=True, ondelete='set null')
    decided_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    _action_uuid_unique = models.Constraint(
        'unique(action_uuid)', 'This kitchen attempt has already been resolved.',
    )

    @api.model
    def _lock_action(self, action_uuid):
        canonical = self.env['baseer.print.preparation.event']._canonical_uuid(action_uuid)
        key = int.from_bytes(hashlib.sha256(
            ('baseer-preparation-attempt:' + canonical).encode('ascii'),
        ).digest()[:8], 'big', signed=True)
        self.env.cr.execute('SELECT pg_advisory_xact_lock(%s)', [key])

    @api.model
    def _for_action(self, action_uuid):
        return self.sudo().search([('action_uuid', '=', action_uuid)], limit=1)

    @api.constrains('action_uuid', 'order_uuid', 'company_id', 'session_id', 'order_id', 'request_fingerprint')
    def _check_receipt(self):
        for receipt in self:
            self.env['baseer.print.preparation.event']._canonical_uuid(receipt.action_uuid)
            if not re.fullmatch('[0-9a-f]{64}', receipt.request_fingerprint):
                raise ValidationError(_('The kitchen attempt fingerprint is invalid.'))
            if (receipt.session_id.company_id != receipt.company_id
                    or (receipt.order_id and (
                        receipt.order_id.uuid != receipt.order_uuid
                        or receipt.order_id.company_id != receipt.company_id
                        or receipt.order_id.session_id != receipt.session_id))):
                raise ValidationError(_('The kitchen attempt does not belong to its order and session.'))

    @api.model_create_multi
    def create(self, vals_list):
        raise AccessError(_('Kitchen attempt receipts can only be recorded by the preparation workflow.'))

    def write(self, vals):
        raise AccessError(_('Kitchen attempt receipts are immutable.'))

    def unlink(self):
        raise AccessError(_('Kitchen attempt receipts cannot be deleted.'))

    @api.model
    def _record_decision(self, order, action, outcome):
        return super(BaseerPrintPreparationAttempt, self.sudo()).create({
            'action_uuid': action['action_uuid'], 'order_uuid': order.uuid,
            'company_id': order.company_id.id, 'session_id': order.session_id.id,
            'order_id': order.id,
            'request_fingerprint': self.env['baseer.print.preparation.event']._action_request_fingerprint(action),
            'outcome': outcome, 'requested_by': self.env.user.id,
        })

    def _assert_identity(self, order_uuid, session_id=False, order=False, action=False):
        self.ensure_one()
        caller = self.sudo(False).env
        if (self.company_id not in caller.companies
                or self.order_uuid != order_uuid
                or (session_id and self.session_id.id != session_id)
                or (order and self.order_id.id != order.id)):
            raise AccessError(_('This kitchen attempt does not belong to the synchronized order.'))
        caller['pos.session'].browse(self.session_id.id).check_access('read')
        if action and self.request_fingerprint != caller[
                'baseer.print.preparation.event']._action_request_fingerprint(action):
            raise ValidationError(_('This kitchen action identifier was already used for different data.'))
        original = caller['pos.order'].browse(self.order_id.id).exists()
        if not original:
            raise UserError(_('The original kitchen order was deleted. Refresh the point of sale.'))
        original.check_access('read')
        if (original.uuid != self.order_uuid or original.company_id != self.company_id
                or original.session_id != self.session_id):
            raise AccessError(_('This kitchen attempt does not belong to the synchronized order.'))
        return original
