"""FL3 release on frozen IC2 R2; source-only delta, protected MAIN upgrade."""
import argparse
import ast
import importlib
import json
import shutil
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

import environment_backups as b
from ic2_release import (require, read_json, review_go, inventory, verify_ui_evidence,
                         read_sql, columns, projection, security_memberships,
                         installed_versions, role_assignments, verify_mounts)

MODULE = 'baseer_financial_register'
VERSION = '19.0.1.2.0'
OLD_VERSION = '19.0.1.1.0'
OLD_RELEASE = '2026-09-10-financial-source-lifecycle-r2'
NEW_RELEASE = '2026-09-10-financial-register-sales'
OLD_FOLDER = 'financial-source-lifecycle-20260910-r2'
NEW_FOLDER = 'financial-register-sales-20260910'
PARENT = '3d96581c2eef324df3b5ed69f7ba526bb37035fc'
PREFIX = 'custom_addons/' + MODULE + '/'
OUT = b.ROOT / 'docs/releases' / NEW_RELEASE
BACK = b.ROOT / '.local-backups' / NEW_FOLDER
SOURCE = BACK / 'candidate'
OLD = b.ROOT / '.local-backups' / OLD_FOLDER / 'candidate'
EVIDENCE = ('fl3-invoice-checks.json', 'fl3-cash-checks.json', 'fl3-pos-checks.json', 'fl3-edge-checks.json', 'fl3b-platform-checks.json', 'fl3-readonly-smoke.json', 'fl3-ui-checks.json')
SUPPORTING = ('FL3-REVIEW.md', 'FINANCIAL-REGISTER-SALES.md', 'fl3_release.py',
              'fl3_github_sync.py', 'fl3_regression.py', 'fl3_pos_checks.py', 'fl3_edge_checks.py',
              'fl3b-platform-checks.py', 'fl3_ui_finalize.py', 'fl3_smoke.py', 'fl3_main_smoke_run.py')


def freeze():
    previous = read_json(b.ROOT / 'docs/releases' / OLD_RELEASE / 'candidate.json')
    require(previous['commit'] == PARENT and len(previous['files']) == 1181, 'IC2 R2 baseline differs')
    require(inventory(OLD) == previous['files'], 'Frozen parent differs')
    current = {PREFIX + rel: sha for rel, sha in inventory(b.ROOT / 'custom_addons' / MODULE).items()}
    files = dict(previous['files'])
    require({r for r in files if r.startswith(PREFIX)}.issubset(current), 'Unreviewed source deletion')
    files.update(current)
    manifest = ast.literal_eval((b.ROOT / PREFIX / '__manifest__.py').read_text(encoding='utf8'))
    old_manifest = ast.literal_eval((OLD / PREFIX / '__manifest__.py').read_text(encoding='utf8'))
    require(manifest['version'] == VERSION and manifest['depends'] == old_manifest['depends'], 'Version/dependencies differ')
    changed = sorted(r for r, sha in files.items() if previous['files'].get(r) != sha)
    require(changed and all(r.startswith(PREFIX) for r in changed), 'Unexpected source changes')
    evidence = {name: read_json(b.ROOT / 'docs/build-governance' / name) for name in EVIDENCE}
    require(all(e['status'] == 'PASS' for e in evidence.values()), 'Acceptance incomplete')
    require(all(evidence[name].get('rollback') is True for name in EVIDENCE[:-1]), 'Financial fixtures not rolled back')
    require(evidence['fl3-ui-checks.json']['source_sha256'] == current, 'Final UI source differs')
    ui_files = verify_ui_evidence(b.ROOT / 'docs/build-governance/fl3-ui', evidence['fl3-ui-checks.json'])
    review_go(b.ROOT / 'docs/build-governance/FL3-REVIEW.md')
    require(not SOURCE.exists() and not (OUT / 'candidate.json').exists(), 'Frozen candidate already exists')
    SOURCE.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for rel, sha in files.items():
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and path.parts[0] in ('custom_addons', 'third_party_addons'), 'Unsafe source path')
        src = b.ROOT / rel if rel.startswith(PREFIX) else OLD / rel
        require(b.sha(src) == sha, 'Source changed during freeze')
        if rel in changed:
            if src.suffix == '.py': ast.parse(src.read_text(encoding='utf8'), filename=rel)
            elif src.suffix == '.xml': ET.parse(src)
        target = SOURCE / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    require(inventory(SOURCE) == files, 'Frozen inventory differs')
    for command in (['git', 'init', '--initial-branch=codex/financial-register-sales'],
                    ['git', 'config', 'core.autocrlf', 'false'],
                    ['git', 'add', '--', 'custom_addons', 'third_party_addons'],
                    ['git', '-c', 'user.name=Codex Release', '-c', 'user.email=codex-release@localhost',
                     '-c', 'core.autocrlf=false', 'commit', '-m', 'Include POS sales and platform incoming in financial operations']):
        b.run(command, cwd=SOURCE, capture_output=True)
    commit = b.run(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, capture_output=True, text=True).stdout.strip()
    archive = OUT / 'candidate-source.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(files): z.write(SOURCE / rel, rel)
    candidate = dict(commit=commit, parent=PARENT, module=MODULE, module_version=VERSION,
                     image=previous['image'], source_directory=str(SOURCE), files=files,
                     changed_files=changed, archive_sha256=b.sha(archive))
    b.save(OUT / 'candidate.json', candidate)
    for name in EVIDENCE:
        shutil.copy2(b.ROOT / 'docs/build-governance' / name, OUT / name)
    for name in SUPPORTING:
        shutil.copy2(b.ROOT / 'docs/build-governance' / name, OUT / name)
    for rel in ui_files:
        dst = OUT / 'fl3-ui' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b.ROOT / 'docs/build-governance/fl3-ui' / rel, dst)
    candidate['evidence_sha256'] = {name: b.sha(OUT / name) for name in EVIDENCE + SUPPORTING}
    b.save(OUT / 'candidate.json', candidate)
    print('FROZEN', commit, len(files), 'files', len(changed), 'changed')


