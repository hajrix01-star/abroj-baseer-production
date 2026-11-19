"""Run only inside a QA Odoo shell; compile real assets and roll back ORM work."""
import hashlib
import json
from odoo.tools import file_open
from odoo.tools.js_transpiler import transpile_javascript

assert env.cr.dbname.startswith('baseer_qa_'), 'QA database required'
module = env['ir.module.module'].search([('name', '=', 'baseer_pos_cache_resilience')])
assert module.state == 'installed' and module.installed_version == '19.0.1.0.2'
assets = env['ir.asset']
paths = [item[0].lstrip('/') for item in assets._get_asset_paths('point_of_sale._assets_pos', assets._get_asset_params())]
original = 'point_of_sale/static/src/app/components/loader/critical_pos_error/reset_local_data.js'
replacement = 'baseer_pos_cache_resilience/static/src/reset_local_data.js'
assert original not in paths and paths.count(replacement) == 1
compiled = {}
for name in ('receipt_number_reservation', 'receipt_storage', 'reset_local_data'):
    path = f'baseer_pos_cache_resilience/static/src/{name}.js'
    assert path in paths
    with file_open(path) as source:
        compiled[name] = transpile_javascript('/' + path, source.read())
assert '__exports.resetLocalData' in compiled['reset_local_data']
assert '@point_of_sale/app/components/loader/critical_pos_error/reset_local_data' in compiled['reset_local_data']
assert '@baseer_pos_cache_resilience/receipt_storage' in compiled['reset_local_data']
bundle = env['ir.qweb']._get_asset_bundle('point_of_sale._assets_pos', css=False, js=True)
content = ';\n'.join(asset.minify() for asset in bundle.javascripts)
assert 'removeUsedNumbers' in content
assert 'unique_device_identifier' in content
assert 'baseer_pos_cache_resilience/reset_local_data' in content
print('POS_NUM1_QA_ACCEPTANCE=' + json.dumps({
    'database': env.cr.dbname, 'module': module.installed_version,
    'asset_paths': len(paths), 'js_assets_compiled': len(bundle.javascripts),
    'minified_bytes': len(content.encode()), 'bundle_sha256': hashlib.sha256(content.encode()).hexdigest(),
    'original_reset_removed': True, 'replacement_count': paths.count(replacement),
    'named_alias': True, 'orm_rolled_back': True,
    'compiled': compiled,
}))
env.cr.rollback()
