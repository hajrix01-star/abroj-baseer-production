"""Read-only metadata accounting, never physical measurement or retention."""
from collections import defaultdict
import re


def lifecycle_class(record):
    if record.get('held'):
        return 'protected_hold'
    if not record.get('res_id'):
        return 'unlinked_unconfirmed'
    model = record.get('res_model')
    if model == 'account.move':
        return 'accounting_original'
    if model == 'baseer.invoice.intake':
        return 'private_review_snapshot'
    if model == 'discuss.channel' and record.get('purpose') == 'invoice_intake':
        return 'invoice_candidate'
    if model == 'project.task':
        return 'work_order'
    if model == 'baseer.procurement.request':
        return 'procurement_record'
    if model == 'discuss.channel' and record.get('purpose') in ('chat', 'tasks', 'procurement', 'sales'):
        return 'ordinary_chat'
    return 'unclassified'


def inventory(records, company_id, *, complete):
    if type(company_id) is not int or company_id <= 0 or type(complete) is not bool:
        raise ValueError('Explicit company and completeness are required')
    classes = defaultdict(lambda: {'count': 0, 'logical_bytes': 0})
    media = defaultdict(lambda: {'count': 0, 'logical_bytes': 0})
    seen, sizes, decisions = set(), {}, []
    total = conflicts = 0
    for record in records:
        if type(record.get('company_id')) is not int or record['company_id'] != company_id:
            raise ValueError('Cross-company or ambiguous metadata')
        ident, size = record.get('attachment_id'), record.get('size')
        if type(ident) is not int or ident <= 0 or ident in seen:
            raise ValueError('Distinct positive attachment IDs are required')
        if type(size) is not int or size < 0:
            raise ValueError('Nonnegative metadata size is required')
        seen.add(ident)
        category = lifecycle_class(record)
        mime = record.get('mimetype') or ''
        kind = ('image' if mime.startswith('image/') else 'audio' if mime.startswith('audio/') else
                'video' if mime.startswith('video/') else 'pdf' if mime == 'application/pdf' else 'other')
        for bucket in (classes[category], media[kind]):
            bucket['count'] += 1
            bucket['logical_bytes'] += size
        total += size
        checksum = record.get('checksum') or ''
        key = checksum if re.fullmatch('[0-9a-f]{40}', checksum) else 'unknown:%s' % ident
        if key in sizes and sizes[key] != size:
            conflicts += 1
            key = 'conflict:%s' % ident
        sizes[key] = size
        decisions.append({'attachment_id': ident, 'lifecycle_class': category, 'action': 'preserve',
                          'reason': 'held' if category == 'protected_hold' else 'retention_policy_pending', 'deletion_eligible': False})
    return {'company_id': company_id, 'scope': 'caller_authorized_attachment_metadata', 'complete': complete,
            'attachment_count': len(seen), 'logical_bytes': total, 'unique_content_bytes_estimate': sum(sizes.values()),
            'metadata_digest_size_conflicts': conflicts, 'physical_filestore_bytes': None, 'external_object_bytes': None,
            'database_bytes': None, 'backup_bytes': None, 'free_disk_bytes': None, 'growth_bytes': None, 'reclaimable_bytes': None,
            'by_lifecycle_class': dict(classes), 'by_media_type': dict(media),
            'dry_run': {'mutations': 0, 'delete_candidates': [], 'decisions': decisions},
            'limits': ['Metadata is not physical disk measurement.', 'Existing checksums do not verify current bytes.',
                       'No retention, quota, cleanup, backup or provider is configured.']}
