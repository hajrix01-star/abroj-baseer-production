#!/usr/bin/env python3
"""One bounded FCM env activation on the already accepted S81 production release.

Input is public apply/backup metadata on stdin, never a private key. No module
upgrade, source switch, database write, provider request or notification send.
Failure recovery restores the external env FIRST, then recreates the SAME Odoo
source/image only. A successful recovery is still an activation failure, not GO.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import types
import urllib.error
import urllib.request

BASE = Path('/srv/abroj-baseer-production')
SOURCE = '81fdd415521670b8c7ad681e97dd583e6f9c85e0'
POLICY = 'cf6062d29e11f2cbea68d100cc1e48a67606c592'
DEPLOY = '39513209001'
APPROVAL = '39511784259'
RELEASE_ID = 'baseer-2026-10-21-bwork-production'
PROJECT = 'baseer-odoo-prod'
CONFIGURE = BASE / 'control-plane-staging/bwork-73947439/ops/production/configure-bwork-fcm-runtime.py'
CONFIGURE_SHA = '1c120b277601eb46b67806b9d4c04f89f798804ea4548cd155367205c5154f59'
COMPOSE_SHA = '2f4a19ae7df388563c147d1763c756f01af8e7e59534780a3d29ecbe0c17b11c'
MODULES = ('baseer_bwork', 'baseer_bwork_procurement', 'baseer_bwork_admin',
           'baseer_bwork_dashboard', 'baseer_sales_dashboard', 'baseer_sales_heat_calendar',
           'baseer_access_roles', 'baseer_procurement_requests')
ODOO = PROJECT + '-odoo-1'
OTHERS = (PROJECT + '-db-1', PROJECT + '-odoo_data_init-1')
JSON_KEY = 'BWORK_FCM_SERVICE_ACCOUNT_JSON'
FILE_KEY = 'BWORK_FCM_SERVICE_ACCOUNT_FILE'


class Stop(Exception):
    pass


def need(value, code):
    if not value:
        raise Stop(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def public_file(path, cap=65536, odoo_config=False):
    """Root-owned nonlink public/control bytes; never read arbitrary CLI paths."""
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
             and info.st_mode & 0o022 == 0, 'unsafe_control_parent')
    before = path.lstat()
    need(stat.S_ISREG(before.st_mode) and before.st_uid == 0 and (before.st_gid == 0 or odoo_config)
         and before.st_nlink == 1 and before.st_mode & 0o022 == 0, 'unsafe_control_file')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        actual = os.fstat(fd)
        need((actual.st_dev, actual.st_ino) == (before.st_dev, before.st_ino)
             and actual.st_size <= cap, 'control_file_changed')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(cap + 1)
        need(len(raw) <= cap, 'control_file_size')
        return raw
    finally:
        os.close(fd)


def load_configure():
    raw = public_file(CONFIGURE)
    need(stat.S_IMODE(CONFIGURE.lstat().st_mode) == 0o600
         and digest(raw) == CONFIGURE_SHA, 'configure_pin_mismatch')
    module = types.ModuleType('pinned_bwork_fcm_configure')
    # Compile exactly the verified bytes, never reopen a replaceable import path.
    exec(compile(raw, str(CONFIGURE), 'exec'), module.__dict__)
    return module


def metadata(raw, helper):
    need(0 < len(raw) <= 4096, 'metadata_size')
    value = helper.strict_json(raw)
    need(isinstance(value, dict) and set(value) == {
        'appliedEnvSha256', 'oldEnvSha256', 'backupPath', 'receiptSha256', 'expectedDeployRun'}, 'metadata_keys')
    for key in ('appliedEnvSha256', 'oldEnvSha256', 'receiptSha256'):
        need(isinstance(value[key], str) and re.fullmatch(r'[0-9a-f]{64}', value[key]), 'metadata_hash')
    need(value['expectedDeployRun'] == DEPLOY and isinstance(value['backupPath'], str), 'metadata_run')
    backup = Path(value['backupPath'])
    need(backup.is_absolute() and '..' not in backup.parts and backup.name == 'preimage.env'
         and re.fullmatch(r'fcm-[A-Za-z0-9_-]{1,80}', backup.parent.name)
         and backup.parent.parent == helper.BACKUP_ROOT, 'metadata_backup')
    return value


def capture(args, cap=2 * 1024 * 1024, timeout=20):
    # Docker output can contain passwords/credential JSON: memory ONLY, never log it.
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=timeout, check=False)
    need(result.returncode == 0 and len(result.stdout) <= cap, 'local_command_failed')
    return result.stdout


def object_capture(args):
    return json.loads(capture(args))


def read_receipt_env(raw):
    values = {}
    for line in raw.decode('ascii').splitlines():
        key, separator, value = line.partition('=')
        need(separator and key not in values, 'deployment_receipt_invalid')
        values[key] = value
    return values


def release_identity():
    link = BASE / 'current'
    info = link.lstat()
    need(stat.S_ISLNK(info.st_mode) and info.st_uid == info.st_gid == 0, 'current_link_unsafe')
    release = link.resolve(strict=True)
    match = re.fullmatch(SOURCE[:12] + '-run-' + DEPLOY + r'-(\d{8}T\d{6}Z)', release.name)
    need(release.parent == BASE / 'releases' and match, 'current_release_mismatch')
    need(public_file(release / 'RELEASE_COMMIT').strip() == SOURCE.encode(), 'source_marker_mismatch')
    backup = BASE / 'backups' / ('pre-' + SOURCE[:12] + '-' + DEPLOY + '-' + match[1])
    receipt_raw = public_file(backup / 'result.env', 8192)
    receipt = read_receipt_env(receipt_raw)
    need(receipt == {'LIVE': 'GO', 'RELEASE_ID': RELEASE_ID, 'RELEASE': str(release),
                    'BACKUP': str(backup), 'COMMIT': SOURCE, 'MODULES': ' '.join(MODULES),
                    'THIRD_PARTY_MODULES': '', 'POLICY_REVISION': POLICY,
                    'APPROVED_RUN_ID': APPROVAL}, 'deployment_not_accepted')
    return release, digest(receipt_raw)


def installed_dms():
    # One read-only scalar, no ORM/server startup and no SQL mutation.
    command = 'psql -U "$POSTGRES_USER" -d baseer_prod -Atqc "SELECT state FROM ir_module_module WHERE name = \'dms\'"'
    state = capture(['docker', 'exec', OTHERS[0], 'sh', '-lc', command], cap=32).strip()
    need(state in (b'', b'uninstalled', b'installed'), 'dms_state_unsafe')
    return state == b'installed'


def dms_files(release, required):
    overlay = release / 'config/dms-runtime.compose.json'
    checksum = release / 'config/dms-runtime.sha256'
    if not os.path.lexists(overlay):
        need(not required and not os.path.lexists(checksum), 'dms_overlay_missing')
        return {}
    raw, sums = public_file(overlay), public_file(checksum, 1024)
    need(stat.S_IMODE(overlay.lstat().st_mode) == stat.S_IMODE(checksum.lstat().st_mode) == 0o600,
         'dms_metadata_unsafe')
    need(sums.decode('ascii').strip() == digest(raw) + '  config/dms-runtime.compose.json', 'dms_checksum_mismatch')
    value = json.loads(raw)
    need(set(value) == {'services'} and set(value['services']) == {'odoo'}
         and set(value['services']['odoo']) == {'command'}, 'dms_overlay_invalid')
    safe_command(value['services']['odoo']['command'])
    return {str(overlay): digest(raw), str(checksum): digest(sums)}


def safe_command(command):
    need(isinstance(command, list) and command and command[0] == 'odoo'
         and all(isinstance(item, str) and '\n' not in item and '\r' not in item for item in command),
         'odoo_command_invalid')
    need(not any(item.startswith(('-u', '-i', '--update', '--init', '--stop-after-init',
                 '--pre-upgrade-scripts')) for item in command), 'odoo_upgrade_forbidden')
    need(not any('password' in item.lower() for item in command), 'odoo_password_argument_forbidden')


def runtime_command_comparison(compose_command):
    """Compare Compose 2.40.3's one proved dollar serialization, never alter UP input."""
    safe_command(compose_command)
    pinned = '--db-filter=^baseer_prod$$'
    filters = [item for item in compose_command if item.startswith('--db-filter')]
    need(filters == [pinned], 'pinned_db_filter_required')
    comparison = list(compose_command)
    comparison[comparison.index(pinned)] = '--db-filter=^baseer_prod$'
    return comparison


