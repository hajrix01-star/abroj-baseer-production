"""Fresh tests for reconstructed bytes; no Odoo or external data."""
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import unittest
from uuid import uuid1, uuid4

spec = importlib.util.spec_from_file_location('business_policy', Path(__file__).resolve().parents[1] / 'business_contracts.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def task(**changes):
    value = {'project_id': 1, 'title': 'مهمة اختبار', 'description': 'Private draft', 'assignee_user_ids': [3, 2]}
    return dict(value, **changes)


def request(**changes):
    value = {'warehouse_id': 1, 'representative_partner_id': 2, 'lines': [{'option_id': 3, 'quantity': '2.50'}]}
    return dict(value, **changes)


def attachment(**changes):
    return dict({'attachment_id': 1, 'company_id': 2, 'res_model': 'discuss.channel', 'res_id': 3,
                 'checksum': 'a' * 40, 'sha256': 'b' * 64, 'mimetype': 'application/pdf', 'size': 42,
                 'purpose': 'invoice_intake'}, **changes)


class BusinessTests(unittest.TestCase):
    def test_record_identity_is_strict(self):
        for value in (True, False, '1', 0, -1, 1.0, 2 ** 31, None):
            with self.subTest(value=value), self.assertRaises(p.BusinessRejected):
                p.record_id(value)
        self.assertEqual(p.record_id(2147483647), 2147483647)

    def test_expected_revision_is_not_coerced(self):
        self.assertEqual(p.version(0), 0)
        for value in (True, -1, '0', 2 ** 31):
            with self.assertRaises(p.BusinessRejected):
                p.version(value)

    def test_uuid_is_canonical_v4(self):
        ident = str(uuid4())
        self.assertEqual(p.uuid4(ident.upper()), ident)
        for value in (str(uuid1()), uuid4().hex, 1, None, 'x' * 36):
            with self.assertRaises(p.BusinessRejected):
                p.uuid4(value)

    def test_bilingual_task_and_empty_description(self):
        result = p.normalize_draft('task', task())
        self.assertEqual(result['assignee_user_ids'], [2, 3])
        self.assertEqual(result['title'], 'مهمة اختبار')
        self.assertEqual(p.normalize_draft('task', task(description=''))['description'], '')

    def test_private_text_is_not_interpreted_as_html(self):
        value = '<img src=x onerror=alert(1)>'
        self.assertEqual(p.normalize_draft('task', task(description=value))['description'], value)

    def test_draft_never_accepts_server_scope_or_state(self):
        for key in ('company_id', 'owner_id', 'state', 'context', 'sudo', 'review_required', 'attachment_ids'):
            with self.subTest(key=key), self.assertRaises(p.BusinessRejected):
                p.normalize_draft('task', task(**{key: 1}))

    def test_assignees_are_distinct_bounded_records(self):
        for members in ([2, 2], [True], [-1], '3', list(range(1, 52))):
            with self.assertRaises(p.BusinessRejected):
                p.normalize_draft('task', task(assignee_user_ids=members))
        p.normalize_draft('task', task(assignee_user_ids=[]))

    def test_text_byte_limits_and_invalid_unicode(self):
        p.normalize_draft('task', task(title='ع' * 128))
        for value in ('ع' * 129, '\ud800', '', ' \n', 'x\x00y'):
            with self.assertRaises(p.BusinessRejected):
                p.normalize_draft('task', task(title=value))

    def test_exact_decimal_quantities(self):
        for before, after in [('1', '1.00'), ('01.2', '1.20'), ('999999999.99', '999999999.99')]:
            self.assertEqual(p.quantity(before), after)
        for value in (True, 1, 1.1, 'NaN', 'Infinity', '1e2', '-1', '0', '0.001', '1.001', ' 1', '1000000000'):
            with self.subTest(value=value), self.assertRaises(p.BusinessRejected):
                p.quantity(value)

    def test_canonical_catalog_sort(self):
        value = request(lines=[{'option_id': 5, 'quantity': '2'}, {'option_id': 3, 'quantity': '1.1'}])
        self.assertEqual(p.normalize_draft('procurement', value)['lines'],
                         [{'option_id': 3, 'quantity': '1.10'}, {'option_id': 5, 'quantity': '2.00'}])

    def test_no_price_payment_or_accounting_fields(self):
        for key in ('price', 'requested_price', 'paid', 'account_id', 'invoice_id', 'state'):
            with self.assertRaises(p.BusinessRejected):
                p.normalize_draft('procurement', request(lines=[{'option_id': 3, 'quantity': '1', key: 1}]))

    def test_cart_size_and_duplicate_options(self):
        for lines in ([], {}, [{'option_id': 3, 'quantity': '1'}] * 2,
                      [{'option_id': i, 'quantity': '1'} for i in range(1, 202)]):
            with self.assertRaises(p.BusinessRejected):
                p.normalize_draft('procurement', request(lines=lines))

    def test_receipt_never_means_payment(self):
        for state in ('draft', 'sent', 'received', 'purchased', 'cancel'):
            self.assertEqual(p.procurement_status(state)['payment_status'], 'not_established')
        self.assertEqual(p.procurement_status('purchased')['quantity_status'], 'quantity_receipt_completed')
        with self.assertRaises(p.BusinessRejected):
            p.procurement_status('paid')

    def test_unknown_operation_kind_is_rejected(self):
        for kind in ('invoice', 'account.move', 'payment', ''):
            with self.assertRaises(p.BusinessRejected):
                p.normalize_draft(kind, {})

    def test_draft_digest_covers_all_identity_fields(self):
        value = p.draft_identity(1, 2, 'task', str(uuid4()), task())
        for key, changed in [('company_id', 2), ('binding_id', 3), ('kind', 'procurement'),
                             ('client_uuid', str(uuid4())), ('payload', task(title='Changed'))]:
            self.assertNotEqual(p.digest(value), p.digest(dict(value, **{key: changed})))

    def test_input_lists_are_not_modified(self):
        original = task()
        result = p.normalize_draft('task', original)
        result['assignee_user_ids'].append(4)
        self.assertEqual(original['assignee_user_ids'], [3, 2])

    def test_same_event_different_audience_conflicts(self):
        one = p.event_identity(1, 2, 'task_created', 'project.task', 3)
        two = dict(one, binding_id=4)
        self.assertEqual(p.event_key(one), p.event_key(two))
        with self.assertRaisesRegex(p.BusinessRejected, 'event_conflict'):
            p.require_same_event(one, two)
        p.require_same_event(one, dict(one))

    def test_event_id_and_company_are_distinct(self):
        one = p.event_identity(1, 2, 'pos_session_closed', 'pos.session', 3)
        for key in ('company_id', 'res_id'):
            self.assertNotEqual(p.event_key(one), p.event_key(dict(one, **{key: 9})))

    def test_native_event_model_is_allowlisted(self):
        for event, model in [('task_created', 'account.move'), ('procurement_submitted', 'project.task'), ('invoice_paid', 'account.move')]:
            with self.assertRaises(p.BusinessRejected):
                p.event_identity(1, 2, event, model, 3)

    def test_bounded_delivery_retry(self):
        now = datetime(2026, 1, 1)
        for attempt in range(1, 5):
            self.assertEqual(p.delivery_failure(attempt, now), {'state': 'retry', 'next_attempt_at': now + timedelta(minutes=2 ** (attempt - 1))})
        self.assertEqual(p.delivery_failure(5, now), {'state': 'failed', 'next_attempt_at': False})
        for value in (0, -1, True, 1.0):
            with self.assertRaises(p.BusinessRejected):
                p.delivery_failure(value, now)

    def test_unconfigured_task_review_completes_native_task(self):
        self.assertEqual(p.completion_transition(review_required=False, review_state='not_required', action='request', is_reviewer=False),
                         {'state': '1_done', 'review_state': 'not_required'})

    def test_configured_review_keeps_task_open_until_approval(self):
        self.assertEqual(p.completion_transition(review_required=True, review_state='not_requested', action='request', is_reviewer=False),
                         {'state': '01_in_progress', 'review_state': 'pending'})
        self.assertEqual(p.completion_transition(review_required=True, review_state='pending', action='approve', is_reviewer=True),
                         {'state': '1_done', 'review_state': 'approved'})

    def test_review_rejects_unassigned_or_unrequested_approval(self):
        for required, state, reviewer in [(True, 'pending', False), (True, 'not_requested', True), (False, 'not_required', True)]:
            with self.assertRaises(p.BusinessRejected):
                p.completion_transition(review_required=required, review_state=state, action='approve', is_reviewer=reviewer)

    def test_review_rejection_does_not_complete(self):
        self.assertEqual(p.completion_transition(review_required=True, review_state='pending', action='reject', is_reviewer=True),
                         {'state': '02_changes_requested', 'review_state': 'changes_requested'})

    def test_invalid_review_policy_is_not_coerced(self):
        for required, state in [(True, 'paid'), (1, 'pending')]:
            with self.assertRaises(p.BusinessRejected):
                p.completion_transition(review_required=required, review_state=state, action='request', is_reviewer=False)

    def test_attachment_contract_is_reference_only(self):
        self.assertEqual(p.canonical_attachment(attachment()), attachment())
        for key in ('raw', 'datas', 'public', 'access_token', 'delete_after', 'dms_file_id'):
            with self.assertRaises(p.BusinessRejected):
                p.canonical_attachment(attachment(**{key: True}))

    def test_attachment_ambiguity_and_invalid_hash_are_rejected(self):
        for key, value in [('company_id', None), ('res_id', 0), ('size', True), ('sha256', 'b' * 63),
                           ('checksum', 'A' * 40), ('purpose', 'infer_from_name'), ('res_model', 'dms.file')]:
            with self.subTest(key=key), self.assertRaises(p.BusinessRejected):
                p.canonical_attachment(attachment(**{key: value}))
