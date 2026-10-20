"""Explicit immutable source configuration; no group creation or activation."""
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from ..business_contracts import PURPOSES, record_id


class BWorkBinding(models.Model):
    _name = 'baseer.bwork.binding'
    _description = 'BWork explicit company and purpose binding'
    _check_company_auto = True
    name = fields.Char(required=True)
    company_id = fields.Many2one('res.company', required=True, ondelete='restrict', index=True)
    channel_id = fields.Many2one('discuss.channel', required=True, ondelete='restrict', index=True)
    purpose = fields.Selection([(value, value.replace('_', ' ').title()) for value in PURPOSES], required=True)
    policy_reference = fields.Char(required=True)
    history_policy = fields.Selection([('pending', 'Blocked: decision pending'), ('since_join', 'Joining onward: QA required'),
                                       ('all_history', 'All history: explicit approval and QA required')], required=True, default='pending')
    history_policy_reference = fields.Char()
    _channel_unique = models.Constraint('unique(channel_id)', 'A group has one immutable company and purpose.')

    @api.model_create_multi
    def create(self, vals_list):
        self.env['baseer.bwork.service']._require_room_manager()
        allowed = {'name', 'company_id', 'channel_id', 'purpose', 'policy_reference', 'history_policy', 'history_policy_reference'}
        for vals in vals_list:
            if set(vals) - allowed or vals.get('company_id') != self.env.company.id:
                raise AccessError(self.env._('Configure an explicit binding in the active company.'))
            if not str(vals.get('policy_reference') or '').strip():
                raise ValidationError(self.env._('An explicit configuration reference is required.'))
        clean = self.with_context({'allowed_company_ids': self.env.company.ids, 'lang': self.env.lang})
        records = super(BWorkBinding, clean).create(vals_list)
        for record in records:
            record._require_valid(record.company_id.id, record.purpose, require_history=False)
        return records

    def write(self, values):
        if set(values) - {'name'}:
            raise AccessError(self.env._('Company, source, purpose and policy require a reviewed migration.'))
        self.env['baseer.bwork.service']._require_room_manager()
        return super().write(values)

    def unlink(self):
        raise AccessError(self.env._('Historical binding deletion is not enabled.'))

    def copy_data(self, default=None):
        raise AccessError(self.env._('Historical bindings cannot be copied.'))

    def _require_valid(self, company_id, purpose, *, require_history=True):
        self.ensure_one()
        if self.env.su or not self.env.user.active or not self.env.user._is_internal():
            raise AccessError(self.env._('An active individual internal user is required.'))
        self.check_access('read')
        if self.company_id.id != record_id(company_id) or self.purpose != purpose or self.company_id != self.env.company or self.company_id not in self.env.user.company_ids:
            raise AccessError(self.env._('The source company or purpose does not match.'))
        channel = self.channel_id
        channel.check_access('read')
        if not channel.active or channel.channel_type != 'group' or channel.parent_channel_id or not channel.is_member:
            raise AccessError(self.env._('An accessible private group with explicit membership is required.'))
        members = channel.channel_member_ids
        if not members or any(members.mapped('guest_id')):
            raise AccessError(self.env._('Guests and empty groups are unavailable.'))
        for member in members:
            identities = member.partner_id.user_ids.filtered('active')
            # All login identities on the partner count, including portal ones.
            if not identities or any(not user._is_internal() or self.company_id not in user.company_ids for user in identities):
                raise AccessError(self.env._('Every group identity must be internal and authorized for this company.'))
        if require_history and (self.history_policy == 'pending' or not (self.history_policy_reference or '').strip()):
            raise AccessError(self.env._('Explicit history policy and global security acceptance are required.'))
        # Intent only; adapters also call the unconditional source release gate.
        return channel