def environment_list(values):
    result = {}
    need(isinstance(values, list), 'container_env_invalid')
    for value in values:
        key, sep, content = value.partition('=')
        need(sep and key not in result, 'container_env_invalid')
        need(not key.startswith('BCHAT_FCM'), 'legacy_fcm_environment_forbidden')
        result[key] = content
    return result


def credential_from_env(raw, helper):
    found = helper.configured_lines(raw)
    need(len(found) == 1 and found[0][0] == helper.JSON_KEY, 'configured_key_invalid')
    line = found[0][1]
    prefix = helper.JSON_KEY + b"='"
    need(line.startswith(prefix) and line.endswith(b"'"), 'configured_line_invalid')
    compact = line[len(prefix):-1]
    need(helper.canonical_account(compact) == compact, 'configured_json_not_canonical')
    return compact.decode('ascii')


def bound_environment(value, helper):
    raw = helper.read_private(helper.ENV_PATH)
    need(digest(raw) == value['appliedEnvSha256'], 'STOP_environment_changed')
    backup = Path(value['backupPath'])
    for directory in (helper.BACKUP_ROOT, backup.parent):
        info = directory.lstat()
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == info.st_gid == 0
             and stat.S_IMODE(info.st_mode) == 0o700, 'backup_directory_unsafe')
    before = helper.read_private(backup)
    receipt_raw = helper.read_private(backup.parent / 'receipt.json', cap=8192)
    receipt = helper.strict_json(receipt_raw)
    need(digest(receipt_raw) == value['receiptSha256'] and digest(before) == value['oldEnvSha256']
         and receipt.get('environment') == str(helper.ENV_PATH) and receipt.get('backup') == str(backup)
         and receipt.get('installedSha256') == value['appliedEnvSha256']
         and receipt.get('beforeSha256') == value['oldEnvSha256'] and receipt.get('version') == 1
         and receipt.get('beforeBytes') == len(before) and receipt.get('installedBytes') == len(raw)
         and (receipt.get('uid'), receipt.get('gid'), receipt.get('mode')) == (0, 0, '0600'), 'backup_binding_invalid')
    compact = credential_from_env(raw, helper)
    need(not helper.configured_lines(before) and helper.appended_environment(before, compact.encode()) == raw,
         'backup_partition_invalid')
    return compact


