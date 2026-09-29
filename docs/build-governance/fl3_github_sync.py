"""Prepare only verified FL3 addon source in the existing publication checkout."""
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath

from fl1_github_sync import REPO, git, require, read_json, digest, source_inventory
from live1_export import known_secrets
import fl3_release as r

PREVIOUS_PUBLIC = 'be89096027c823dbe5414bbf95ce97e9e354a5b6'


def prepare():
    candidate = r.verify_candidate()
    r.review_go(r.OUT / 'PREDEPLOY-GO.md', candidate['commit'])
    runtime, preservation = read_json(r.OUT / 'runtime.json'), read_json(r.OUT / 'main-preservation.json')
    require(runtime['candidate'] == candidate['commit'] and runtime['http'] == 200
            and runtime['installed'] == 'installed|' + r.VERSION and runtime['no_pending_modules'], 'MAIN verification missing')
    require(preservation['candidate'] == candidate['commit'] and all(preservation[k] for k in (
        'existing_rows_exact', 'existing_columns_exact', 'existing_user_memberships_exact',
        'existing_user_presets_exact', 'existing_module_versions_exact')), 'Preservation incomplete')
    require(git('remote', 'get-url', 'origin').rstrip('/').removesuffix('.git') == 'https://github.com/hajrix01-star/Odoo-Baseer', 'Wrong remote')
    require(git('branch', '--show-current') == 'main' and git('rev-parse', 'HEAD') == PREVIOUS_PUBLIC
            and not git('status', '--porcelain'), 'Publication checkout differs')
    old = read_json(REPO / 'release-source.json')
    require(old['source_commit'] == candidate['parent'] == r.PARENT and old['odoo_image'] == candidate['image'], 'Wrong parent/runtime')
    require(len(old['files']) == 1181 and set(old['files']).issubset(candidate['files'])
            and source_inventory(REPO) == set(old['files']), 'Inventory differs')
    changed = {rel for rel, sha in candidate['files'].items() if old['files'].get(rel) != sha}
    require(changed == set(candidate['changed_files']) and all(rel.startswith(r.PREFIX) for rel in changed), 'Unexpected source delta')
    secrets = known_secrets()
    payload = {}
    for rel, sha in candidate['files'].items():
        path = PurePosixPath(rel)
        require(not path.is_absolute() and '..' not in path.parts and '\\' not in rel
                and path.parts[0] in ('custom_addons', 'third_party_addons'), 'Unsafe path')
        src = r.SOURCE / rel
        require(not src.is_symlink() and src.resolve().is_relative_to(r.SOURCE.resolve()), 'Unsafe source')
        data = src.read_bytes()
        require(digest(data) == sha, 'Source hash differs')
        if rel in old['files']: require(digest((REPO / rel).read_bytes()) == old['files'][rel], 'Checkout file differs')
        if rel in changed:
            require(not any(secret in data for secret in secrets), 'Credential match')
            require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data), 'Private key match')
            payload[rel] = data
    payload['release-source.json'] = (json.dumps(dict(source_commit=candidate['commit'], odoo_image=candidate['image'],
        odoo_major=19, files=candidate['files']), indent=2) + '\n').encode()
    readme = (REPO / 'README.md').read_text(encoding='utf8')
    readme, source_count = re.subn(r'^- أصل المصدر: `[^`]+`\.$', '- أصل المصدر: `' + candidate['commit'] + '`.', readme, flags=re.M)
    readme, file_count = re.subn(r'^- ملف `release-source\.json` يثبت\s*\d+\s*ملفًا.*$',
        '- ملف `release-source.json` يثبت ' + str(len(candidate['files'])) + ' ملفًا ببصمات SHA256 وصورة Odoo المعتمدة.', readme, flags=re.M)
    require((source_count, file_count) == (1, 1), 'README format changed')
    payload['README.md'] = readme.encode()
    for rel in payload:
        dst = REPO / rel
        require(not dst.is_symlink() and dst.resolve().is_relative_to(REPO.resolve()), 'Unsafe destination')
    for rel, data in payload.items():
        dst = REPO / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    subprocess.run([sys.executable, 'ops/verify_source.py'], cwd=REPO, check=True)
    require(source_inventory(REPO) == set(candidate['files']), 'Final inventory differs')
    print('FL3 SOURCE PREPARED', candidate['commit'], len(changed))


if __name__ == '__main__':
    prepare()
