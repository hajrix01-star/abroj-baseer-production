"""Negotiated social metadata, isolated from legacy v87 route shapes."""
import re

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError, positive_id
from .api_v2 import BChatTextApi


class BChatSocialApi(http.Controller):
    _response = BChatTextApi._response
    _service = BChatTextApi._service
    _error = BChatTextApi._error
    _form = BChatTextApi._group_form_payload
    _no_query = staticmethod(BChatTextApi._no_query)

    @staticmethod
    def _args(allowed, required=()):
        args = request.httprequest.args
        if set(args) - set(allowed) or not set(required) <= set(args) or any(len(args.getlist(key)) != 1 for key in args):
            raise ProtocolError('invalid_payload', 'Unexpected or repeated query fields.')
        return args

    @staticmethod
    def _id(value, field):
        if type(value) is not str or not re.fullmatch(r'[1-9][0-9]*', value):
            raise ProtocolError('invalid_payload', 'A positive record ID is required.')
        return positive_id(int(value), field)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/preferences', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def preferences(self, room_id, **kwargs):
        try:
            args = self._args(('membership_id',), ('membership_id',))
            return self._response(self._service()._v2_room_preferences(room_id, self._id(args['membership_id'], 'membership_id')))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/preferences', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def set_preferences(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_set_room_preferences(room_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/social/rooms', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def rooms(self, **kwargs):
        try:
            args = self._args(('archived', 'cursor'))
            if args.get('archived', 'false') not in ('true', 'false'):
                raise ProtocolError('invalid_payload', 'Choose one archive filter.')
            return self._response(self._service()._v2_social_rooms(args.get('archived') == 'true', args.get('cursor')))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/direct-rooms', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def direct_room(self, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_direct_room(self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/social/member-candidates', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def member_candidates(self, **kwargs):
        try:
            args = self._args(('company_id', 'q', 'after_user_id'), ('company_id',))
            after = self._id(args['after_user_id'], 'after_user_id') if 'after_user_id' in args else None
            return self._response(self._service()._v2_social_member_candidates(
                self._id(args['company_id'], 'company_id'), args.get('q', ''), after))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/group/members', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def add_members(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_group_add_members(room_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/group/events', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def group_events(self, room_id, **kwargs):
        try:
            args = self._args(('membership_id', 'before_id'))
            member = self._id(args['membership_id'], 'membership_id') if 'membership_id' in args else None
            before = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            return self._response(self._service()._v2_group_events(room_id, member, before))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/search', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=8192)
    def search(self, room_id, **kwargs):
        try:
            self._no_query()
            return self._response(self._service()._v2_room_search(room_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/rooms/<int:room_id>/media', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def media(self, room_id, **kwargs):
        try:
            args = self._args(('membership_id', 'kind', 'before_id'), ('membership_id',))
            before = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            return self._response(self._service()._v2_room_media(
                room_id, self._id(args['membership_id'], 'membership_id'), args.get('kind', 'all'), before))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