def compose_arguments(release, dms, overlay):
    args = ['docker', 'compose', '--project-name', PROJECT, '--env-file', str(release / '.env'),
            '-f', str(release / 'compose.production.yaml')]
    if dms:
        args += ['-f', str(release / 'config/dms-runtime.compose.json')]
    return args + ['-f', str(overlay), '--project-directory', str(release)]


def validate_compose(config, release, credential):
    need(config.get('name') == PROJECT and set(config.get('services', {})) == {'db', 'odoo', 'odoo_data_init'},
         'compose_project_invalid')
    for service, spec in config['services'].items():
        env = spec.get('environment', {})
        need(isinstance(env, dict) and FILE_KEY not in env, 'compose_credential_scope')
        need(not any(key.startswith('BCHAT_FCM') for key in env), 'legacy_fcm_environment_forbidden')
        need(env.get(JSON_KEY) == credential if service == 'odoo' and credential is not None else JSON_KEY not in env,
             'compose_credential_scope')
    odoo = config['services']['odoo']
    safe_command(odoo['command'])
    data = [m for m in odoo.get('volumes', []) if m.get('target') == '/var/lib/odoo']
    need(len(data) == 1 and data[0].get('type') == 'volume' and data[0].get('source') == 'odoo-data'
         and not data[0].get('read_only')
         and config.get('volumes', {}).get('odoo-data', {}).get('name') == PROJECT + '-odoo-data',
         'compose_data_volume')
    expected = {'/mnt/baseer-addons': str(release / 'custom_addons'),
                '/mnt/third-party-addons': str(release / 'third_party_addons'),
                '/etc/odoo/odoo.conf': str(release / 'config/odoo.conf')}
    binds = {row['target']: row for row in odoo.get('volumes', []) if row.get('type') == 'bind'}
    need(set(binds) == set(expected) and all(binds[k].get('source') == v and binds[k].get('read_only') is True
         for k, v in expected.items()), 'compose_source_mounts')
    return odoo


