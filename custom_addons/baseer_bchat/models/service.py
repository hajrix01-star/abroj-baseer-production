"""Private authorization boundary. No native business mutations are wired."""
from odoo import api, models
from odoo.exceptions import AccessError

from .. import contracts


class BChatService(models.AbstractModel):
    _name = 'baseer.bchat.service'
    _description = 'BChat private API boundary'

    @api.model
    def _require_user(self):
        user = self.env.user
        if self.env.su or not user.active or not user._is_internal():
            raise AccessError(self.env._('An authorized individual BChat user session is required.'))
        return user

    @api.model
    def _require_bchat_permission(self, key):
        user = self._require_user()
        if key not in ('chat_view', 'chat_send', 'media', 'media_view',
                       'media_upload', 'media_download', 'group_create',
                       'group_manage', 'task_view', 'task_manage', 'room_admin'):
            raise ValueError('Unknown BChat permission')
        if not user._bchat_effective_permissions()[key]:
            raise AccessError(self.env._('This BChat action is not enabled for your user.'))
        return user

    @api.model
    def _require_any_bchat_permission(self, *keys):
        user = self._require_user()
        permitted = user._bchat_effective_permissions()
        allowed = {'chat_view', 'chat_send', 'media', 'media_view',
                   'media_upload', 'media_download', 'group_create',
                   'group_manage', 'task_view', 'task_manage', 'room_admin'}
        if not keys or any(key not in allowed for key in keys):
            raise ValueError('Unknown BChat permission')
        if not any(permitted[key] for key in keys):
            raise AccessError(self.env._('This BChat action is not enabled for your user.'))
        return user

    @api.model
    def _require_media_right(self, operation):
        """One boundary shared by previews, originals and optional DMS readers."""
        if operation not in ('view', 'upload', 'download'):
            raise ValueError('Unknown BChat media operation')
        return self._require_bchat_permission('media_' + operation)

    @api.model
    def _require_room_manager(self):
        return self._require_bchat_permission('room_admin')

    @api.model
    def _bootstrap(self):
        user = self._require_user()
        result = contracts.capabilities()
        result['user_id'] = user.id
        result['database'] = self.env.cr.dbname
        # No employee directory, channels, task data, tokens or financial data.
        result['company_ids'] = user.company_ids.ids
        return result

    @api.model
    def _company_scope(self, company_id):
        user = self._require_user()
        company_id = contracts.positive_id(company_id, 'company_id')
        if company_id not in user.company_ids.ids:
            raise AccessError(self.env._('The company is outside your authorized companies.'))
        # Replace caller context, rather than merging untrusted default/skip,
        # allowed-company, guest, token or mail_* flags into native operations.
        scoped = self.with_context({
            'allowed_company_ids': [company_id],
            'lang': self.env.lang,
            'tz': user.tz or 'UTC',
        })
        scoped.env['res.company'].browse(company_id).check_access('read')
        return scoped

    @api.model
    def _prepare_conversation(self, payload):
        user = self._require_room_manager()
        normalized = contracts.normalize_conversation(payload)
        scoped = self._company_scope(normalized['company_id'])
        if user.id not in normalized['member_user_ids']:
            raise AccessError(self.env._('The creating manager must be an explicit member.'))
        members = scoped.env['res.users'].browse(normalized['member_user_ids'])
        members.check_access('read')
        if len(members.exists()) != len(normalized['member_user_ids']):
            raise AccessError(self.env._('One or more members are unavailable.'))
        for member in members:
            # No sudo fallback when a role cannot inspect the needed fields.
            if (not member.active or not member._is_internal()
                    or normalized['company_id'] not in member.company_ids.ids):
                raise AccessError(self.env._('All members must be authorized internal users of the selected company.'))
        return normalized

    @api.model
    def _submit_message(self, payload):
        self._require_user()
        contracts.normalize_message(payload)
        # No native channel has a trusted BChat company/history binding yet.
        # Do not pretend that Discuss membership alone authorizes that binding.
        contracts.require_released()

    @api.model
    def _create_conversation(self, payload):
        self._require_room_manager()
        contracts.normalize_conversation(payload)
        # Even manager access and selecting all_history cannot open this gate.
        contracts.require_released()
