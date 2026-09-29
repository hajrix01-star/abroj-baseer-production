"""Prepare source-only FL2 publication after verified MAIN upgrade; never push."""
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from fl1_github_sync import REPO, git, require, read_json, digest, source_inventory
from live1_export import known_secrets
from fl2_release import verify_candidate, review_go, OUT

PREVIOUS_PUBLIC = 'de47b3f1fdc36a628580290c2ac6b9a55796f82d'
PREFIX = 'custom_addons/baseer_financial_register/'


def prepare():
    candidate = verify_candidate()
    review_go(OUT / 'PREDEPLOY-GO.md', candidate['commit'])
    runtime = read_json(OUT / 'runtime.json')
    preservation = read_json(OUT / 'main-preservation.json')
    require(runtime['candidate'] == candidate['commit'] and runtime['http'] == 200
            and runtime['installed'] == 'installed|19.0.1.1.0'
            and runtime['no_pending_modules'], 'MAIN upgrade has not passed')
    require(preservation['candidate'] == candidate['commit'] and all(preservation.get(key) is True
            for key in ('existing_rows_exact', 'existing_columns_exact',
                        'existing_user_memberships_exact', 'existing_user_presets_exact',
                        'existing_module_versions_exact')), 'MAIN data preservation must pass')
    require(git('remote', 'get-url', 'origin').rstrip('/').removesuffix('.git')
            == 'https://github.com/hajrix01-star/Odoo-Baseer', 'Wrong destination')
    require(git('branch', '--show-current') == 'main' and git('rev-parse', 'HEAD') == PREVIOUS_PUBLIC
            and not git('status', '--porcelain'), 'Publication checkout baseline differs')
    old = read_json(REPO / 'release-source.json')
    require(old['source_commit'] == candidate['parent']
            == '0a6246b7215caddf9e7b14ffe799f84ee03f8cd3', 'Wrong source baseline')
    require(old['odoo_image'] == candidate['image'] and old['odoo_major'] == 19, 'Runtime changed')
    require(len(old['files']) == 1166 and set(old['files']).issubset(candidate['files'])
            and source_inventory(REPO) == set(old['files']), 'Source inventory differs')
    changed = {rel for rel, sha in candidate['files'].items() if old['files'].get(rel) != sha}
    require(changed == set(candidate['changed_files']) and len(changed) == 9
            and all(rel.startswith(PREFIX) for rel in changed)
            and len(candidate['files']) == 1167, 'Unexpected source delta')
    require(all(candidate['files'][rel] == sha for rel, sha in old['files'].items()
                if rel not in changed), 'Unrelated source changed')
    source = Path(candidate['source_directory']).resolve()
    secrets = known_secrets()
    payload = {}
    for rel, sha in candidate['files'].items():
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in rel
                and path.parts[0] in ('custom_addons', 'third_party_addons'), 'Unsafe source path')
        src = source.joinpath(*path.parts)
        require(not src.is_symlink() and src.resolve().is_relative_to(source), 'Unsafe frozen source')
        data = src.read_bytes()
        require(digest(data) == sha, 'Frozen source hash differs: ' + rel)
        if rel in old['files']:
            require(digest((REPO / rel).read_bytes()) == old['files'][rel], 'Old checkout differs: ' + rel)
        if rel in changed:
            require(not any(secret in data for secret in secrets), 'Credential match: ' + rel)
            require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data),
                    'Private key in source')
            payload[rel] = data
    payload['release-source.json'] = (json.dumps(dict(source_commit=candidate['commit'],
        odoo_image=candidate['image'], odoo_major=19, files=candidate['files']), indent=2) + '\n').encode()
    readme = (REPO / 'README.md').read_text(encoding='utf-8-sig')
    readme, source_count = re.subn(r'^- أصل المصدر: `[^`]+`\.$',
        '- أصل المصدر: `' + candidate['commit'] + '`.', readme, flags=re.M)
    readme, file_count = re.subn(r'^- ملف `release-source\.json` يثبت\s*\d+\s*ملفًا.*$',
        '- ملف `release-source.json` يثبت 1167 ملفًا ببصمات SHA256 وصورة Odoo المعتمدة.', readme, flags=re.M)
    require((source_count, file_count) == (1, 1), 'README format differs')
    payload['README.md'] = readme.encode('utf8')
    for rel in payload:
        dst = REPO / rel
        require(not dst.is_symlink() and dst.resolve().is_relative_to(REPO.resolve()), 'Unsafe destination')
    for rel, data in payload.items():
        dst = REPO / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    subprocess.run([sys.executable, 'ops/verify_source.py'], cwd=REPO, check=True)
    require(source_inventory(REPO) == set(candidate['files']), 'Prepared inventory differs')
    print('PREPARED FL2', candidate['commit'], '9 addon changes; 1158 preserved; source-only')


if __name__ == '__main__':
    prepare()