def snapshots():
    rows = object_capture(['docker', 'inspect', ODOO, *OTHERS])
    need(isinstance(rows, list) and len(rows) == 3, 'container_inventory_invalid')
    result = {row['Name'].lstrip('/'): row for row in rows}
    need(set(result) == {ODOO, *OTHERS}, 'container_inventory_invalid')
    for name, row in result.items():
        labels = row['Config'].get('Labels', {})
        need(labels.get('com.docker.compose.project') == PROJECT, 'container_project_mismatch')
        need(FILE_KEY not in environment_list(row['Config'].get('Env', [])), 'container_file_key_forbidden')
        if name != ODOO:
            need(JSON_KEY not in environment_list(row['Config'].get('Env', [])), 'container_credential_scope')
    return result


def runtime_projection(row):
    return {'image': row['Image'], 'imageRef': row['Config']['Image'], 'command': row['Config']['Cmd'],
            'entrypoint': row['Config'].get('Entrypoint'),
            'mounts': sorted((m['Type'], m['Source'], m['Destination'], m['RW'], m.get('Name')) for m in row['Mounts']),
            'ports': row['HostConfig'].get('PortBindings'),
            'networks': sorted(row['NetworkSettings']['Networks'])}


def validate_runtime(rows, odoo, release, image_id, image_volumes):
    row = rows[ODOO]
    need(row['Image'] == image_id and row['Config']['Image'] == odoo['image']
         and row['Config']['Cmd'] == runtime_command_comparison(odoo['command']), 'runtime_image_or_command_mismatch')
    labels = row['Config'].get('Labels', {})
    need(labels.get('com.docker.compose.service') == 'odoo'
         and labels.get('com.docker.compose.project.working_dir') == str(release), 'runtime_release_mismatch')
    explicit = {'/mnt/baseer-addons', '/mnt/third-party-addons', '/etc/odoo/odoo.conf', '/var/lib/odoo'}
    need(isinstance(image_volumes, dict), 'image_volumes_invalid')
    expected_targets = explicit | set(image_volumes)
    actual_targets = [mount['Destination'] for mount in row['Mounts']]
    need(len(actual_targets) == len(expected_targets) and set(actual_targets) == expected_targets,
         'unexpected_runtime_mount')
    for target in set(image_volumes) - explicit:
        mount = next(m for m in row['Mounts'] if m['Destination'] == target)
        need(mount['Type'] == 'volume' and mount['RW'] is True
             and isinstance(mount.get('Name'), str) and re.fullmatch(r'[0-9a-f]{64}', mount['Name']),
             'image_anonymous_volume_invalid')
    data = [m for m in row['Mounts'] if m['Destination'] == '/var/lib/odoo']
    need(len(data) == 1 and data[0]['Type'] == 'volume'
         and data[0].get('Name') == PROJECT + '-odoo-data' and data[0]['RW'] is True, 'runtime_data_volume')
    need(row['HostConfig'].get('PortBindings') == {
        '8069/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18069'}],
        '8072/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18072'}]}
        and set(row['NetworkSettings']['Networks']) == {PROJECT + '-frontend', PROJECT + '-backend'},
        'runtime_network_projection')
    for target, source in (('/mnt/baseer-addons', release / 'custom_addons'),
                           ('/mnt/third-party-addons', release / 'third_party_addons'),
                           ('/etc/odoo/odoo.conf', release / 'config/odoo.conf')):
        found = [m for m in row['Mounts'] if m['Destination'] == target]
        need(len(found) == 1 and found[0]['Type'] == 'bind' and found[0]['Source'] == str(source)
             and found[0]['RW'] is False, 'runtime_source_mounts')


