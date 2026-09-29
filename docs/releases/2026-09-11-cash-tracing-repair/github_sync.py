"""Publish-source preparation after verified MAIN deployment; never commit/push.

inspect is read-only. prepare copies exactly the six accepted addon files plus
the existing README/source lock into the existing publication checkout.
verify-prepared rechecks that eight-file change before the operator commits it.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / 'docs' / 'build-governance'))
from fl1_github_sync import REPO, git, require, read_json, digest, source_inventory
from live1_export import known_secrets

REMOTE = 'https://github.com/hajrix01-star/Odoo-Baseer'
PREVIOUS_PUBLIC = '031264047111ca677f404608543a2d22d0cfc10b'
PREVIOUS_SOURCE = 'f38e4c4934c377dac69cd563c2ed3ca30b61bf9e'
QA_SHA256 = '1824578524e00788c8e35f7f23af0567e8252f93ac2bc583017e6502ddc79bfd'
PREVIOUS_CI = 34519359419
VERSIONS = {'baseer_cash_categories': '19.0.1.3.2', 'baseer_pos_summary': '19.0.1.5.2',
            'baseer_financial_register': '19.0.1.2.1'}
CHANGED = {
    'custom_addons/baseer_cash_categories/__manifest__.py',
    'custom_addons/baseer_cash_categories/models/cash_categories.py',
    'custom_addons/baseer_financial_register/__manifest__.py',
    'custom_addons/baseer_financial_register/models/platform.py',
    'custom_addons/baseer_pos_summary/__manifest__.py',
    'custom_addons/baseer_pos_summary/models/cash_report.py',
}
EXPORT = CHANGED | {'README.md', 'release-source.json'}


def remote_head():
    rows = git('ls-remote', 'origin', 'refs/heads/main').splitlines()
    require(len(rows) == 1 and rows[0].split()[1] == 'refs/heads/main', 'Unexpected remote branch result')
    return rows[0].split()[0]


def publication_checkout(clean):
    require(REPO.resolve() == (ROOT / '.local-backups/live1-20260909/repository').resolve(),
            'Unexpected publication checkout')
    require(git('remote', 'get-url', 'origin').rstrip('/').removesuffix('.git') == REMOTE,
            'Unexpected GitHub remote')
    require(git('branch', '--show-current') == 'main' and git('rev-parse', 'HEAD') == PREVIOUS_PUBLIC,
            'Publication branch or previous HEAD changed')
    require(remote_head() == PREVIOUS_PUBLIC, 'Remote main changed; do not overwrite or force push')
    if clean:
        require(not git('status', '--porcelain'), 'Publication checkout is not clean')


def inspect():
    publication_checkout(clean=True)
    previous = read_json(REPO / 'release-source.json')
    require(previous['source_commit'] == PREVIOUS_SOURCE and len(previous['files']) == 1183,
            'Previous source lock changed')
    subprocess.run([sys.executable, 'ops/verify_source.py'], cwd=REPO, check=True)
    ci = json.loads(subprocess.check_output(['gh', 'run', 'view', str(PREVIOUS_CI),
        '--repo', 'hajrix01-star/Odoo-Baseer', '--json', 'databaseId,headSha,status,conclusion,url,workflowName'], text=True))
    require(ci['headSha'] == PREVIOUS_PUBLIC and ci['status'] == 'completed'
            and ci['conclusion'] == 'success', 'Previous public commit has no matching successful CI')
    print(json.dumps({'status': 'PASS', 'read_only': True, 'repository': str(REPO),
        'remote': REMOTE, 'head': PREVIOUS_PUBLIC, 'source_commit': PREVIOUS_SOURCE,
        'source_files': 1183, 'checkout_clean': True, 'ci': ci}, indent=2))


def candidate_and_gate():
    # Imported lazily: inspect remains useful before the MAIN release exists.
    sys.path.insert(0, str(OUT))
    import main_release as release
    candidate = release.verify_candidate()
    require(Path(candidate['source_directory']).resolve() == Path(release.SOURCE).resolve(),
            'Candidate source directory differs from the MAIN release')
    require(re.fullmatch(r'[0-9a-f]{40}', candidate['commit']) is not None,
            'The publication metadata requires a real source Git commit')
    require(candidate['parent'] == PREVIOUS_SOURCE and candidate['candidate_sha256'] == QA_SHA256,
            'Candidate does not match the accepted QA source')
    require(len(candidate['files']) == 1183 and set(candidate['changed_files']) == CHANGED,
            'Only the six accepted files may change')
    require(digest(json.dumps(candidate['files'], sort_keys=True).encode()) == QA_SHA256,
            'Candidate inventory fingerprint differs from accepted QA')
    require(candidate['versions'] == VERSIONS, 'Candidate module versions differ')
    source = Path(candidate['source_directory']).resolve()
    source_head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    require(source_head == candidate['commit'], 'Frozen source HEAD differs from its real commit')
    require(not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip(),
            'Frozen source is not clean')
    require(source_inventory(source) == set(candidate['files']), 'Frozen source inventory differs')
    release.review_go(OUT / 'PREDEPLOY-GO.md', candidate['commit'])
    runtime = read_json(OUT / 'runtime.json')
    preservation = read_json(OUT / 'main-preservation.json')
    smoke = read_json(OUT / 'main-smoke.json')
    require(runtime.get('candidate') == candidate['commit'] and runtime.get('http') == 200
            and runtime.get('no_pending_modules') is True and runtime.get('source_tree_exact') is True
            and runtime.get('versions') == VERSIONS, 'Successful matching MAIN runtime evidence is required')
    require(preservation.get('candidate') == candidate['commit'] and all(preservation.get(key) is True
            for key in ('all_business_exact', 'security_exact', 'schema_exact', 'module_versions_exact'))
            and isinstance(preservation.get('technical_metadata_only'), dict),
            'MAIN business/security/schema/module preservation evidence is incomplete')
    require(smoke.get('status') == 'PASS' and smoke.get('read_only') is True
            and (smoke.get('candidate') == candidate['commit'] or smoke.get('candidate_sha256') == QA_SHA256),
            'Matching read-only MAIN smoke must pass')
    return candidate, source


def safe_file(root, relative):
    parts = PurePosixPath(relative)
    require(not parts.is_absolute() and '..' not in parts.parts and '\\' not in relative,
            'Unsafe relative path: ' + relative)
    target = root.joinpath(*parts.parts)
    require(not target.is_symlink() and target.resolve().is_relative_to(root.resolve()),
            'Unsafe resolved path: ' + relative)
    return target


def expected_payload(candidate, source, previous, verify_old):
    require(previous['source_commit'] == PREVIOUS_SOURCE and previous['odoo_major'] == 19
            and previous['odoo_image'] == candidate['image'], 'Previous source or runtime image changed')
    require(set(previous['files']) == set(candidate['files']) and len(previous['files']) == 1183,
            'All accepted source files must remain present')
    changed = {relative for relative, sha in candidate['files'].items() if previous['files'].get(relative) != sha}
    require(changed == CHANGED, 'The source delta differs from the six approved files')
    payload = {}
    for relative, sha in candidate['files'].items():
        require(PurePosixPath(relative).parts[0] in ('custom_addons', 'third_party_addons'),
                'Only addon source may be published')
        original = safe_file(source, relative)
        data = original.read_bytes()
        require(digest(data) == sha, 'Frozen source hash differs: ' + relative)
        destination = safe_file(REPO, relative)
        if verify_old:
            require(digest(destination.read_bytes()) == previous['files'][relative],
                    'Publication source changed before preparation: ' + relative)
        if relative in CHANGED:
            payload[relative] = data
    payload['release-source.json'] = (json.dumps({'source_commit': candidate['commit'],
        'odoo_image': candidate['image'], 'odoo_major': 19, 'files': candidate['files']}, indent=2) + '\n').encode()
    old_readme = subprocess.check_output(['git', '-C', str(REPO), 'show', PREVIOUS_PUBLIC + ':README.md'])
    readme = old_readme.decode('utf-8-sig')
    readme, source_count = re.subn(r'^- أصل المصدر: `[^`]+`\.$',
        '- أصل المصدر: `' + candidate['commit'] + '`.', readme, flags=re.M)
    readme, file_count = re.subn(r'^- ملف `release-source\.json` يثبت\s*\d+\s*ملفًا.*$',
        '- ملف `release-source.json` يثبت 1183 ملفًا ببصمات SHA256 وصورة Odoo المعتمدة.', readme, flags=re.M)
    require((source_count, file_count) == (1, 1), 'README source metadata format changed')
    if verify_old:
        require(safe_file(REPO, 'README.md').read_bytes() == old_readme, 'README differs before preparation')
    payload['README.md'] = readme.encode('utf8')
    require(set(payload) == EXPORT, 'Unexpected export file set')
    secrets = known_secrets()
    for relative, data in payload.items():
        safe_file(REPO, relative)
        require(not any(secret in data for secret in secrets), 'Credential match in export: ' + relative)
        require(not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data),
                'Private key match in export: ' + relative)
    return payload


def prepared_checks(candidate, payload):
    require(source_inventory(REPO) == set(candidate['files']), 'Prepared source inventory differs')
    require(not git('diff', '--cached', '--name-only'), 'Preparation must not stage any files')
    require(not git('ls-files', '--others', '--exclude-standard'), 'Unexpected untracked publication files')
    require(set(git('diff', '--name-only', 'HEAD').splitlines()) == EXPORT,
            'Prepared checkout must contain exactly six addon changes plus README/source lock')
    for relative, data in payload.items():
        require(safe_file(REPO, relative).read_bytes() == data, 'Prepared payload differs: ' + relative)
    subprocess.run(['git', '-C', str(REPO), 'diff', '--check'], check=True)
    subprocess.run([sys.executable, 'ops/verify_source.py'], cwd=REPO, check=True)


def prepare(verify_only=False):
    candidate, source = candidate_and_gate()
    publication_checkout(clean=not verify_only)
    previous = json.loads(subprocess.check_output(['git', '-C', str(REPO), 'show',
        PREVIOUS_PUBLIC + ':release-source.json'], text=True))
    payload = expected_payload(candidate, source, previous, verify_old=not verify_only)
    if not verify_only:
        # All source, destination, MAIN, scope and secrecy checks precede writes.
        for relative, data in payload.items():
            safe_file(REPO, relative).write_bytes(data)
    prepared_checks(candidate, payload)
    print(json.dumps({'status': 'PASS', 'phase': 'verify-prepared' if verify_only else 'prepare',
        'source_commit': candidate['commit'], 'candidate_sha256': QA_SHA256,
        'source_files': 1183, 'changed_source_files': 6, 'export_files': sorted(EXPORT),
        'staged': False, 'committed': False, 'pushed': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect', 'prepare', 'verify-prepared'))
    args = parser.parse_args()
    if args.command == 'inspect':
        inspect()
    else:
        prepare(verify_only=args.command == 'verify-prepared')
