"""Prepare accepted AR1 source for GitHub only after successful MAIN publication.

Run `python docs/build-governance/ar1_github_sync.py prepare` after AR1 MAIN
verification. This copies reviewed source and refreshes the existing source-lock
metadata/README, then runs ops/verify_source.py. It never stages, commits or pushes.
No database, filestore, operational evidence or credentials are exported.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from ar1_release import verify_candidate, review_go
from live1_export import known_secrets


ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / '.local-backups/live1-20260909/repository'
RELEASE = ROOT / 'docs/releases/2026-09-10-access-roles'
PREVIOUS_PUBLIC_COMMIT = '429b8a9856fbb6e790d49e2a0c7a827b20d5bdfe'
PREVIOUS_SOURCE_COMMIT = '4cd5ee3e9bebcd1d85bda2723bf2781643f7f3e7'
EXPECTED_SOURCE_COMMIT = '98f9d4dced9f7a844d3d44e63f89d8d0d8218664'
ADDON_PREFIX = 'custom_addons/baseer_access_roles/'
PAYROLL_PATCHES = {
    'custom_addons/baseer_payroll/__manifest__.py',
    'custom_addons/baseer_payroll/models/common.py',
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def source_inventory(root):
    return {path.relative_to(root).as_posix() for folder in ('custom_addons', 'third_party_addons')
            for path in (root / folder).rglob('*') if path.is_file()
            and '__pycache__' not in path.parts and path.suffix != '.pyc'}


def prepare():
    candidate = verify_candidate()
    require(candidate['commit'] == EXPECTED_SOURCE_COMMIT, 'Expected the reviewed AR1 frozen commit')
    review_go(RELEASE / 'PREDEPLOY-GO.md', candidate['commit'])
    runtime = read_json(RELEASE / 'runtime.json')
    preservation = read_json(RELEASE / 'main-preservation.json')
    require(runtime.get('candidate') == candidate['commit'] and runtime.get('http') == 200
            and runtime.get('installed') == 'installed|19.0.1.0.0'
            and runtime.get('no_pending_modules') is True,
            'Successful AR1 MAIN runtime verification is required before GitHub preparation')
    require(preservation.get('candidate') == candidate['commit']
            and preservation.get('existing_rows_exact') is True
            and preservation.get('existing_columns_exact') is True
            and preservation.get('existing_user_memberships_exact') is True
            and preservation.get('no_existing_user_presets') is True,
            'AR1 MAIN preservation evidence must pass')
    require(git('remote', 'get-url', 'origin').rstrip('/').removesuffix('.git')
            == 'https://github.com/hajrix01-star/Odoo-Baseer', 'Unexpected GitHub destination')
    require(git('branch', '--show-current') == 'main', 'Expected the publication main branch')
    require(git('rev-parse', 'HEAD') == PREVIOUS_PUBLIC_COMMIT, 'Prior public commit changed')
    require(not git('status', '--porcelain'), 'Publication checkout must be clean before preparation')

    old = read_json(REPO / 'release-source.json')
    require(old['source_commit'] == candidate['parent'] == PREVIOUS_SOURCE_COMMIT,
            'Expected the accepted SD7 source baseline')
    require(old['odoo_image'] == candidate['image'] and old['odoo_major'] == 19,
            'Odoo runtime image or major version changed')
    require(len(old['files']) == 1135 and set(old['files']).issubset(candidate['files']),
            'The 1135 previous source files must remain present')
    require(source_inventory(REPO) == set(old['files']), 'Previous source checkout inventory differs')
    changed = {rel for rel, sha in candidate['files'].items() if old['files'].get(rel) != sha}
    added = set(candidate['files']) - set(old['files'])
    require(added and all(rel.startswith(ADDON_PREFIX) for rel in added),
            'Only the new access-role addon may add source files')
    require(changed - added == PAYROLL_PATCHES and changed == set(candidate['changed_files']),
            'Only the two reviewed payroll patches and new role addon may change')
    require(len(candidate['files']) - len(changed) == 1133,
            'All 1133 unrelated source files must remain unchanged')

    source = Path(candidate['source_directory']).resolve()
    secrets = known_secrets()
    payload = {}
    for rel, sha in candidate['files'].items():
        parts = PurePosixPath(rel)
        require(not parts.is_absolute() and '..' not in parts.parts and '\\' not in rel
                and parts.parts[0] in ('custom_addons', 'third_party_addons'), 'Unsafe source path')
        path = source.joinpath(*parts.parts)
        require(not path.is_symlink() and path.resolve().is_relative_to(source), 'Unsafe frozen file: ' + rel)
        data = path.read_bytes()
        require(digest(data) == sha, 'Frozen source differs: ' + rel)
        if rel in old['files']:
            require(digest((REPO / rel).read_bytes()) == old['files'][rel], 'Previous checkout differs: ' + rel)
        if rel in changed:
            require(not any(secret in data for secret in secrets), 'Credential match in source: ' + rel)
            require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data),
                    'Private key in source: ' + rel)
            payload[rel] = data

    # release-source.json is this repository's existing SHA256 source lock.
    payload['release-source.json'] = (json.dumps({
        'source_commit': candidate['commit'], 'odoo_image': candidate['image'],
        'odoo_major': 19, 'files': candidate['files'],
    }, indent=2) + '\n').encode('utf-8')
    modules = {PurePosixPath(rel).parts[1] for rel in candidate['files']
               if rel.startswith('custom_addons/') and rel.endswith('/__manifest__.py')}
    readme = (REPO / 'README.md').read_text(encoding='utf-8-sig')
    readme, module_count = re.subn(r'^يشمل\s*\d+\s*موديولًا مخصصًا.*$',
        f'يشمل {len(modules)} موديولًا مخصصًا والاعتماديات الخارجية الموجودة في الإصدار المعتمد.', readme, flags=re.M)
    readme, source_count = re.subn(r'^- أصل المصدر: `[^`]+`\.$',
        '- أصل المصدر: `' + candidate['commit'] + '`.', readme, flags=re.M)
    readme, inventory_count = re.subn(r'^- ملف `release-source\.json` يثبت\s*\d+\s*ملفًا.*$',
        f'- ملف `release-source.json` يثبت {len(candidate["files"])} ملفًا ببصمات SHA256 وصورة Odoo المعتمدة.', readme, flags=re.M)
    require((module_count, source_count, inventory_count) == (1, 1, 1),
            'README source metadata format changed; inspect before rewriting')
    payload['README.md'] = readme.encode('utf-8')

    # Complete every destination/hash/secret/release check before writing the checkout.
    for rel in payload:
        destination = REPO / rel
        require(destination.resolve().is_relative_to(REPO.resolve()) and not destination.is_symlink(),
                'Unsafe export destination: ' + rel)
    for rel, data in payload.items():
        destination = REPO / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    subprocess.run([sys.executable, 'ops/verify_source.py'], cwd=REPO, check=True)
    require(source_inventory(REPO) == set(candidate['files']), 'Prepared source inventory differs')
    print(f'PREPARED AR1 {candidate["commit"]}: {len(added)} new files, 2 payroll patches, '
          f'1133 preserved files; {len(modules)} custom modules. No commit or push performed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare',))
    parser.parse_args()
    prepare()
