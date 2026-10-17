"""Pure C32 digest/normalization regression; not an ORM acceptance test."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'bchat_message_social_contract_package'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package
for name in ('contracts', 'v2_contracts', 'social_contracts'):
    spec = importlib.util.spec_from_file_location('%s.%s' % (PACKAGE, name), ROOT / ('%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
v2 = sys.modules[PACKAGE + '.v2_contracts']
social = sys.modules[PACKAGE + '.social_contracts']


class MessageSocialContractCase(unittest.TestCase):
    def payload(self, **extra):
        return {'api_version': 2, 'membership_id': 7, 'client_uuid': str(uuid4()), 'text': 'Same exact text', **extra}

    def test_no_mentions_and_empty_mentions_preserve_legacy_digest_exactly(self):
        payload = self.payload()
        old = v2.normalize_send(payload)
        for candidate in (payload, {**payload, 'mention_user_ids': []}):
            new = v2.normalize_social_send(candidate)
            self.assertEqual(new, old)
            self.assertEqual(v2.digest(9, new), v2.digest(9, old))

    def test_explicit_mentions_are_sorted_and_bind_the_digest(self):
        payload = self.payload()
        normalized = v2.normalize_social_send({**payload, 'mention_user_ids': [13, 11]})
        self.assertEqual(normalized['mention_user_ids'], [11, 13])
        self.assertEqual(v2.digest(9, normalized), v2.digest(9,
            v2.normalize_social_send({**payload, 'mention_user_ids': [11, 13]})))
        self.assertNotEqual(v2.digest(9, normalized), v2.digest(9, v2.normalize_send(payload)))
        self.assertNotEqual(v2.digest(9, normalized), v2.digest(9, {**normalized, 'mention_user_ids': [11]}))

    def test_mentions_are_strict_bounded_unique_ids_and_legacy_route_stays_strict(self):
        for ids in (None, True, '11', [True], [1, 1], [0], list(range(1, 51))):
            with self.subTest(ids=ids), self.assertRaises(v2.ProtocolError):
                v2.normalize_social_send(self.payload(mention_user_ids=ids))
        with self.assertRaises(v2.ProtocolError):
            v2.normalize_send(self.payload(mention_user_ids=[]))

    def test_empty_mentions_preserve_media_reply_document_digest(self):
        payload = self.payload(text='', media_id=19, reply_to_message_id=5,
                               document_type='invoice', policy_version=2)
        old = v2.normalize_send(payload)
        old['media_sha256'] = 'a' * 64
        new = v2.normalize_social_send({**payload, 'mention_user_ids': []})
        new['media_sha256'] = 'a' * 64
        self.assertEqual(v2.digest(9, old), v2.digest(9, new))

    def test_projection_revision_zero_is_valid_but_bool_and_negative_are_not(self):
        payload = {'api_version': 2, 'membership_id': 9, 'client_uuid': str(uuid4()),
                   'expected_revision': 0, 'emoji': '👍'}
        self.assertEqual(social.mutation(payload, 'emoji')['expected_revision'], 0)
        for value in (-1, True, 2147483647):
            with self.subTest(value=value), self.assertRaises(v2.ProtocolError):
                social.mutation({**payload, 'expected_revision': value}, 'emoji')

    def test_exact_emoji_and_saved_boolean_schema(self):
        common = {'api_version': 2, 'membership_id': 9, 'client_uuid': str(uuid4()), 'expected_revision': 0}
        for value in social.EMOJIS + (None,):
            self.assertEqual(social.mutation({**common, 'emoji': value}, 'emoji')['emoji'], value)
        for value in ('❤', '❤️x', '', True, 1, ['👍']):
            with self.subTest(value=value), self.assertRaises(v2.ProtocolError):
                social.mutation({**common, 'emoji': value}, 'emoji')
        self.assertTrue(social.mutation({**common, 'saved': True}, 'saved')['saved'])
        with self.assertRaises(v2.ProtocolError):
            social.mutation({**common, 'saved': 1}, 'saved')


if __name__ == '__main__':
    unittest.main()
