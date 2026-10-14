"""Owner-authorized synthetic QA fixtures; never run against production."""
import base64
import json
from pathlib import Path

from odoo.exceptions import AccessError
import odoo.addons.dms as dms_package

assert env.cr.dbname == 'baseer_live_qa_clean_20260928'
env.cr.rollback()
owner = env.ref('base.user_admin')
assert owner.id == 2 and owner.active
for suffix in ('private_storage','private_directory','private_file','private_group','private_share','private_attachment'):
    rule = env.ref('baseer_dms_trial.' + suffix)
    assert rule.active and not rule['groups']
companies = owner.company_ids.sorted('id')[:2]
assert len(companies) == 2
scope = dict(allowed_company_ids=companies.ids, lang='ar_001')
oe = env['dms.file'].with_user(owner).with_context(**scope).env
assert not oe.su
prefix = 'QA DMS 20261014'
assert not env['dms.storage'].search([('name','=like',prefix+'%')])
payload = base64.b64encode((Path(dms_package.__file__).parent / 'test' / 'document01.pdf').read_bytes())
assert 0 < len(base64.b64decode(payload)) < 1048576
group = oe['dms.access.group'].create({
    'name': prefix+' — Owner only','perm_create':True,'perm_write':True,'perm_unlink':True,
    'explicit_user_ids':[(6,0,[owner.id])],
})
# Native permission queries use stored group membership via SQL. Match the
# separate UI group-save transaction while keeping this synthetic setup atomic.
env.flush_all()
storages, directories, files = [], [], []
for company in companies:
    storage = oe['dms.storage'].create({
        'name':prefix+' — '+company.name, 'company_id':company.id,'save_type':'file',
        'model_ids':[(5,0,0)],'include_message_attachments':False,
        'inherit_access_from_parent_record':False,
    })
    root = oe['dms.directory'].create({
        'name':prefix+' — '+company.name,'is_root_directory':True,
        'storage_id':storage.id,'group_ids':[(6,0,group.ids)],
    })
    storages.append(storage)
    directories.append(root)
    for label in ('عقود تجريبية','رخص تجريبية'):
        folder = oe['dms.directory'].create({
            'name':label,'parent_id':root.id,'is_root_directory':False,
        })
        document = oe['dms.file'].create({
            'name':'QA — '+label+' — ملف وهمي.pdf','directory_id':folder.id,'content':payload,
        })
        assert document.company_id == company
        assert document.content == payload and not document.attachment_id
        assert not document.access_token and not folder.access_token and not root.access_token
        directories.append(folder)
        files.append(document)

def denied(operation):
    try:
        with env.cr.savepoint():
            operation()
            raise AssertionError('Nonowner unexpectedly accessed private DMS')
    except AccessError:
        pass

class RollbackProbe(Exception):
    pass

try:
    with env.cr.savepoint():
        manager = env['res.users'].with_context(no_reset_password=True).create({
            'name':prefix+' temporary access check','login':'qa-dms-check-20261014',
            'active':False,'company_id':companies[0].id,'company_ids':[(6,0,companies.ids)],
            'group_ids':[(6,0,[env.ref('dms.group_dms_manager').id])],
        })
        # Prove confinement even with native group permission and both companies.
        group.write({'explicit_user_ids':[(4,manager.id)]})
        env.flush_all()
        for record in (storages[0],directories[0],files[0],group):
            restricted = record.with_user(manager).with_context(**scope)
            assert not restricted.search([('id','=',record.id)])
            denied(lambda r=restricted:r.read(['name']))
            denied(lambda r=restricted:r.write({'name':'FORBIDDEN'}))
            denied(lambda r=restricted:r.unlink())
        foreign = files[0].with_user(manager).with_context(**scope)
        denied(lambda:foreign.read(['content']))
        denied(lambda:foreign.write({'directory_id':directories[-1].id}))
        denied(lambda:foreign.write({'access_token':'INVALID-PROBE'}))
        denied(lambda:oe['dms.file'].with_user(manager).create({
            'name':'FORBIDDEN.pdf','directory_id':directories[1].id,'content':payload,
        }))
        attachment = env['ir.attachment'].search([
            ('res_model','=','dms.file'),('res_field','=','content_file'),('res_id','=',files[0].id),
        ])
        assert len(attachment) == 1
        for user in (manager,env.ref('base.public_user')):
            denied(lambda u=user:attachment.with_user(u).read(['datas']))
        denied(lambda:env['wizard.dms.share'].with_user(manager).create({
            'res_model':'dms.file','res_id':files[0].id,
        }))
        assert not files[0].access_token
        duplicate = oe['dms.file'].create({
            'name':'QA temporary duplicate.pdf','directory_id':directories[1].id,'content':payload,
        })
        assert duplicate.checksum == files[0].checksum
        print('LOGICAL_DUPLICATE_ALLOWED=YES_KNOWN_LIMITATION')
        raise RollbackProbe()
except RollbackProbe:
    pass

assert group.explicit_user_ids.ids == [owner.id]
assert not env['res.users'].with_context(active_test=False).search([('login','=','qa-dms-check-20261014')])
assert all(not f.access_token for f in files)
env.cr.commit()
print('DMS_PRIVATE_QA=PASS_OWNER_ONLY_SYNTHETIC')
print('DMS_TRIAL_IDS='+json.dumps({
    'company_ids':companies.ids,'owner_id':owner.id,'group_id':group.id,
    'storage_ids':[s.id for s in storages],'directory_ids':[d.id for d in directories],
    'file_ids':[f.id for f in files],
},ensure_ascii=False))