def verify_volume_sources(row):
    """Local Docker metadata only: prove named/anonymous source/name/type before UP."""
    mounts = [mount for mount in row['Mounts'] if mount['Type'] == 'volume']
    names = [mount['Name'] for mount in mounts]
    need(len(names) == len(set(names)), 'volume_inventory_invalid')
    rows = object_capture(['docker', 'volume', 'inspect', *names])
    need(isinstance(rows, list) and len(rows) == len(names), 'volume_inventory_invalid')
    indexed = {volume['Name']: volume for volume in rows}
    need(set(indexed) == set(names) and all(
        indexed[mount['Name']].get('Driver') == 'local'
        and indexed[mount['Name']].get('Scope') == 'local'
        and indexed[mount['Name']].get('Options') in (None, {})
        and indexed[mount['Name']].get('Mountpoint') == mount['Source'] for mount in mounts),
        'volume_source_mismatch')


def health():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    deadline = time.monotonic() + 45

    def status(url):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        try:
            response = opener.open(url, timeout=min(2, remaining))
        except urllib.error.HTTPError as error:
            response = error  # NoRedirect exposes 303 as HTTPError; never follow it.
        with response as actual:
            code = actual.status
            locations = actual.headers.get_all('Location', []) if actual.headers is not None else []
        if time.monotonic() >= deadline:
            raise TimeoutError()
        return code, locations

    while time.monotonic() < deadline:
        try:
            code, locations = status('http://127.0.0.1:18069/web/login')
            if code == 200:
                return
            if code == 303 and locations == ['/en/web/login']:
                # Proven production language routing only: fixed second GET, no Location-derived URL.
                if status('http://127.0.0.1:18069/en/web/login')[0] == 200:
                    return
        except Exception:
            pass
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise Stop('login_health_failed')


