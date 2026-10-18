"""Company-scoped policy and direct conversations using existing BChat contracts."""
from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo import api, models
from odoo.exceptions import AccessError
from odoo.addons.baseer_bchat.contracts import ProtocolError, canonical_uuid, positive_id

from .room import _DIRECT_TOKEN


def _payload(payload, keys):
    if type(payload) is not dict or set(payload) != {'api_version', *keys}:
        raise ProtocolError('invalid_payload', 'Unexpected mobile policy payload fields.')
    if type(payload['api_version']) is not int or payload['api_version'] != 2:
        raise ProtocolError('unsupported_version', 'API version 2 is required.')


class BChatMobileService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _mobile_company(self, company_id, *, manage=False):
        user = self._require_user()
        company_id = positive_id(company_id, 'company_id')
        if company_id not in user.company_ids.ids:
            raise AccessError(self.env._('This company is outside your allowed companies.'))
        if manage and not user._bchat_effective_permissions()['mobile_admin']:
            raise AccessError(self.env._('Mobile application administration is not assigned.'))
        return self.env['res.company'].sudo().browse(company_id)

    @api.model
    def _mobile_policy(self, company_id):
        company = self._mobile_company(company_id)
        company._mobile_lock_policy()
        return {
            'api_version': 2, 'company_id': company.id,
            'direct_enabled': bool(company.bchat_mobile_direct_enabled),
            'can_manage': self._require_user()._bchat_effective_permissions()['mobile_admin'],
        }

    @api.model
    def _mobile_policy_set(self, payload):
        _payload(payload, {'company_id', 'direct_enabled'})
        if type(payload['direct_enabled']) is not bool:
            raise ProtocolError('invalid_payload', 'direct_enabled must be a boolean.')
        self._mobile_company(payload['company_id'], manage=True)
        # Invoke with the original user environment before the narrow setter
        # elevates only its one already-authorized company boolean write.
        company = self.env['res.company'].browse(payload['company_id'])
        company._mobile_set_direct_enabled(payload['direct_enabled'])
        return self._mobile_policy(company.id)

    @api.model
    def _mobile_candidates(self, company_id, query=''):
        user = self._require_user()
        company = self._mobile_company(company_id)
        if (type(query) is not str or len(query) > 80
                or any(ord(char) < 32 for char in query)):
            raise ProtocolError('invalid_payload', 'Invalid member search.')
        rights = user._bchat_effective_permissions()
        company._mobile_lock_policy()
        group_allowed = any(rights[key] for key in ('group_create', 'group_manage', 'room_admin'))
        direct_allowed = rights['chat_send'] and company.bchat_mobile_direct_enabled
        if not group_allowed and not direct_allowed:
            raise AccessError(self.env._('Member search is not enabled for this user.'))
        # Elevated access is bounded to the validated company and the minimum
        # display fields. Never grant an ORM directory ACL to mobile users.
        domain = [('active', '=', True), ('share', '=', False),
                  ('company_ids', 'in', [company.id]), ('id', '!=', user.id),
                  ('bchat_chat_view', '=', True)]
        if query.strip():
            domain.append(('name', 'ilike', query.strip()))
        found = self.env['res.users'].sudo().search(domain, order='name,id', limit=40)
        return {'api_version': 2, 'users': [
            {'user_id': candidate.id, 'name': candidate.name or ''}
            for candidate in found if candidate._is_internal()
        ]}

    @api.model
    def _v2_bootstrap(self):
        result = super()._v2_bootstrap()
        result['mobile_policy'] = [self._mobile_policy(company_id)
                                   for company_id in result['company_ids']]
        return result

    @api.model
    def _v2_room_rows(self, memberships):
        result = super()._v2_room_rows(memberships)
        direct_ids = set(memberships.sudo().mapped('room_id').filtered('mobile_direct').ids)
        for row in result:
            row['mobile_direct'] = row['id'] in direct_ids
        return result

    @api.model
    def _mobile_require_direct_writable(self, room):
        if not room.mobile_direct:
            return
        self._mobile_company(room.company_id.id)
        company = room.company_id
        company._mobile_lock_policy()
        if not company.bchat_mobile_direct_enabled:
            raise ProtocolError('direct_disabled', 'Direct conversations are disabled in this company.', 403)
        # A removed/inactive colleague cannot keep receiving new content in
        # this pair. Old history remains subject to each reader's own rights.
        for participant in room.mobile_direct_low_user_id | room.mobile_direct_high_user_id:
            if (not participant.active or not participant._is_internal()
                    or company not in participant.company_ids
                    or not participant._bchat_effective_permissions()['chat_view']):
                raise AccessError(self.env._('A direct conversation participant is unavailable.'))

    @api.model
    def _v2_lock_room(self, room_id, *, mutate=False):
        # Inspect before the legacy room lock, so all writers share one lock
        # order with policy changes. IDs grant no authority: company is checked
        # here and active membership remains checked by the original service.
        if mutate:
            room = self.env['baseer.bchat.room'].sudo().browse(positive_id(room_id, 'room_id')).exists()
            if room:
                self._mobile_require_direct_writable(room)
        return super()._v2_lock_room(room_id, mutate=mutate)

    @api.model
    def _v2_upload_scope(self, room_id, metadata):
        normalized = super()._v2_upload_scope(room_id, metadata)
        room = self.env['baseer.bchat.room'].sudo().browse(room_id)
        self._mobile_require_direct_writable(room)
        return normalized

    @api.model
    def _mobile_direct(self, payload):
        _payload(payload, {'company_id', 'user_id', 'client_uuid'})
        canonical_uuid(payload['client_uuid'])
        user = self._require_bchat_permission('chat_send')
        company = self._mobile_company(payload['company_id'])
        company._mobile_lock_policy()
        if not company.bchat_mobile_direct_enabled:
            raise ProtocolError('direct_disabled', 'Direct conversations are disabled in this company.', 403)
        target_id = positive_id(payload['user_id'], 'user_id')
        target = self.env['res.users'].sudo().browse(target_id).exists()
        if (not target or target.id == user.id or not target.active or not target._is_internal()
                or company not in target.company_ids
                or not target._bchat_effective_permissions()['chat_view']):
            raise AccessError(self.env._('Choose an authorized colleague in this company.'))
        low, high = sorted([user.id, target.id])
        rooms = self.env['baseer.bchat.room'].sudo().with_context(allowed_company_ids=[company.id])
        domain = [('company_id', '=', company.id), ('mobile_direct', '=', True),
                  ('mobile_direct_low_user_id', '=', low), ('mobile_direct_high_user_id', '=', high)]
        room = rooms.search(domain, limit=1)
        if room:
            room = self._v2_lock_room(room.id)
            member = self._v2_current_member(room)
            return {'api_version': 2, 'room_id': room.id, 'membership_id': member.id, 'replayed': True}
        with self.env.cr.savepoint():
            self.env['baseer.bchat.membership']._assert_room_capacity_for_users([low, high])
            try:
                with self.env.cr.savepoint():
                    room = rooms._create_mobile_direct_verified({
                        'name': '%s / %s' % (user.name[:60], target.name[:60]),
                        'company_id': company.id, 'mobile_direct': True,
                        'mobile_direct_low_user_id': low, 'mobile_direct_high_user_id': high,
                    }, _DIRECT_TOKEN)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_room_mobile_direct_pair_unique':
                    raise
                # The winner can be invisible to our REPEATABLE READ snapshot.
                # Let Odoo retry the complete HTTP request on a fresh snapshot;
                # do not fabricate an ACK from an unverified record.
                raise SerializationFailure('Retry concurrent direct conversation opening.') from None
            members = self.env['baseer.bchat.membership'].with_context(
                allowed_company_ids=[company.id])._create_mobile_direct_verified(room, _DIRECT_TOKEN)
            self._change_publish([low, high], 'room', room_id=room.id, company_id=company.id,
                                 memberships={row.user_id.id: row.id for row in members})
            member = members.filtered(lambda row: row.user_id.id == user.id)
            return {'api_version': 2, 'room_id': room.id, 'membership_id': member.id, 'replayed': False}
