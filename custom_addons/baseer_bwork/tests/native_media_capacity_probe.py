"""Disposable-database capacity probe for native BWork media.

Run this only with ``odoo shell`` against a database whose name starts with
``baseer_bwork_native_media_test_``.  It commits its synthetic fixtures so
separate cursors and two concurrent upload workers can exercise the same
transaction boundaries as the capability endpoint.  It is deliberately not
imported by the Odoo test suite.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from threading import Barrier
from uuid import uuid4

from PIL import Image
from psycopg2.extensions import TransactionRollbackError

from odoo import Command, api
from odoo.service.model import retrying


_PREFIX = 'baseer_bwork_native_media_test_'
_MIB = 1024 * 1024


def _metadata(membership_id, raw, *, kind, mime, name):
    return {
        'api_version': 2,
        'membership_id': membership_id,
        'upload_uuid': str(uuid4()),
        'kind': kind,
        'mime': mime,
        'size': len(raw),
        'sha256': sha256(raw).hexdigest(),
        'name': name,
    }


def _exact_size_png(size):
    """A valid, tiny PNG padded to the image contract's exact 5 MiB edge."""
    stream = BytesIO()
    Image.new('RGB', (2, 2), (15, 75, 135)).save(stream, format='PNG')
    payload = stream.getvalue()
    if len(payload) > size:
        raise AssertionError('image fixture exceeded its intended capacity')
    return payload + (b'\0' * (size - len(payload)))


def run(env):
    if not env.cr.dbname.startswith(_PREFIX):
        raise RuntimeError('Refusing native-media capacity probe outside a disposable database')

    company = env.company
    suffix = uuid4().hex
    admin = env.ref('base.user_admin')
    admin.sudo().write({
        'group_ids': [Command.link(env.ref('baseer_bwork.group_bwork_manager').id)],
    })
    users = env['res.users'].with_context(no_reset_password=True)
    manager = users.create({
        'name': 'Native upload capacity manager %s' % suffix,
        'login': 'native-capacity-manager-%s' % suffix,
        'company_id': company.id,
        'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('baseer_bwork.group_bwork_manager').id])],
    })
    colleague = users.create({
        'name': 'Native upload capacity colleague %s' % suffix,
        'login': 'native-capacity-colleague-%s' % suffix,
        'company_id': company.id,
        'company_ids': [Command.set(company.ids)],
        'group_ids': [Command.set([env.ref('base.group_user').id])],
    })
    room = env['baseer.bwork.room'].with_user(admin).with_company(company).create({
        'name': 'Native capacity room %s' % suffix,
        'company_id': company.id,
    })
    members = env['baseer.bwork.membership'].with_user(admin).with_company(company)
    manager_member = members.create({'room_id': room.id, 'user_id': manager.id})
    colleague_member = members.create({'room_id': room.id, 'user_id': colleague.id})
    ids = (company.id, room.id, manager.id, colleague.id, manager_member.id, colleague_member.id)
    env.cr.commit()

    company_id, room_id, manager_id, colleague_id, manager_member_id, colleague_member_id = ids
    registry = env.registry

    def upload(user_id, membership_id, raw, *, kind, mime, name, synchronize=None):
        with registry.cursor() as cursor:
            scoped = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            metadata = _metadata(membership_id, raw, kind=kind, mime=mime, name=name)
            issued = scoped['baseer.bwork.service']._v2_issue_mobile_upload_grant(room_id, metadata)
            cursor.commit()
        if synchronize:
            synchronize.wait(timeout=30)
        with registry.cursor() as cursor:
            scoped = api.Environment(cursor, user_id, {'allowed_company_ids': [company_id]})
            def redeem():
                grants = scoped['baseer.bwork.mobile.upload.grant'].sudo()
                claim = grants._claim_capability(issued['grant_id'], issued['secret'])
                assert claim['claimed'], claim
                try:
                    result = scoped['baseer.bwork.service']._v2_mobile_upload_from_capability(claim, raw)
                    return grants._resolve_claimed_capability(claim, result['media_id'])
                except TransactionRollbackError:
                    grants._release_claimed_capability(claim)
                    raise

            resolved = retrying(redeem, scoped)
            cursor.commit()
            assert resolved['state'] == 'resolved', resolved
            return {'bytes': len(raw), 'media_id': resolved['media_id']}

    one_byte = upload(manager_id, manager_member_id, b'x', kind='file', mime='text/plain', name='one.txt')
    five_mib = upload(manager_id, manager_member_id, _exact_size_png(5 * _MIB),
                      kind='image', mime='image/png', name='edge.png')
    ten_mib = upload(manager_id, manager_member_id, b'x' * (10 * _MIB),
                     kind='file', mime='text/plain', name='edge.txt')

    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(upload, manager_id, manager_member_id, b'ab', kind='file',
                        mime='text/plain', name='parallel-a.txt', synchronize=barrier),
            pool.submit(upload, colleague_id, colleague_member_id, b'cd', kind='file',
                        mime='text/plain', name='parallel-b.txt', synchronize=barrier),
        ]
        parallel = [future.result(timeout=90) for future in futures]
    assert len({result['media_id'] for result in parallel}) == 2, parallel

    return {
        'one_byte': one_byte,
        'five_mib': five_mib,
        'ten_mib': ten_mib,
        'parallel': parallel,
        'disposable_database': env.cr.dbname,
    }


if __name__ == '__main__':
    print(run(env))  # noqa: F821 - Odoo shell injects env.