def verify_candidate():
    candidate = read_json(OUT / 'candidate.json')
    previous = read_json(b.ROOT / 'docs/releases' / OLD_RELEASE / 'candidate.json')
    require(previous['commit'] == PARENT and len(previous['files']) == 1181, 'Parent identity differs')
    require(candidate['parent'] == PARENT and candidate['module_version'] == VERSION
            and candidate['module'] == MODULE and candidate['image'] == previous['image'], 'Candidate identity differs')
    require(set(previous['files']).issubset(candidate['files']) and all(
        sha == candidate['files'][rel] for rel, sha in previous['files'].items() if not rel.startswith(PREFIX)), 'Unrelated source changed')
    changed = sorted(rel for rel, sha in candidate['files'].items() if previous['files'].get(rel) != sha)
    require(changed == candidate['changed_files'] and changed and all(rel.startswith(PREFIX) for rel in changed), 'Delta differs')
    require(set(candidate['evidence_sha256']) == set(EVIDENCE + SUPPORTING), 'Evidence inventory differs')
    require(all(b.sha(OUT / name) == sha for name, sha in candidate['evidence_sha256'].items()), 'Acceptance evidence changed')
    require(inventory(SOURCE) == candidate['files'], 'Frozen source differs')
    require(b.sha(OUT / 'candidate-source.zip') == candidate['archive_sha256'], 'Archive differs')
    for name in EVIDENCE:
        evidence = read_json(OUT / name)
        require(evidence['status'] == 'PASS', 'Acceptance no longer passes')
        if name != EVIDENCE[-1]: require(evidence['rollback'] is True, 'Rollback missing')
    ui = read_json(OUT / EVIDENCE[-1])
    require(ui['source_sha256'] == {r: sha for r, sha in candidate['files'].items() if r.startswith(PREFIX)}, 'UI source binding differs')
    verify_ui_evidence(OUT / 'fl3-ui', ui)
    review_go(OUT / 'FL3-REVIEW.md')
    return candidate


