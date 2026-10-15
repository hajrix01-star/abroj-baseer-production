"""Recheck current BChat user switches on notification entrypoints.

The upstream notification service still decides whether the caller may see the
particular company, room, membership epoch, message, task or order. This
extension only closes the gap when a user's BChat section is switched off.
"""

from odoo import api, models


class BChatPermissionGuardService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _notify_recipient_ref(self, recipient):
        source = recipient.event_id.source_model
        if source == 'message':
            self._require_bchat_permission('chat_view')
        elif source == 'task':
            self._require_bchat_permission('task_view')
        elif source == 'order':
            # Both destinations originate in BChat. A representative need not
            # see the order tab: upstream still verifies the assigned partner
            # and company for the dedicated order link, while room members
            # remain subject to their membership epoch.
            self._require_bchat_permission('chat_view')
        return super()._notify_recipient_ref(recipient)

    @api.model
    def _v2_room_message_detail(self, room_id, message_id):
        self._require_bchat_permission('chat_view')
        return super()._v2_room_message_detail(room_id, message_id)

    @api.model
    def _v2_order_representative_detail(self, order_id):
        self._require_bchat_permission('chat_view')
        return super()._v2_order_representative_detail(order_id)
