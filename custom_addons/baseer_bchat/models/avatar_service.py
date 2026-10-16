"""Private employee-avatar reads for BChat.

Images are deliberately served through BChat routes rather than a generic
attachment endpoint:
the route re-checks the active room membership at every request and never
exposes a predictable public attachment URL.
"""
import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from odoo import api, models
from odoo.exceptions import AccessError

from ..contracts import ProtocolError, positive_id


_AVATAR_MAX_BYTES = 256 * 1024
_AVATAR_MAX_PIXELS = 4_000_000
_AVATAR_EDGE = 128


def _as_avatar_png(value):
    """Safely normalise an existing Odoo binary image to a small PNG."""
    if isinstance(value, str):
        value = value.encode('ascii', 'ignore')
    if not isinstance(value, bytes) or not value:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
        if not raw or len(raw) > 2 * 1024 * 1024:
            return None
        with Image.open(io.BytesIO(raw)) as source:
            if (source.format not in ('JPEG', 'PNG', 'WEBP')
                    or source.width * source.height > _AVATAR_MAX_PIXELS):
                return None
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            image.thumbnail((_AVATAR_EDGE, _AVATAR_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG', optimize=True)
        encoded = output.getvalue()
        return encoded if encoded and len(encoded) <= _AVATAR_MAX_BYTES else None
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return None


class BChatAvatarService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_avatar_png_for_user(self, user, company=None):
        """Prefer the active employee image in this company, then user image."""
        candidates = []
        employee_model = self.env.registry.models.get('hr.employee')
        if employee_model:
            domain = [('active', '=', True), ('user_id', '=', user.id)]
            if company:
                domain.append(('company_id', '=', company.id))
            else:
                domain.append(('company_id', 'in', user.company_ids.ids))
            employee = self.env['hr.employee'].sudo().search(domain, order='company_id,id', limit=1)
            if employee:
                candidates.append(employee.image_128)
        candidates.append(user.sudo().image_128)
        for candidate in candidates:
            avatar = _as_avatar_png(candidate)
            if avatar:
                return avatar
        raise ProtocolError('avatar_missing', 'This employee has no usable image.', 404)

    @api.model
    def _v2_member_avatar(self, room_id, user_id):
        self._require_bchat_permission('chat_view')
        room = self._v2_lock_room(room_id)
        self._v2_current_member(room)
        target_id = positive_id(user_id, 'user_id')
        target_member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', target_id), ('active', '=', True),
        ], limit=1)
        if not target_member:
            raise AccessError(self.env._('This employee is unavailable in the room.'))
        return self._v2_avatar_png_for_user(target_member.user_id, room.company_id)

    @api.model
    def _v2_profile_avatar(self):
        user = self._require_any_bchat_permission('chat_view', 'task_view')
        # A user can have one employee record per allowed company.  Keep the
        # profile deterministic and aligned with the current Odoo company,
        # rather than leaking an arbitrary company-ordered employee image.
        return self._v2_avatar_png_for_user(user, self.env.company)
