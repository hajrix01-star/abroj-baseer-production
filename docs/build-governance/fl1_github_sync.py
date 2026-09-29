"""Prepare accepted FL1 source for GitHub only after successful MAIN publication.

Run `python docs/build-governance/fl1_github_sync.py prepare` after FL1 MAIN
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

from fl1_release import verify_candidate, review_go
from live1_export import known_secrets


ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / '.local-backups/live1-20260909/repository'
RELEASE = ROOT / 'docs/releases/2026-09-10-financial-register'
PREVIOUS_PUBLIC_COMMIT = '4124200cad7d53fab8eab228752d25e3e79f2da9'
PREVIOUS_SOURCE_COMMIT = '6104fc8e6f1d24b3e842f2b43bd9f410840d7759'
ADDON_PREFIX = 'custom_addons/baseer_financial_register/'


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
    review_go(RELEASE / 'PREDEPLOY-GO.md', candidate['commit'])
    runtime = read_json(RELEASE / 'runtime.json')
    preservation = read_json(RELEASE / 'main-preservation.json')
    require(runtime.get('candidate') == candidate['commit'] and runtime.get('http') == 200
            and runtime.get('installed') == 'installed|19.0.1.0.0'
            and runtime.get('no_pending_modules') is True,
            'Successful FL1 MAIN runtime verification is required before GitHub preparation')
    require(preservation.get('candidate') == candidate['commit']
            and preservation.get('existing_rows_exact') is True
            and preservation.get('existing_columns_exact') is True
            and preservation.get('existing_user_memberships_exact') is True
            and preservation.get('existing_user_presets_exact') is True
            and preservation.get('no_automatic_role_assignments') is True,
            'FL1 MAIN preservation evidence must pass')
    require(git('remote', 'get-url', 'origin').rstrip('/').removesuffix('.git')
            == 'https://github.com/hajrix01-star/Odoo-Baseer', 'Unexpected GitHub destination')
    require(git('branch', '--show-current') == 'main', 'Expected the publication main branch')
    require(git('rev-parse', 'HEAD') == PREVIOUS_PUBLIC_COMMIT, 'Prior public commit changed')
    require(not git('status', '--porcelain'), 'Publication checkout must be clean before preparation')

    old = read_json(REPO / 'release-source.json')
    require(old['source_commit'] == candidate['parent'] == PREVIOUS_SOURCE_COMMIT,
            'Expected the accepted AR2 source baseline')
    require(old['odoo_image'] == candidate['image'] and old['odoo_major'] == 19,
            'Odoo runtime image or major version changed')
    require(len(old['files']) == 1156 and set(old['files']).issubset(candidate['files']),
            'All 1156 accepted source files must remain present')
    require(source_inventory(REPO) == set(old['files']), 'Previous source checkout inventory differs')
    changed = {rel for rel, sha in candidate['files'].items() if old['files'].get(rel) != sha}
    require(changed and changed == set(candidate['changed_files'])
            and changed == set(candidate['files']) - set(old['files'])
            and all(rel.startswith(ADDON_PREFIX) for rel in changed),
            'Only the new financial register addon may be added')
    require(all(candidate['files'].get(rel) == sha for rel, sha in old['files'].items())
            and len(candidate['files']) - len(changed) == 1156,
            'All 1156 accepted source files must remain byte-identical')

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
    old_modules = {PurePosixPath(rel).parts[1] for rel in old['files']
                   if rel.startswith('custom_addons/') and rel.endswith('/__manifest__.py')}
    require(len(old_modules) == 17 and len(modules) == 18
            and modules - old_modules == {'baseer_financial_register'},
            'Expected the 17 accepted custom modules plus the financial register')
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
    print(f'PREPARED FL1 {candidate["commit"]}: {len(changed)} new register files, '
          f'1156 preserved files; {len(modules)} custom modules. No commit or push performed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare',))
    parser.parse_args()
    prepare()
