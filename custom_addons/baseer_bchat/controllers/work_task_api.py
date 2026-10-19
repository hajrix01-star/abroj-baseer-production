"""Separate modern facade; legacy /tasks is deliberately unchanged."""
import json

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from ..contracts import ProtocolError
from .task_api import BChatTaskApi


class BChatWorkTaskApi(http.Controller):
    # Reuse validation, not decorated routes: modern response serialization
    # must not accidentally republish or change legacy route handlers.
    _service = BChatTaskApi._service
    _error = BChatTaskApi._error
    _args = staticmethod(BChatTaskApi._args)
    _id = staticmethod(BChatTaskApi._id)
    _form = staticmethod(BChatTaskApi._form)

    def _response(self, payload, status=200):
        # Identical UTF-8/compact encoding to the measured contract byte caps.
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return request.make_response(body, status=status, headers=[
            ('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store'),
            ('Pragma', 'no-cache'), ('Vary', 'Cookie'), ('X-Content-Type-Options', 'nosniff'),
        ])

    @http.route('/bchat/api/v2/work-tasks/options', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def work_options(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._work_task_options())
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/work-tasks/assignees', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def work_assignees(self, **kwargs):
        try:
            args = self._args(('company_id', 'q', 'after_id'))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            company = self._id(args['company_id'], 'company_id')
            after = self._id(args['after_id'], 'after_id') if 'after_id' in args else None
            return self._response(self._service()._work_task_assignees(company, args.get('q', ''), after))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/work-tasks', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def work_tasks(self, **kwargs):
        try:
            args = self._args(('view', 'state', 'company_id', 'before_id'))
            company = self._id(args['company_id'], 'company_id') if 'company_id' in args else None
            before = self._id(args['before_id'], 'before_id') if 'before_id' in args else None
            return self._response(self._service()._work_tasks(
                args.get('view', 'mine'), args.get('state', 'open'), company, before))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/work-tasks/<int:task_id>', type='http', auth='user',
                methods=['GET'], csrf=True, save_session=True)
    def work_detail(self, task_id, **kwargs):
        try:
            args = self._args(('company_id',))
            if 'company_id' not in args:
                raise ProtocolError('invalid_payload', 'company_id is required.')
            return self._response(self._service()._work_task_detail(
                task_id, self._id(args['company_id'], 'company_id')))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/work-tasks', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def work_create(self, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._work_task_create(self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)

    @http.route('/bchat/api/v2/work-tasks/<int:task_id>/transition', type='http', auth='user',
                methods=['POST'], csrf=True, save_session=True, max_content_length=65536)
    def work_transition(self, task_id, **kwargs):
        try:
            self._args(())
            return self._response(self._service()._work_task_transition(task_id, self._form()))
        except (AccessError, ProtocolError) as error:
            return self._error(error)
