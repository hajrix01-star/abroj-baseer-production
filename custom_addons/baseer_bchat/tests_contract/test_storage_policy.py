import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('storage_policy', Path(__file__).resolve().parents[1] / 'storage_policy.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def row(**changes):
    return dict({'attachment_id': 1, 'company_id': 2, 'res_model': 'discuss.channel', 'res_id': 3,
                 'size': 100, 'mimetype': 'image/png', 'checksum': 'a' * 40, 'purpose': 'chat', 'held': False}, **changes)


class StorageTests(unittest.TestCase):
    def test_logical_bytes_are_not_physical_disk(self):
        value = p.inventory([row(), row(attachment_id=2)], 2, complete=True)
        self.assertEqual(value['logical_bytes'], 200)
        self.assertEqual(value['unique_content_bytes_estimate'], 100)
        for key in ('physical_filestore_bytes', 'external_object_bytes', 'database_bytes', 'backup_bytes', 'free_disk_bytes', 'growth_bytes', 'reclaimable_bytes'):
            self.assertIsNone(value[key])

    def test_missing_hash_does_not_assume_deduplication(self):
        value = p.inventory([row(checksum=''), row(attachment_id=2, checksum='')], 2, complete=False)
        self.assertEqual(value['unique_content_bytes_estimate'], 200)
        self.assertFalse(value['complete'])

    def test_hash_size_conflict_is_visible(self):
        value = p.inventory([row(), row(attachment_id=2, size=200)], 2, complete=True)
        self.assertEqual(value['metadata_digest_size_conflicts'], 1)
        self.assertEqual(value['unique_content_bytes_estimate'], 300)

    def test_every_class_preserves_every_file(self):
        examples = [row(held=True), row(res_model='account.move'), row(res_model='baseer.invoice.intake'), row(purpose='invoice_intake'),
                    row(res_model='project.task'), row(res_model='baseer.procurement.request'), row(), row(res_id=0), row(res_model='unknown')]
        rows = [dict(value, attachment_id=i+1) for i, value in enumerate(examples)]
        value = p.inventory(rows, 2, complete=True)
        self.assertEqual(len(value['by_lifecycle_class']), 9)
        self.assertEqual(value['dry_run']['mutations'], 0)
        self.assertEqual(value['dry_run']['delete_candidates'], [])
        self.assertTrue(all(row['action'] == 'preserve' and not row['deletion_eligible'] for row in value['dry_run']['decisions']))

    def test_age_and_name_never_authorize_cleanup(self):
        value = p.inventory([row(res_id=0, age_days=999999, name='temporary', retention_days=1)], 2, complete=True)
        self.assertEqual(value['dry_run']['delete_candidates'], [])
        self.assertEqual(value['dry_run']['decisions'][0]['lifecycle_class'], 'unlinked_unconfirmed')

    def test_company_binding_is_strict(self):
        for company in (3, None, True):
            with self.assertRaises(ValueError):
                p.inventory([row(company_id=company)], 2, complete=True)

    def test_duplicate_identity_or_bad_sizes_rejected(self):
        with self.assertRaises(ValueError):
            p.inventory([row(), row()], 2, complete=True)
        for size in (-1, True, '100', 1.0):
            with self.assertRaises(ValueError):
                p.inventory([row(size=size)], 2, complete=True)

    def test_media_totals_reconcile(self):
        rows = [row(attachment_id=i, mimetype=mime, size=i, checksum='') for i, mime in enumerate(
            ['image/png', 'audio/aac', 'video/mp4', 'application/pdf', 'application/octet-stream'], 1)]
        value = p.inventory(rows, 2, complete=True)
        self.assertEqual(value['logical_bytes'], 15)
        self.assertEqual(set(value['by_media_type']), {'image', 'audio', 'video', 'pdf', 'other'})
        self.assertEqual(sum(group['logical_bytes'] for group in value['by_media_type'].values()), 15)

    def test_names_paths_tokens_and_content_never_returned(self):
        value = repr(p.inventory([row(name='PRIVATE', raw='SECRET', access_token='TOKEN', path='/filestore/FILE')], 2, complete=True))
        for marker in ('PRIVATE', 'SECRET', 'TOKEN', '/filestore/FILE'):
            self.assertNotIn(marker, value)
