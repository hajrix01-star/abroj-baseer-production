"""Exact display identities/privacy, no Odoo/FCM or device assertions."""
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('bchat_presentation',
    Path(__file__).resolve().parents[1] / 'notification_presentation.py')
presentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presentation)
ACCOUNT = '00000000-0000-4000-8000-000000000001'


class NotificationPresentationCase(unittest.TestCase):
    def payload(self, **extra):
        values = dict(account=ACCOUNT, event=41, company=7, room=19, membership=23,
                      message=31, author=13, sent_at_ms=1792238400123, mode='none',
                      sender='Private sender', title='Private room', is_group=True,
                      text='Private message', attachment=False)
        values.update(extra)
        return presentation.chat_data(**values)

    def test_known_hash_vector_matches_android_contract(self):
        self.assertEqual(presentation.presentation_keys(ACCOUNT, 7, 19, 23, 31, 13), {
            'presentation_v': '1',
            'room_key': 'f204a34ee307e864d1c4db0eb36ab19cb8fca1e92d3d7da323773f7444fb6218',
            'message_key': '3372699fdfc412a5fda6fbbbd3dd5e71343a3b80906fbabf30ff44aac30275d1',
            'sender_key': '2650f7f5758fa2582e2dbde9cfa8596e63625cdac6458718a3cc564f06f5977c'})

    def test_each_scope_component_separates_keys(self):
        base = presentation.presentation_keys(ACCOUNT, 7, 19, 23, 31, 13)
        for args in ((ACCOUNT.replace('001', '002'), 7, 19, 23, 31, 13),
                     (ACCOUNT, 8, 19, 23, 31, 13), (ACCOUNT, 7, 20, 23, 31, 13),
                     (ACCOUNT, 7, 19, 24, 31, 13)):
            self.assertNotEqual(base['room_key'], presentation.presentation_keys(*args)['room_key'])
        self.assertNotEqual(base['message_key'], presentation.presentation_keys(ACCOUNT, 7, 19, 23, 32, 13)['message_key'])
        self.assertNotEqual(base['sender_key'], presentation.presentation_keys(ACCOUNT, 7, 19, 23, 31, 14)['sender_key'])

    def test_rejects_local_scope_hash_uuid_coercion_and_bad_record_types(self):
        for account in ('a' * 64, ACCOUNT.upper().replace('0000', 'AAAA', 1),
                        '00000000-0000-1000-8000-000000000001', None):
            with self.assertRaises(ValueError): self.payload(account=account)
        for field in ('event', 'company', 'room', 'membership', 'message', 'author'):
            for value in (True, 1.0, '1', 0, -1, 2147483648):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.payload(**{field: value})

    def test_none_contains_no_names_text_title_sender_or_group_flag(self):
        data = self.payload()
        self.assertEqual(set(data), {'account_key', 'kind', 'event_id', 'presentation_v',
                                     'room_key', 'message_key', 'sent_at_ms'})
        self.assertNotIn('Private', json.dumps(data))
        self.assertTrue(all(type(value) is str for value in data.values()))

    def test_sender_does_not_leak_group_title_flag_or_message(self):
        data = self.payload(mode='sender')
        self.assertEqual(set(data) - set(self.payload()), {'sender_key', 'sender_name'})
        self.assertEqual(data['sender_name'], 'Private sender')
        self.assertNotIn('Private room', json.dumps(data))
        self.assertNotIn('Private message', json.dumps(data))

    def test_full_and_attachment_shapes_are_mutually_exclusive(self):
        full = self.payload(mode='full')
        self.assertEqual((full['is_group'], full['conversation_title'], full['message_preview']),
                         ('true', 'Private room', 'Private message'))
        self.assertNotIn('message_preview_kind', full)
        media = self.payload(mode='full', text='', attachment=True, is_group=False)
        self.assertEqual(media['message_preview_kind'], 'attachment')
        self.assertEqual(media['is_group'], 'false')
        self.assertNotIn('message_preview', media)

    def test_retry_uses_message_creation_not_new_event_time_for_identity(self):
        first, retried = self.payload(mode='full'), self.payload(event=42, mode='full')
        for field in ('room_key', 'message_key', 'sender_key', 'sent_at_ms'):
            self.assertEqual(first[field], retried[field])

    def test_utf8_and_control_cleaning_remain_bounded(self):
        data = self.payload(mode='full', text='\u202e<b>سلام</b>\n\x00😀' * 100,
                            title='😀' * 300, sender='😀' * 300)
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()),
                             presentation.MAX_DATA_BYTES)
        self.assertNotIn('\u202e', data.get('message_preview', ''))
        self.assertNotIn('<b>', data.get('message_preview', ''))
        self.assertLessEqual(len(data.get('message_preview', '')), 160)
        self.assertLessEqual(len(data.get('sender_name', '')), 120)

    def test_bound_includes_json_escaping_not_character_count(self):
        data = self.payload(mode='full', text='"' * 160, title='\\' * 120, sender='\\' * 120)
        self.assertLessEqual(len(json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()), 3072)
        self.assertEqual(data['message_preview'], '"' * 160)

    def test_strict_timestamp_mode_and_flags(self):
        for at in (0, -1, True, 1.5, '1', presentation.MAX_SENT_AT_MS + 1):
            with self.assertRaises(ValueError): self.payload(sent_at_ms=at)
        for extra in ({'mode': 'unknown'}, {'is_group': 'true'}, {'attachment': 1}):
            with self.assertRaises(ValueError): self.payload(**extra)
        self.assertEqual(self.payload(sent_at_ms=presentation.MAX_SENT_AT_MS)['sent_at_ms'], '253402300799999')


if __name__ == '__main__':
    unittest.main()
