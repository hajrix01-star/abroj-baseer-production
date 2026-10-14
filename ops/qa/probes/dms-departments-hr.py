"""Owner-authorized QA directory configuration; no historical HR import."""
import json

assert env.cr.dbname == 'baseer_live_qa_clean_20260928'
env.cr.rollback()
owner = env.ref('base.user_admin')
assert owner.id == 2 and owner.active
for suffix in ('private_storage', 'private_directory', 'private_file',
               'private_group', 'private_share', 'private_attachment'):
    assert env.ref('baseer_dms_trial.' + suffix).active
assert env['ir.module.module'].sudo().search_count([
    ('name', '=', 'baseer_dms_departments'), ('state', '=', 'installed')
]) == 1
companies = env['res.company'].sudo().search([]).sorted('id')
assert companies.ids == [1, 2, 3, 54, 55, 56, 57], 'Refuse unexpected company-scope changes'
assert set(companies.ids) <= set(owner.company_ids.ids), 'Do not grant new company access'
scoped = companies.with_user(owner).with_context(
    allowed_company_ids=companies.ids, lang='ar_001')
assert not scoped.env.su
env.cr.execute('SELECT checksum, MD5(ROW_TO_JSON(a)::text) FROM ir_attachment a WHERE id=5840')
original = env.cr.fetchone()
assert original == ('74d64754a79987d2ccce685c06ef553cd8930931',
                    'f5c49b2644b09fd6a4edbec26dc7c988'), 'Original changed: investigate, do not overwrite'
link = scoped.env['dms.file'].browse(10)
assert link.exists() and link.bill_attachment_id.id == 5840
old_bill_leaf = link.directory_id.id
file_count = scoped.env['dms.file'].search_count([])
hr_attachment_count = scoped.env['ir.attachment'].search_count([
    ('res_model', 'in', ['hr.employee', 'hr.version'])])
group = scoped.env['dms.access.group'].browse(2)
assert group.exists() and group.explicit_user_ids == owner
trees = scoped._setup_dms_departments(access_group=group)
assert set(trees) == set(companies.ids)
env.flush_all()
first_count = scoped.env['dms.directory'].search_count([])
assert scoped._setup_dms_departments(access_group=group) == trees
assert scoped.env['dms.directory'].search_count([]) == first_count
for company_id, tree in trees.items():
    assert set(tree) == {'root', 'purchases', 'bills', 'purchase_orders',
                         'hr', 'employees', 'sales', 'administration'}
    dirs = scoped.env['dms.directory'].browse(list(tree.values()))
    assert len(dirs) == 8 and dirs.exists() == dirs
    assert set(dirs.company_id.ids) == {company_id}
    assert not any(dirs.mapped('access_token'))
    assert dirs.storage_id.company_id.id == company_id
    assert not dirs.storage_id.model_ids
    assert not dirs.storage_id.inherit_access_from_parent_record
    for key, label in {'purchases': 'المشتريات', 'bills': 'فواتير الموردين',
                       'purchase_orders': 'أوامر الشراء', 'hr': 'الموارد البشرية',
                       'employees': 'الموظفون', 'sales': 'المبيعات',
                       'administration': 'الإدارة'}.items():
        assert scoped.env['dms.directory'].browse(tree[key]).name == label, 'Arabic folder label missing'
    assert not scoped.env['dms.directory'].browse(tree['root']).parent_id
    for child, parent in [('purchases', 'root'), ('hr', 'root'), ('sales', 'root'),
                          ('administration', 'root'), ('bills', 'purchases'),
                          ('purchase_orders', 'purchases'), ('employees', 'hr')]:
        assert scoped.env['dms.directory'].browse(tree[child]).parent_id.id == tree[parent]
    company = scoped.browse(company_id)
    assert company.dms_bill_root_id.id == tree['bills']
    assert company.dms_purchase_order_root_id.id == tree['purchase_orders']
    assert company.dms_hr_root_id.id == tree['hr']
    assert company.dms_employee_root_id.id == tree['employees']
assert link.id == 10 and link.bill_attachment_id.id == 5840
assert link.directory_id.id == old_bill_leaf
env.cr.execute('SELECT checksum, MD5(ROW_TO_JSON(a)::text) FROM ir_attachment a WHERE id=5840')
assert env.cr.fetchone() == original
assert scoped.env['dms.file'].search_count([('bill_attachment_id', '=', 5840)]) == 1
assert scoped.env['dms.file'].search_count([]) == file_count
assert scoped.env['ir.attachment'].search_count([
    ('res_model', 'in', ['hr.employee', 'hr.version'])]) == hr_attachment_count
env.cr.commit()
print('DMS_DEPARTMENTS_QA=PASS', json.dumps(trees, sort_keys=True))
print('SETUP=IDEMPOTENT; ORIGINAL5840=UNCHANGED; BACKFILL=NONE; USER_GRANTS=NONE; LIVE=UNTOUCHED')