def activate(value, helper):
    release, receipt_sha = release_identity()
    compact = bound_environment(value, helper)
    dms_required = installed_dms()
    dms = dms_files(release, dms_required)
    source_files = {str(release / 'compose.production.yaml'): digest(public_file(release / 'compose.production.yaml')),
                    str(release / 'RELEASE_COMMIT'): digest(public_file(release / 'RELEASE_COMMIT')), **dms}
    need(source_files[str(release / 'compose.production.yaml')] == COMPOSE_SHA, 'frozen_compose_mismatch')
    shared_env_sha = digest(helper.read_private(release / '.env'))
    config_sha = digest(public_file(release / 'config/odoo.conf', odoo_config=True))
    fd, overlay_name = tempfile.mkstemp(prefix='baseer-google-odoo.', suffix='.yaml', dir='/run')
    overlay = Path(overlay_name)
    try:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
        yaml = ('services:\n  odoo:\n    env_file:\n      - "' + str(helper.ENV_PATH) + '"\n').encode()
        with os.fdopen(fd, 'wb') as stream:
            stream.write(yaml)
            stream.flush()
            os.fsync(stream.fileno())
        fd = -1
        helper.fsync_dir(Path('/run'))
        args = compose_arguments(release, dms, overlay)
        config = object_capture(args + ['config', '--format', 'json'])
        odoo = validate_compose(config, release, compact)
        image = object_capture(['docker', 'image', 'inspect', odoo['image']])
        need(isinstance(image, list) and len(image) == 1, 'local_image_invalid')
        image_id = image[0]['Id']
        image_volumes = image[0]['Config'].get('Volumes') or {}
        initial = snapshots()
        validate_runtime(initial, odoo, release, image_id, image_volumes)
        verify_volume_sources(initial[ODOO])
        baseline = runtime_projection(initial[ODOO])
        initial_env = environment_list(initial[ODOO]['Config']['Env'])
        expected_env = environment_list(image[0]['Config'].get('Env') or [])
        expected_env.update(odoo.get('environment', {}))
        need({key: content for key, content in initial_env.items() if key != JSON_KEY}
             == {key: content for key, content in expected_env.items() if key != JSON_KEY},
             'initial_non_fcm_environment_mismatch')
        need(initial[ODOO]['Config'].get('Entrypoint') == image[0]['Config'].get('Entrypoint'), 'initial_entrypoint_mismatch')
        need(JSON_KEY not in initial_env or initial_env[JSON_KEY] == compact, 'STOP_runtime_credential_unknown')
        need(initial[ODOO]['State']['Running'] is True, 'initial_odoo_not_running')
        health()

        def guard(expected_env, allowed_credentials):
            need(release_identity() == (release, receipt_sha), 'STOP_source_changed')
            need(digest(helper.read_private(helper.ENV_PATH)) == expected_env, 'STOP_environment_changed')
            need(helper.read_private(overlay) == yaml, 'STOP_overlay_changed')
            need(digest(helper.read_private(release / '.env')) == shared_env_sha, 'STOP_shared_env_changed')
            need(digest(public_file(release / 'config/odoo.conf', odoo_config=True)) == config_sha, 'STOP_odoo_config_changed')
            for name, expected in source_files.items():
                need(digest(public_file(Path(name))) == expected, 'STOP_source_changed')
            need(object_capture(['docker', 'image', 'inspect', odoo['image']])[0]['Id'] == image_id, 'STOP_image_changed')
            current = snapshots()
            validate_runtime(current, odoo, release, image_id, image_volumes)
            need(runtime_projection(current[ODOO]) == baseline, 'STOP_runtime_changed')
            need(all(current[name]['Id'] == initial[name]['Id'] for name in OTHERS), 'STOP_other_container_changed')
            running_env = environment_list(current[ODOO]['Config']['Env'])
            need({k: v for k, v in running_env.items() if k != JSON_KEY}
                 == {k: v for k, v in initial_env.items() if k != JSON_KEY}, 'STOP_non_fcm_environment_changed')
            actual = running_env.get(JSON_KEY)
            need(actual in allowed_credentials, 'STOP_runtime_credential_unknown')
            return current

        if initial_env.get(JSON_KEY) == compact:
            guard(value['appliedEnvSha256'], (compact,))
            return {'status': 'already_active', 'sourceVerified': True, 'credentialVerified': True}
        guard(value['appliedEnvSha256'], (None,))
        up = ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'odoo']
        try:
            capture(args + up, cap=65536, timeout=45)
            health()
            current = guard(value['appliedEnvSha256'], (compact,))
            need(current[ODOO]['State']['Running'] is True, 'activated_odoo_not_running')
            return {'status': 'activated', 'sourceVerified': True, 'credentialVerified': True}
        except Exception as error:
            if isinstance(error, Stop) and str(error).startswith('STOP_'):
                raise
            # Re-prove the exact known state BEFORE restoring anything/restarting.
            guard(value['appliedEnvSha256'], (None, compact))
            helper.restore_backup(Path(value['backupPath']), value['appliedEnvSha256'], value['oldEnvSha256'])
            need(digest(helper.read_private(helper.ENV_PATH)) == value['oldEnvSha256'], 'STOP_env_restore_failed')
            restored_config = object_capture(args + ['config', '--format', 'json'])
            validate_compose(restored_config, release, None)
            guard(value['oldEnvSha256'], (None, compact))
            capture(args + up, cap=65536, timeout=45)
            health()
            current = guard(value['oldEnvSha256'], (None,))
            need(current[ODOO]['State']['Running'] is True, 'STOP_recovery_not_running')
            raise Stop('activation_failed_env_restored_same_source_healthy') from None
    finally:
        if fd >= 0:
            os.close(fd)
        # Only remove our own unchanged generated overlay, never backup/receipt files.
        try:
            if helper.read_private(overlay) == yaml:
                overlay.unlink()
                helper.fsync_dir(Path('/run'))
        except Exception:
            pass


def main():
    try:
        need(len(sys.argv) == 1 and sys.platform.startswith('linux') and os.geteuid() == 0, 'linux_root_no_args_required')
        helper = load_configure()
        value = metadata(sys.stdin.buffer.read(4097), helper)
        with helper.production_lock():
            result = activate(value, helper)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Stop as error:
        print(json.dumps({'status': 'STOP', 'code': str(error)}))
    except Exception:
        print(json.dumps({'status': 'STOP', 'code': 'activation_failed_private_details_suppressed'}))
    return 1


if __name__ == '__main__':
    sys.exit(main())
