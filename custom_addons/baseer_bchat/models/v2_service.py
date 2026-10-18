"""Private BChat-only text API. All privileged reads follow a fresh membership check."""
import json
import unicodedata

from psycopg2.errors import UniqueViolation

from odoo import api, fields, models
from odoo.exceptions import AccessError, MissingError

from .. import v2_contracts
from ..contracts import ProtocolError, positive_id
from .message import _SERVICE_TOKEN
from .media import _MEDIA_TOKEN
from .message_receipt import _RECEIPT_TOKEN


_ACK_MEMBERSHIP_ABSENT = object()


class BChatTextService(models.AbstractModel):
    _inherit = 'baseer.bchat.service'

    @api.model
    def _v2_bootstrap(self):
        user = self._require_user()
        allowed_company_ids = sorted(user.company_ids.ids)
        result = {
            'api_version': 2,
            'database': self.env.cr.dbname,
            'user_id': user.id,
            'company_ids': allowed_company_ids,
            'current_company_id': (user.company_id.id
                                   if user.company_id.id in allowed_company_ids else None),
            'receipt_delivery_contract_version': 1,
            'history_search_contract_version': 1,
            'room_preferences_contract_version': 1,
            'capabilities': {
                'rooms': True, 'messages': True, 'history': True,
                'attachments': True, 'tasks': False, 'shifts': False,
                'procurement': False, 'report_events': False,
                'delivery_receipts': True, 'read_receipts': True,
            },
            'permissions': user._bchat_effective_permissions(),
        }
        try:
            # Profile data is optional; a failed HR read must not block chat login.
            with self.env.cr.savepoint():
                profile = self._v2_profile(user)
                size = len(json.dumps(profile, ensure_ascii=False).encode('utf-8'))
                if size > 16 * 1024:
                    # Keep the company picker usable when optional HR titles
                    # alone make the profile too large.
                    for company in profile['companies']:
                        company['job_titles'] = []
                    size = len(json.dumps(profile, ensure_ascii=False).encode('utf-8'))
            if size > 16 * 1024:
                result.update(profile=None, profile_error='profile_too_large')
            else:
                result['profile'] = profile
        except Exception:
            result.update(profile=None, profile_error='profile_unavailable')
        return result

    @api.model
    def _v2_profile(self, user):
        companies = sorted(user.company_ids, key=lambda company: company.id)
        company_profiles = []
        for company in companies:
            profile = {
                'id': company.id,
                'name': company.name or '',
                'job_titles': [],
            }
            # The bilingual company fields come from an optional module. Keep
            # their native values separate; `name` can contain both languages.
            if 'baseer_name_ar' in company._fields:
                profile['name_ar'] = (company.baseer_name_ar or '').strip()
            if 'baseer_name_en' in company._fields:
                profile['name_en'] = (company.baseer_name_en or '').strip()
            company_profiles.append(profile)
        by_company = {company['id']: company for company in company_profiles}
        titles_by_company = {}
        if by_company:
            try:
                # HR is optional. Roll back even a database-level HR failure,
                # while keeping the already-authorized company names visible.
                with self.env.cr.savepoint():
                    titles_by_company = self._v2_employee_titles(user, list(by_company))
            except Exception:
                titles_by_company = {}
        for company in company_profiles:
            company['job_titles'] = sorted(set(titles_by_company.get(company['id'], [])),
                                           key=lambda title: (title.casefold(), title))
        return {'name': user.name or '', 'companies': company_profiles}

    @api.model
    def _v2_employee_titles(self, user, company_ids):
        if not self.env.registry.models.get('hr.employee'):
            return {}
        employees = self.env['hr.employee'].sudo().search_read([
            ('active', '=', True),
            ('user_id', '=', user.id),
            ('company_id', 'in', company_ids),
        ], fields=['company_id', 'job_title'], limit=257)
        if len(employees) >= 257:
            raise ValueError('BChat profile employee limit exceeded')
        titles_by_company = {company_id: [] for company_id in company_ids}
        for employee in employees:
            company_id = employee['company_id'][0] if employee['company_id'] else None
            title = (employee['job_title'] or '').strip()
            if company_id in titles_by_company and title:
                titles_by_company[company_id].append(title)
        return titles_by_company

    @api.model
    def _v2_rooms(self):
        user = self._require_bchat_permission('chat_view')
        memberships = self.env['baseer.bchat.membership'].sudo().search([
            ('user_id', '=', user.id), ('active', '=', True),
            ('company_id', 'in', user.company_ids.ids),
        ], order='id desc', limit=101)
        if len(memberships) > 100:
            raise ProtocolError('too_many_rooms', 'Room listing needs pagination.', 409)
        for room_id in sorted(set(memberships.mapped('room_id').ids)):
            self.env['baseer.bchat.room']._lock_for_read(room_id)
        memberships.invalidate_recordset(['active'])
        return {'api_version': 2, 'rooms': self._v2_room_rows(
            memberships.filtered('active'))}

    @api.model
    def _v2_room_rows(self, memberships):
        """Bounded, epoch-filtered list metadata for rooms and reset snapshots."""
        if not memberships:
            return []
        if len(memberships) > 100:
            raise ProtocolError('too_many_rooms', 'Room listing needs pagination.', 409)
        task_view = bool(self._require_user()._bchat_effective_permissions().get('task_view'))
        self.env.cr.execute('''
            SELECT membership.id, latest.id, latest.text, latest.create_date,
                   media.kind, COALESCE(unread.total, 0), COALESCE(members.total, 0),
                   COALESCE(tasks.has_active_task, FALSE)
            FROM baseer_bchat_membership AS membership
            LEFT JOIN LATERAL (
                SELECT message.id, message.text, message.create_date, message.media_id
                FROM baseer_bchat_message AS message
                WHERE message.room_id = membership.room_id
                  AND message.id > membership.joined_after_message_id
                ORDER BY message.id DESC LIMIT 1
            ) AS latest ON TRUE
            LEFT JOIN baseer_bchat_media AS media ON media.id = latest.media_id
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS total
                FROM baseer_bchat_message_receipt AS receipt
                WHERE receipt.membership_id = membership.id
                  AND receipt.recipient_user_id = %s
                  AND receipt.read_at IS NULL
                  AND receipt.message_id > membership.joined_after_message_id
            ) AS unread ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS total FROM baseer_bchat_membership AS other
                WHERE other.room_id = membership.room_id AND other.active
            ) AS members ON TRUE
            LEFT JOIN LATERAL (
                SELECT EXISTS(
                    SELECT 1 FROM baseer_bchat_task AS task
                    WHERE task.room_id = membership.room_id
                      AND task.company_id = membership.company_id
                      AND task.state IN ('new', 'in_progress')
                ) AS has_active_task
            ) AS tasks ON TRUE
            WHERE membership.id = ANY(%s) AND membership.active
        ''', [self.env.uid, memberships.ids])
        metadata = {row[0]: row[1:] for row in self.env.cr.fetchall()}
        result = []
        for member in memberships:
            if member.id not in metadata:
                continue
            last_id, text, created_at, media_kind, unread_count, member_count, has_active_task = metadata[member.id]
            preview = ' '.join((text or '').split())[:160]
            room = member.room_id
            result.append({
                'id': room.id, 'company_id': member.company_id.id,
                'name': room.name, 'membership_id': member.id,
                'invoice_policy': room.invoice_policy,
                'invoice_policy_version': room.invoice_policy_version,
                'is_group': bool(room.is_group),
                'is_group_admin': bool(member.is_group_admin),
                'avatar_version': room.avatar_version,
                'member_count': member_count,
                'last_message_id': last_id or 0,
                'last_message_preview': preview,
                'last_message_kind': media_kind or None,
                'last_message_at': fields.Datetime.to_string(created_at) if created_at else None,
                'unread_count': unread_count,
                # Neutral group indicator; never a task title or description.
                'has_active_task': bool(has_active_task) if task_view else False,
            })
        return result

    @api.model
    def _v2_lock_room(self, room_id, *, mutate=False):
        user = self._require_user()
        room_id = positive_id(room_id, 'room_id')
        locker = self.env['baseer.bchat.room']
        if mutate:
            locker._lock_for_mutation(room_id)
        else:
            locker._lock_for_read(room_id)
        room = self.env['baseer.bchat.room'].sudo().browse(room_id)
        if room.company_id.id not in user.company_ids.ids:
            raise AccessError(self.env._('This room is unavailable.'))
        return room

    @api.model
    def _v2_current_member(self, room):
        member = self.env['baseer.bchat.membership'].sudo().search([
            ('room_id', '=', room.id), ('user_id', '=', self.env.uid),
            ('active', '=', True),
        ], limit=1)
        if not member:
            raise AccessError(self.env._('This room is unavailable.'))
        return member

    @api.model
    def _v2_history(self, room_id, before_id=None):
        self._require_bchat_permission('chat_view')
        if before_id is not None:
            before_id = positive_id(before_id, 'before_id')
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        domain = [('room_id', '=', room.id), ('id', '>', member.joined_after_message_id)]
        if before_id is not None:
            domain.append(('id', '<', before_id))
        found = self.env['baseer.bchat.message'].sudo().search(domain, order='id desc', limit=31)
        page = list(found[:30])
        more = len(found) > 30
        # Referenced messages are fetched as one bounded, visibility-filtered page.
        reply_ids = {message.reply_to_message_id.id for message in page if message.reply_to_message_id}
        parents = self.env['baseer.bchat.message'].sudo().search([
            ('id', 'in', list(reply_ids)), ('room_id', '=', room.id),
            ('id', '>', member.joined_after_message_id),
        ]) if reply_ids else self.env['baseer.bchat.message']
        parent_by_id = {parent.id: parent for parent in parents}
        # Names are read only for messages visible in this membership period.
        author_names = self._v2_author_names(page + list(parents))
        while page:
            payload = {**self._v2_history_payload(page, more, author_names, parent_by_id),
                       'room_id': room.id, 'membership_id': member.id}
            if len(json.dumps(payload, ensure_ascii=False).encode('utf-8')) <= 131072:
                return payload
            page.pop()
            more = True
        return {'api_version': 2, 'room_id': room.id, 'membership_id': member.id,
                'messages': [], 'next_before_id': None}

    @api.model
    def _v2_author_names(self, page):
        return self._v2_visible_user_names({message.author_user_id.id for message in page})

    @api.model
    def _v2_visible_user_names(self, user_ids):
        author_ids = sorted(set(user_ids))
        names = {author_id: 'User' for author_id in author_ids}
        if not author_ids:
            return names
        try:
            # Never read names through the sudoed messages. Native search/read
            # applies the caller's ACL and record rules to this whole bounded
            # page+reply batch. Archived authors retain their existing names.
            rows = self.env['res.users'].with_context(active_test=False).search_read(
                [('id', 'in', author_ids)], fields=['name'], order='id', limit=len(author_ids))
        except (AccessError, MissingError):
            return names
        for row in rows:
            candidate = ''.join(char for char in (row['name'] or '')
                                if not unicodedata.category(char).startswith('C')).strip()
            if candidate:
                names[row['id']] = candidate[:120].encode('utf-8')[:256].decode('utf-8', 'ignore') or 'User'
        return names

    @api.model
    def _v2_history_payload(self, page, more, author_names, parent_by_id=None):
        parent_by_id = parent_by_id or {}
        own_ids = [message.id for message in page if message.author_user_id.id == self.env.uid]
        receipts = self._v2_receipt_summaries(own_ids)
        def message_data(message):
            row = {
                'id': message.id,
                'author_user_id': message.author_user_id.id,
                'author_name': author_names[message.author_user_id.id],
                'text': message.text or '',
                'created_at': fields.Datetime.to_string(message.create_date),
            }
            if message.author_user_id.id == self.env.uid:
                summary = receipts[message.id]
                row['delivery_state'] = summary['state']
                row['read_at'] = summary['read_at']
            if (message.media_id and message.media_id.state == 'attached'
                    and message.media_id.message_id.id == message.id
                    and message.media_id.room_id.id == message.room_id.id
                    and message.media_id.company_id.id == message.company_id.id):
                row['media'] = self._v2_media_metadata(message.media_id)
            if message.reply_to_message_id:
                parent = parent_by_id.get(message.reply_to_message_id.id)
                if parent:
                    preview = ' '.join((parent.text or '').split())[:160]
                    # v2 clients require this published three-field reply shape.
                    # Media previews need a negotiated capability or a new API version.
                    row['reply'] = {
                        'id': parent.id,
                        'author_name': author_names[parent.author_user_id.id],
                        'text': preview,
                    }
                else:
                    row['reply'] = {'unavailable': True}
            return row
        return {
            'api_version': 2,
            'messages': [message_data(message) for message in reversed(page)],
            'next_before_id': page[-1].id if more else None,
        }

    @api.model
    def _v2_send(self, room_id, payload):
        self._require_bchat_permission('chat_send')
        return self._v2_send_normalized(room_id, v2_contracts.normalize_send(payload))

    @api.model
    def _v2_send_metadata_scope(self, room, member, normalized):
        """Additive metadata hook after current scope and replay checks."""
        return None

    @api.model
    def _v2_create_send_metadata(self, room, member, message, normalized, metadata):
        """Additive metadata must commit in the message's existing savepoint."""
        return None

    @api.model
    def _v2_send_normalized(self, room_id, normalized):
        self._require_bchat_permission('chat_send')
        with self.env.cr.savepoint():
            room = self._v2_lock_room(room_id, mutate=True)
            member = self._v2_current_member(room)
            if normalized['membership_id'] != member.id:
                raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
            parent_id = normalized.get('reply_to_message_id')
            if parent_id is not None:
                parent = self.env['baseer.bchat.message'].sudo().browse(parent_id).exists()
                if (not parent or parent.room_id.id != room.id
                        or parent.company_id.id != room.company_id.id
                        or parent.id <= member.joined_after_message_id):
                    raise AccessError(self.env._('The referenced BChat message is unavailable.'))
            media = None
            if 'media_id' in normalized:
                self._require_media_right('upload')
                media = self.env['baseer.bchat.media'].sudo().browse(normalized['media_id']).exists()
                if (not media or media.author_user_id.id != self.env.uid
                        or media.room_id.id != room.id
                        or media.company_id.id != room.company_id.id
                        or media.membership_id.id != member.id
                        or not (media.attachment_id or media.document_file_id)):
                    raise AccessError(self.env._('This media is unavailable.'))
                normalized['media_sha256'] = media.sha256
            digest = v2_contracts.digest(room.id, normalized)
            messages = self.env['baseer.bchat.message'].sudo()
            existing = messages.search([
                ('author_user_id', '=', self.env.uid),
                ('client_uuid', '=', normalized['client_uuid']),
            ], limit=1)
            if existing:
                return self._v2_replay(room, member, normalized, digest, existing)
            if media and (media.state != 'staged' or media.message_id):
                raise ProtocolError('media_already_sent', 'This media was already sent.', 409)
            metadata = self._v2_send_metadata_scope(room, member, normalized)
            effective = self._v2_document_selection(room, normalized, media) if media else normalized
            vals = {
                'room_id': room.id, 'company_id': room.company_id.id,
                'membership_id': member.id, 'author_user_id': self.env.uid,
                'client_uuid': normalized['client_uuid'],
                'payload_digest': digest, 'text': normalized['text'],
            }
            if parent_id is not None:
                vals['reply_to_message_id'] = parent_id
            if media:
                vals['media_id'] = media.id
            try:
                with self.env.cr.savepoint():
                    created = messages._create_verified(vals, _SERVICE_TOKEN)
                    if media:
                        self._v2_finalize_document(room, member, media, created, effective)
                        media._write_verified({
                            'state': 'attached', 'message_id': created.id,
                            'document_type': effective['document_type'],
                            'document_policy_version': effective['policy_version'],
                        }, _MEDIA_TOKEN)
                    self._v2_create_send_metadata(room, member, created, normalized, metadata)
            except UniqueViolation as error:
                if error.diag.constraint_name != 'baseer_bchat_message_user_uuid_unique':
                    raise
                # A different room can win the same user-wide UUID. Under
                # Odoo's REPEATABLE READ the original snapshot cannot see it.
                return self._v2_fresh_replay(room.id, member.id, normalized, digest)
            members = self.env['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', room.id), ('active', '=', True),
            ], order='user_id, id', limit=2049)
            if len(members) > 2048:
                raise ProtocolError('too_many_members', 'This room exceeds its supported member limit.', 409)
            members = members.filtered(lambda row: row.user_id.active
                                      and row.company_id in row.user_id.company_ids
                                      and row.user_id._bchat_effective_permissions()['chat_view'])
            recipients = members.filtered(lambda row: row.user_id.id != self.env.uid)
            if recipients:
                self.env['baseer.bchat.message.receipt'].sudo()._create_verified([{
                    'message_id': created.id, 'membership_id': row.id,
                    'recipient_user_id': row.user_id.id,
                    'company_id': room.company_id.id,
                } for row in recipients], _RECEIPT_TOKEN)
                # Delivery remains best-effort: an FCM failure must never roll
                # back an already verified, immutable message or its receipts.
                self._message_queue_push(created, recipients)
            self._change_publish(members.mapped('user_id').ids, 'message',
                                 room_id=room.id, message_id=created.id,
                                 company_id=room.company_id.id,
                                 memberships={row.user_id.id: row.id for row in members})
            return v2_contracts.ack(room.id, normalized, created.id)

    @api.model
    def _v2_message(self, room_id, message_id):
        self._require_bchat_permission('chat_view')
        room = self._v2_lock_room(room_id)
        member = self._v2_current_member(room)
        message = self.env['baseer.bchat.message'].sudo().browse(
            positive_id(message_id, 'message_id')).exists()
        if (not message or message.room_id.id != room.id
                or message.company_id.id != room.company_id.id
                or message.id <= member.joined_after_message_id):
            raise AccessError(self.env._('This BChat message is unavailable.'))
        authors = self._v2_author_names([message])
        payload = self._v2_history_payload([message], False, authors)
        return {'api_version': 2, 'room_id': room.id, 'membership_id': member.id,
                'message': payload['messages'][0]}

    @api.model
    def _v2_receipt_ack(self, room_id, message_id, kind, membership_id=_ACK_MEMBERSHIP_ABSENT):
        self._require_bchat_permission('chat_view')
        if kind not in ('delivered', 'read'):
            raise ProtocolError('invalid_payload', 'Unknown BChat receipt kind.')
        message_id = positive_id(message_id, 'message_id')
        with self.env.cr.savepoint():
            room = self._v2_lock_room(room_id)
            member = self._v2_current_member(room)
            if membership_id is not _ACK_MEMBERSHIP_ABSENT:
                if type(membership_id) is not int or not 0 < membership_id <= 2147483647:
                    raise ProtocolError('invalid_payload', 'A positive membership ID is required.')
                if membership_id != member.id:
                    raise ProtocolError('membership_changed', 'The membership period changed.', 409)
            message = self.env['baseer.bchat.message'].sudo().browse(message_id).exists()
            if (not message or message.room_id.id != room.id
                    or message.company_id.id != room.company_id.id
                    or message.id <= member.joined_after_message_id
                    or message.author_user_id.id == self.env.uid):
                raise AccessError(self.env._('This BChat message is unavailable.'))
            receipt = self.env['baseer.bchat.message.receipt'].sudo().search([
                ('message_id', '=', message.id), ('membership_id', '=', member.id),
                ('recipient_user_id', '=', self.env.uid),
            ], limit=1)
            if not receipt:
                raise ProtocolError('receipt_unavailable', 'This message predates receipt tracking.', 409)
            self.env.cr.execute('''
                SELECT id FROM baseer_bchat_message_receipt WHERE id = %s FOR UPDATE
            ''', [receipt.id])
            receipt.invalidate_recordset(['delivered_at', 'read_at'])
            now = fields.Datetime.now()
            values = {}
            if not receipt.delivered_at:
                values['delivered_at'] = now
            if kind == 'read' and not receipt.read_at:
                values['read_at'] = now
            if values:
                receipt._write_verified(values, _RECEIPT_TOKEN)
                author_member = self.env['baseer.bchat.membership'].sudo().search([
                    ('room_id', '=', room.id), ('user_id', '=', message.author_user_id.id),
                    ('active', '=', True),
                ], limit=1)
                if author_member and author_member.id == message.membership_id.id:
                    self._change_publish([message.author_user_id.id], 'receipt',
                                         room_id=room.id, message_id=message.id,
                                         company_id=room.company_id.id,
                                         memberships={message.author_user_id.id: author_member.id})
            # The reader does not receive its own receipt hint.  Return the
            # authoritative post-ack room count so a client never has to
            # hide a badge optimistically or infer it from cached history.
            self.env.cr.execute('''
                SELECT COUNT(*)
                FROM baseer_bchat_message_receipt AS receipt
                JOIN baseer_bchat_message AS candidate ON candidate.id = receipt.message_id
                WHERE receipt.membership_id = %s
                  AND receipt.recipient_user_id = %s
                  AND receipt.read_at IS NULL
                  AND candidate.room_id = %s
                  AND candidate.company_id = %s
                  AND candidate.id > %s
            ''', [member.id, self.env.uid, room.id, room.company_id.id,
                  member.joined_after_message_id])
            unread_count = self.env.cr.fetchone()[0]
            self.env.cr.execute('''
                SELECT COALESCE(MAX(id), 0)
                FROM baseer_bchat_message
                WHERE room_id = %s AND id > %s
            ''', [room.id, member.joined_after_message_id])
            last_message_id = self.env.cr.fetchone()[0]
            return {'api_version': 2, 'message_id': message.id,
                    'delivered_at': fields.Datetime.to_string(receipt.delivered_at),
                    'read_at': fields.Datetime.to_string(receipt.read_at) if receipt.read_at else None,
                    'unread_count': unread_count,
                    'last_message_id': last_message_id,
                    'replayed': not bool(values)}

    @api.model
    def _v2_documents_enabled(self):
        """A bridge addon may enable document storage; the base module never does."""
        return False

    @api.model
    def _v2_document_selection(self, room, normalized, media):
        selected = dict(normalized)
        policy = room.invoice_policy
        version = room.invoice_policy_version
        requested = selected.get('document_type')
        # Only images and PDFs can enter invoice intake; audio and office files
        # always stay in the room's ordinary-media area, even in default rooms.
        invoice_eligible = media.kind == 'image' or (
            media.kind == 'file' and media.mime == 'application/pdf')
        if not invoice_eligible and (requested not in (None, 'other') or 'invoice_case_id' in selected):
            raise ProtocolError('unsupported_document_type',
                                'This media type cannot be an invoice or receipt.', 415)
        if policy == 'off':
            if requested not in (None, 'other') or 'invoice_case_id' in selected:
                raise ProtocolError('document_policy_changed', 'This room does not accept invoices.', 409)
            if 'policy_version' in selected and selected['policy_version'] != version:
                raise ProtocolError('document_policy_changed', 'The room document policy changed.', 409)
            selected['document_type'] = 'other'
            selected['policy_version'] = version
            return selected
        if not self._v2_documents_enabled():
            raise ProtocolError('documents_unavailable', 'Document storage is not available.', 409)
        if requested is None or selected.get('policy_version') != version:
            raise ProtocolError('document_policy_changed', 'The room document policy changed.', 409)
        if requested == 'other' and 'invoice_case_id' in selected:
            raise ProtocolError('invalid_payload', 'Ordinary media cannot refer to an invoice case.')
        if requested == 'payment_receipt' and 'invoice_case_id' not in selected:
            raise ProtocolError('invoice_case_required', 'A payment receipt needs an invoice case.', 409)
        return selected

    @api.model
    def _v2_finalize_document(self, room, member, media, message, normalized):
        """Called inside the message savepoint by the optional DMS bridge."""
        return None

    @api.model
    def _v2_fresh_replay(self, room_id, membership_id, normalized, digest):
        with self.env.registry.cursor() as fresh_cr:
            fresh = api.Environment(fresh_cr, self.env.uid, {
                'allowed_company_ids': [self.env['baseer.bchat.room'].sudo().browse(room_id).company_id.id],
            })
            user = fresh.user
            if fresh.su or not user.active or not user._is_internal():
                raise AccessError(self.env._('This room is unavailable.'))
            fresh['baseer.bchat.service']._require_bchat_permission('chat_send')
            if 'media_id' in normalized:
                fresh['baseer.bchat.service']._require_media_right('upload')
            room = fresh['baseer.bchat.room'].sudo().browse(room_id)
            if not room.exists() or room.company_id not in user.company_ids:
                raise AccessError(self.env._('This room is unavailable.'))
            member = fresh['baseer.bchat.membership'].sudo().search([
                ('room_id', '=', room_id), ('user_id', '=', user.id), ('active', '=', True),
            ], limit=1)
            if not member or member.id != membership_id:
                raise ProtocolError('membership_changed', 'The room membership period changed.', 409)
            existing = fresh['baseer.bchat.message'].sudo().search([
                ('author_user_id', '=', user.id),
                ('client_uuid', '=', normalized['client_uuid']),
            ], limit=1)
            if not existing:
                raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation.', 409)
            return self._v2_replay(room, member, normalized, digest, existing)

    @api.model
    def _v2_replay(self, room, member, normalized, digest, existing):
        if (existing.room_id.id != room.id or existing.membership_id.id != member.id
                or existing.id <= member.joined_after_message_id
                or existing.payload_digest != digest
                or existing.media_id.id != normalized.get('media_id', 0)):
            raise ProtocolError('idempotency_conflict', 'The UUID belongs to another operation or membership period.', 409)
        return v2_contracts.ack(room.id, normalized, existing.id)