def publish():
    candidate = verify_candidate()
    review_go(OUT / 'PREDEPLOY-GO.md', candidate['commit'])
    require(not (OUT / 'main-backup.json').exists(), 'Publication already started; inspect before recovery')
    verify_mounts(b.inspect(b.MAIN_CONTAINER), OLD_FOLDER, candidate['image'])
    versions = installed_versions()
    require(versions.get(MODULE) == OLD_VERSION and versions.get('baseer_financial_correction') == '19.0.1.1.0'
            and versions.get('baseer_pos_summary') == '19.0.1.5.1', 'MAIN baseline versions differ')
    require(read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')") == '0', 'Pending module operations')
    old_prefix = './.local-backups/' + OLD_FOLDER + '/candidate/'
    new_prefix = './.local-backups/' + NEW_FOLDER + '/candidate/'
    compose = {name: (b.ROOT / name).read_text(encoding='utf8') for name in ('compose.yaml', 'compose.main-release.yaml')}
    require(all(s.count(old_prefix) == 3 for s in compose.values()), 'MAIN compose baseline differs')
    helper = b.ROOT / 'docs/build-governance/environment_backups.py'
    helper_text = helper.read_text(encoding='utf8')
    require(OLD_RELEASE in helper_text and OLD_FOLDER in helper_text, 'Backup mapping differs')
    b.BACK.mkdir(parents=True, exist_ok=True)
    lock = b.BACK / 'maintenance.lock'
    with lock.open('x', encoding='utf8') as f: f.write('FL3 publish ' + candidate['commit'])
    try:
        b.run(['docker', 'stop', '--timeout', '60', b.MAIN_CONTAINER], capture_output=True)
        b.save(OUT / 'main-backup.json', b.backup(b.MAIN))
        b.save(OUT / 'installed-versions-before.json', versions)
        cols = columns()
        require(len(cols) == 373, 'Expected accepted IC2 R2 protected tables')
        before = projection(cols)
        memberships, roles = security_memberships(), role_assignments()
        b.save(OUT / 'protected-columns.json', cols)
        b.save(OUT / 'protected-before.json', before)
        b.save(OUT / 'security-memberships-before.json', memberships)
        b.save(OUT / 'role-assignments-before.json', roles)
        for name, content in compose.items():
            shutil.copy2(b.ROOT / name, BACK / (name + '.before'))
            (b.ROOT / name).write_text(content.replace(old_prefix, new_prefix), encoding='utf8')
        with (OUT / 'main-install.log').open('wb') as log:
            b.run(['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml',
                   'run', '--rm', '--no-deps', '-T', 'odoo', 'odoo', '--config=/etc/odoo/odoo.local.conf',
                   '--addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19',
                   '--database=' + b.MAIN, '--update=' + MODULE, '--stop-after-init', '--no-http',
                   '--max-cron-threads=0', '--i18n-overwrite'], cwd=b.ROOT, stdout=log, stderr=log)
        require(columns() == cols, 'Unexpected schema change; MAIN remains stopped')
        after = projection(cols)
        b.save(OUT / 'protected-after.json', after)
        require(before == after, 'Business data changed; MAIN remains stopped for investigation')
        memberships_after, roles_after = security_memberships(), role_assignments()
        b.save(OUT / 'security-memberships-after.json', memberships_after)
        b.save(OUT / 'role-assignments-after.json', roles_after)
        require(memberships == memberships_after and roles == roles_after, 'Security changed')
        require(installed_versions() == dict(versions, **{MODULE: VERSION}), 'Unrelated module change')
        b.save(OUT / 'main-preservation.json', dict(candidate=candidate['commit'], protected_tables=len(cols),
            existing_columns_exact=True, existing_rows_exact=True, existing_user_memberships_exact=True,
            existing_user_presets_exact=True, existing_module_versions_exact=True))
        shutil.copy2(helper, BACK / 'environment_backups.py.before')
        helper.write_text(helper_text.replace(OLD_RELEASE, NEW_RELEASE).replace(OLD_FOLDER, NEW_FOLDER), encoding='utf8')
        importlib.reload(b)
        b.save(OUT / 'post-release-backup.json', b.backup(b.MAIN))
        b.run(['docker', 'compose', '-p', 'baseer_odoo_dev', '-f', 'compose.yaml', 'up', '-d', '--no-deps', 'odoo'], cwd=b.ROOT, capture_output=True)
        for _ in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=3) as r:
                    if r.status == 200: break
            except OSError: pass
            time.sleep(2)
        else: raise RuntimeError('MAIN healthcheck failed')
        verify_runtime()
    finally:
        lock.unlink()


def verify_runtime():
    candidate = verify_candidate()
    runtime = b.inspect(b.MAIN_CONTAINER)
    verify_mounts(runtime, NEW_FOLDER, candidate['image'])
    require(installed_versions() == dict(read_json(OUT / 'installed-versions-before.json'), **{MODULE: VERSION}), 'Version drift')
    require(read_sql("SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove')") == '0', 'Pending modules')
    with urllib.request.urlopen('http://127.0.0.1:18069/web/login', timeout=5) as response:
        require(response.status == 200, 'MAIN unavailable')
    b.save(OUT / 'runtime.json', dict(candidate=candidate['commit'], http=200,
        installed='installed|' + VERSION, no_pending_modules=True, mounts=runtime['Mounts'], image=candidate['image']))
    print('MAIN VERIFIED', candidate['commit'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'publish', 'verify-runtime'))
    args = parser.parse_args()
    {'freeze': freeze, 'publish': publish, 'verify-runtime': verify_runtime}[args.command]()
