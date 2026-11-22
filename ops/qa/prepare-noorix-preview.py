#!/usr/bin/env python3
"""Prepare and validate configuration for the 20261121b isolated QA preview.

The builder is pure. The verifier reads the protected installed configuration
and inspects the fixed Docker runtime before the deployment wrapper can mutate it.
"""
import configparser
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
import urllib.request

PROJECT = 'baseer-qa-refresh-20261121b'
DATABASE = 'baseer_qa_20261121b'
NETWORK = PROJECT + '-isolated'
DB_IP = '172.31.136.2'
APP_IP = '172.31.136.3'
PG_IMAGE = 'sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'
ODOO_IMAGE = 'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
CONFIG = '/etc/baseer-qa/noorix-preview'
BASE = '/srv/baseer-qa/noorix-preview'
ADDONS = ('/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,'
          '/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19,'
          '/mnt/third-party-addons/oca_dms_19')
RUN_ID = '44943715853'
STATE = f'/srv/baseer-qa/refresh/20261121b-{RUN_ID}'
ORIGINAL = f'/srv/baseer-qa/releases/qa-refresh-20261121b-{RUN_ID}'
PROMOTED_COMMIT = '4a4f06cda34a5a6e2817e9e118f95c9945c4f2ab'
PROMOTED_CUSTOM_TREE = '1d39bf7ba774a9459c0dfed549c4f4b140e59011'
PROMOTED_THIRD_PARTY_TREE = '416a2abef9430037b6209cc9c1e4c6e1aa5d9a2a'
RECEIPT = 'QA_PROMOTED_SOURCE.json'


def _git_tree(path):
    """Hash the exact Git tree, ignoring only generated Python caches."""
    def walk(directory):
        entries = []
        for item in directory.iterdir():
            if item.name == '__pycache__' or item.suffix in ('.pyc', '.pyo'):
                continue
            info = item.lstat()
            require(info.st_uid == 0 and not info.st_mode & 0o022, 'unprotected release')
            name = os.fsencode(item.name)
            if stat.S_ISDIR(info.st_mode):
                digest = walk(item)
                if digest is None:
                    continue
                mode, order = b'40000', name + b'/'
            elif stat.S_ISREG(info.st_mode):
                content = item.read_bytes()
                digest = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).digest()
                mode, order = (b'100755' if info.st_mode & 0o111 else b'100644'), name
            else:
                raise ValueError('unexpected release object')
            entries.append((order, mode + b' ' + name + b'\0' + digest))
        if not entries:
            return None
        data = b''.join(value for _, value in sorted(entries))
        return hashlib.sha1(b'tree ' + str(len(data)).encode() + b'\0' + data).digest()
    require(path.is_dir() and not path.is_symlink(), 'invalid release tree')
    result = walk(path)
    require(result is not None, 'empty release tree')
    return result.hex()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate compose key')
        result[key] = value
    return result


def _assignments(text, shell=False):
    require(isinstance(text, str) and len(text) <= 65536 and '\x00' not in text, 'invalid configuration')
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        key, sep, raw = line.partition('=')
        require(sep and re.fullmatch(r'[A-Z_][A-Z_0-9]*', key) and key not in result,
                'invalid configuration assignment')
        if shell:
            # Accept only one literal value; reject shell metacharacters and
            # expansion even if a trusted config happened to quote them.
            require(not any(c in raw for c in '`$;|&<>\\'), 'unsafe shell assignment')
            try:
                tokens = shlex.split(raw, posix=True)
            except ValueError:
                raise ValueError('invalid shell assignment') from None
            require(len(tokens) <= 1, 'invalid shell assignment')
            value = tokens[0] if tokens else ''
        else:
            require(not any(c in raw for c in '\r\n'), 'invalid environment assignment')
            value = raw
        result[key] = value
    return result


def _original_compose(run_id):
    state = f'/srv/baseer-qa/refresh/20261121b-{run_id}'
    release = f'/srv/baseer-qa/releases/qa-refresh-20261121b-{run_id}'
    def service(image, ip):
        return {'image': image, 'restart': 'no', 'networks': {'isolated': {'ipv4_address': ip}},
                'dns': [DB_IP], 'sysctls': {'net.ipv6.conf.all.disable_ipv6': '1',
                                             'net.ipv6.conf.default.disable_ipv6': '1'}}
    db = service(PG_IMAGE, DB_IP)
    db.update(container_name=PROJECT + '-db-1', env_file=[state + '/pg.env'],
              volumes=[PROJECT + '-postgres:/var/lib/postgresql/data'])
    app = service(ODOO_IMAGE, APP_IP)
    app.update(container_name=PROJECT + '-odoo-1', entrypoint=['odoo'],
               env_file=[state + '/app.env'], command=['--config=/etc/odoo/odoo.conf'],
               ports=['127.0.0.1:18140:8069', '127.0.0.1:18141:8072'],
               volumes=[PROJECT + '-odoo:/var/lib/odoo', state + '/odoo.conf:/etc/odoo/odoo.conf:ro',
                        release + '/custom_addons:/mnt/baseer-addons:ro',
                        release + '/third_party_addons:/mnt/third-party-addons:ro'])
    return {'services': {'db': db, 'odoo': app},
            'volumes': {PROJECT + '-postgres': {'external': True}, PROJECT + '-odoo': {'external': True}},
            'networks': {'isolated': {'external': True, 'name': NETWORK}}}


def build_preview(compose_json, runtime_env, deploy_env, odoo_conf, run_id):
    """Return path -> contents; never emit, persist, or interpolate secrets.

    ``compose_json`` is the protected original refresh compose JSON, not an
    arbitrary compose specification. Its entire shape must match the source.
    """
    require(isinstance(run_id, str) and re.fullmatch(r'[1-9][0-9]{0,19}', run_id), 'invalid run id')
    require(isinstance(compose_json, str) and len(compose_json) <= 65536, 'invalid compose')
    try:
        compose = json.loads(compose_json, object_pairs_hook=_object)
    except (ValueError, TypeError):
        raise ValueError('invalid compose') from None
    require(compose == _original_compose(run_id), 'compose does not match protected refresh')

    env = _assignments(runtime_env)
    require(set(env) == {'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'HOST', 'USER', 'PASSWORD'}
            and env['POSTGRES_USER'] == env['USER'] == 'qa_runner' and env['HOST'] == 'db'
            and env['POSTGRES_DB'] == DATABASE and env['POSTGRES_PASSWORD'] == env['PASSWORD']
            and re.fullmatch('[0-9a-f]{64}', env['PASSWORD']), 'runtime identity mismatch')
    require(isinstance(odoo_conf, str) and len(odoo_conf) <= 65536, 'invalid odoo configuration')
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        parser.read_string(odoo_conf)
    except configparser.Error:
        raise ValueError('invalid odoo configuration') from None
    expected = {'addons_path': ADDONS, 'data_dir': '/var/lib/odoo', 'db_host': 'db', 'db_port': '5432',
                'db_user': 'qa_runner', 'db_password': env['PASSWORD'], 'db_name': DATABASE,
                'dbfilter': '^' + DATABASE + '$', 'list_db': 'False', 'proxy_mode': 'True',
                'workers': '2', 'max_cron_threads': '0', 'limit_time_cpu': '120',
                'limit_time_real': '240', 'http_port': '8069', 'gevent_port': '8072'}
    require(parser.sections() == ['options'] and not parser.defaults(), 'invalid odoo section')
    options = dict(parser['options'])
    require(set(options) == set(expected) | {'admin_passwd'} and
            all(options.get(k) == v for k, v in expected.items()) and
            options['admin_passwd'].startswith('$pbkdf2-sha512$600000$'), 'odoo identity mismatch')

    deploy = _assignments(deploy_env, shell=True)
    require(deploy.get('QA_ENVIRONMENT') == 'qa' and deploy.get('QA_BASE') == '/srv/baseer-qa'
            and all(key.startswith('QA_') for key in deploy), 'not a QA configuration')
    deploy.update(QA_BASE='/srv/baseer-qa', QA_DATABASE=DATABASE, QA_DB_CONTAINER=PROJECT + '-db-1',
                  QA_ODOO_VOLUME=PROJECT + '-odoo', QA_COMPOSE_PROJECT=PROJECT,
                  QA_COMPOSE_FILE=CONFIG + '/compose.yaml', QA_ENV_FILE=CONFIG + '/runtime.env',
                  QA_LOGIN_URL='http://127.0.0.1:18140/web/login', QA_ADDONS_PATH=ADDONS)
    result = copy.deepcopy(compose)
    app = result['services']['odoo']
    app['env_file'] = [CONFIG + '/runtime.env']
    app['volumes'] = [PROJECT + '-odoo:/var/lib/odoo', CONFIG + '/odoo.conf:/etc/odoo/odoo.conf:ro',
                      BASE + '/current/custom_addons:/mnt/baseer-addons:ro',
                      BASE + '/current/third_party_addons:/mnt/third-party-addons:ro']
    # JSON is a YAML subset and avoids a YAML parser dependency.
    return {CONFIG + '/compose.yaml': json.dumps(result, sort_keys=True, indent=2) + '\n',
            CONFIG + '/runtime.env': runtime_env,
            CONFIG + '/deploy.env': ''.join(k + '=' + shlex.quote(v) + '\n' for k, v in sorted(deploy.items())),
            CONFIG + '/odoo.conf': odoo_conf}


def protected_text(path, mode=0o600, gid=0):
    path = Path(path)
    require(path.resolve(strict=True) == path, 'redirected configuration path')
    for parent in (path.parent, *path.parent.parents):
        info = parent.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'writable configuration parent')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and (info.st_uid, info.st_gid) == (0, gid)
                and stat.S_IMODE(info.st_mode) == mode, 'unprotected configuration')
        data = stream.read(65537)
    require(len(data) <= 65536, 'oversized configuration')
    return data.decode('utf-8')


def docker(*args):
    return subprocess.run(['/usr/bin/docker', *args], check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, text=True, timeout=30).stdout


def expected_files():
    return build_preview(protected_text(STATE + '/compose.json'),
                         protected_text(STATE + '/app.env'),
                         protected_text('/etc/baseer-qa/deploy.env'),
                         protected_text(STATE + '/odoo.conf', 0o640, 101), RUN_ID)


def provision():
    import fcntl

    # Use the same lock order as the approved refresh wrapper. No primary
    # configuration, Odoo container, proxy route or database is changed here.
    with ExitStack() as stack:
        for lock in ('baseer-qa-refresh', 'baseer-qa-deploy', 'baseer-qa-release-poller'):
            fd = os.open('/var/lock/' + lock + '.lock', os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                    'unsafe QA lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        output = expected_files()
        require(Path(ORIGINAL).resolve(strict=True) == Path(ORIGINAL), 'redirected preview source')
        target_dirs = (Path(BASE), Path(CONFIG))
        require(not any(os.path.lexists(path) for path in target_dirs), 'preview already provisioned')
        for path in target_dirs:
            parent = path.parent
            require(parent.resolve(strict=True) == parent and parent.stat().st_uid == 0
                    and not parent.stat().st_mode & 0o022, 'unsafe preview parent')
        created = []
        try:
            for path in target_dirs:
                path.mkdir(mode=0o700)
                created.append(path)
            for name, data in output.items():
                path = Path(name)
                with path.open('xb') as stream:
                    created.append(path)
                    os.fchmod(stream.fileno(), 0o640 if path.name == 'odoo.conf' else 0o600)
                    if path.name == 'odoo.conf':
                        os.fchown(stream.fileno(), 0, 101)
                    stream.write(data.encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
            link = Path(BASE) / 'current'
            link.symlink_to(ORIGINAL, target_is_directory=True)
            created.append(link)
            verify_installed()
        except BaseException:
            for path in reversed(created):
                if not path.is_symlink() and path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()
            raise


def _promoted_source(current, *, allow_unrecorded=False):
    source = current.resolve(strict=True)
    match = re.fullmatch(r'/srv/baseer-qa/releases/([0-9a-f]{12})-run-[0-9]+-[0-9]{8}T[0-9]{6}Z', str(source))
    require(current.is_symlink() and match, 'unexpected promoted source pointer')
    commit = protected_text(source / 'RELEASE_COMMIT', 0o644).strip()
    require(re.fullmatch('[0-9a-f]{40}', commit) and commit.startswith(match.group(1)),
            'unexpected promoted source marker')
    custom = _git_tree(source / 'custom_addons')
    third = _git_tree(source / 'third_party_addons')
    receipt_path = source / RECEIPT
    if os.path.lexists(receipt_path):
        try:
            receipt = json.loads(protected_text(receipt_path), object_pairs_hook=_object)
        except (TypeError, ValueError):
            raise ValueError('invalid promoted source receipt') from None
        require(type(receipt) is dict and set(receipt) == {'version', 'database', 'commit', 'custom_tree',
                                                          'third_party_tree', 'report_version'} and
                type(receipt['version']) is int and receipt['version'] == 1 and
                receipt['database'] == DATABASE and receipt['commit'] == commit and
                receipt['custom_tree'] == custom and receipt['third_party_tree'] == third and
                isinstance(receipt['report_version'], str) and
                re.fullmatch(r'19\.0\.[0-9]+(?:\.[0-9]+){1,3}', receipt['report_version']),
                'promoted source receipt mismatch')
        return source, receipt
    if commit == PROMOTED_COMMIT:
        require(custom == PROMOTED_CUSTOM_TREE and third == PROMOTED_THIRD_PARTY_TREE,
                'promoted source tree differs')
        version = '19.0.1.1.6'
    else:
        require(allow_unrecorded, 'promoted source receipt missing')
        version = None
    return source, {'version': 1, 'database': DATABASE, 'commit': commit, 'custom_tree': custom,
                    'third_party_tree': third, 'report_version': version}


def verify_installed(*, promoted=False, phase='running', allow_unrecorded=False):
    require(phase in ('static', 'db', 'running'), 'invalid verification phase')
    base = Path(BASE)
    require(base.resolve(strict=True) == base and base.is_dir(), 'redirected preview directory')
    for parent in (base, *base.parents):
        info = parent.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'writable preview path')
    current = base / 'current'
    original = Path(ORIGINAL)
    source = current.resolve(strict=True)
    receipt = None
    if promoted:
        source, receipt = _promoted_source(current, allow_unrecorded=allow_unrecorded)
    else:
        require(current.is_symlink() and source == original and original.is_dir(),
                'unexpected preview source pointer')
    pg = _assignments(protected_text(STATE + '/pg.env'))
    require(set(pg) == {'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB'} and
            pg['POSTGRES_USER'] == 'qa_refresh_admin' and pg['POSTGRES_DB'] == 'postgres' and
            re.fullmatch('[0-9a-f]{64}', pg['POSTGRES_PASSWORD']), 'unexpected preview database process environment')
    for path, expected in expected_files().items():
        require(protected_text(path, 0o640, 101) == expected if path.endswith('/odoo.conf')
                else protected_text(path) == expected, 'generated preview files differ')
    items = json.loads(docker('inspect', PROJECT + '-db-1', PROJECT + '-odoo-1'))
    expectations = (
        (PROJECT + '-db-1', DB_IP, PG_IMAGE, {}, '/var/lib/postgresql/data', PROJECT + '-postgres'),
        (PROJECT + '-odoo-1', APP_IP, ODOO_IMAGE, {
            '8069/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18140'}],
            '8072/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '18141'}],
        }, '/var/lib/odoo', PROJECT + '-odoo'),
    )
    require(len(items) == len(expectations), 'unexpected preview containers')
    for item, (name, ip, image, ports, destination, volume) in zip(items, expectations):
        networks = item['NetworkSettings']['Networks']
        host = item['HostConfig']
        mounts = {m['Destination']: m for m in item['Mounts']}
        running = item['State']['Running']
        address = networks.get(NETWORK, {})
        expected_running = phase == 'running' or (phase == 'db' and name.endswith('-db-1'))
        configured_ip = (address.get('IPAMConfig') or {}).get('IPv4Address')
        require(item['Name'] == '/' + name and item['Image'] == image
                and (not expected_running or running)
                and set(networks) == {NETWORK} and configured_ip == ip
                and (not running or address['IPAddress'] == ip)
                and (host['PortBindings'] or {}) == ports
                and host['RestartPolicy']['Name'] == 'no' and host['Dns'] == [DB_IP]
                and not host['Privileged'] and destination in mounts
                and mounts[destination].get('Name') == volume and mounts[destination]['Type'] == 'volume'
                and mounts[destination]['RW'],
                'unexpected preview container identity')
        mounts.pop(destination)
        if name == PROJECT + '-odoo-1':
            override = mounts.pop('/mnt/extra-addons', None)
            if override is not None:
                require(override['Type'] == 'volume' and re.fullmatch('[0-9a-f]{64}', override['Name']),
                        'unexpected vendor addon mount')
                volume = json.loads(docker('volume', 'inspect', override['Name']))
                mountpoint = Path('/var/lib/docker/volumes') / override['Name'] / '_data'
                require(len(volume) == 1 and volume[0]['Name'] == override['Name'] and
                        volume[0]['Driver'] == 'local' and volume[0]['Mountpoint'] == str(mountpoint) and
                        mountpoint.resolve(strict=True) == mountpoint and mountpoint.is_dir() and
                        not any(mountpoint.iterdir()), 'vendor addon volume is not empty')
            expected_mounts = {'/etc/odoo/odoo.conf': (CONFIG if promoted else STATE) + '/odoo.conf',
                               '/mnt/baseer-addons': str(source) + '/custom_addons',
                               '/mnt/third-party-addons': str(source) + '/third_party_addons'}
            require(set(mounts) == set(expected_mounts) and all(
                mounts[key]['Type'] == 'bind' and not mounts[key]['RW'] and
                Path(mounts[key]['Source']).resolve(strict=True) == Path(source)
                for key, source in expected_mounts.items()), 'running preview source mount differs')
        else:
            require(not mounts, 'unexpected database mount')
    if phase == 'static':
        return

    def read_query(query):
        return docker('exec', '--env', 'PGOPTIONS=-c default_transaction_read_only=on', PROJECT + '-db-1',
                      '/bin/sh', '-c', 'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "$2"',
                      'sh', DATABASE, query).strip()

    query = ("SELECT current_database() = 'baseer_qa_20261121b' "
             "AND EXISTS (SELECT FROM ir_config_parameter "
             "WHERE key = 'database.is_neutralized' AND value = 'true') "
             "AND NOT EXISTS (SELECT FROM ir_cron WHERE active)")
    require(read_query(query) == 't', 'preview database identity or neutralization mismatch')
    if promoted:
        report_version = read_query("SELECT latest_version FROM ir_module_module WHERE name = "
                                    "'baseer_profit_loss_report' AND state = 'installed'")
        require(re.fullmatch(r'19\.0\.[0-9]+(?:\.[0-9]+){1,3}', report_version) and
                (receipt['report_version'] is None or receipt['report_version'] == report_version),
                'promoted report module is not installed')
        receipt['report_version'] = report_version
    predicates = {
        'ir_mail_server': 'active', 'fetchmail_server': 'active', 'baseer_print_agent': 'active',
        'baseer_bwork_push_device': 'active', 'baseer_bank_sms_device': 'active',
        'payment_provider': "state <> 'disabled'",
        'res_users_apikeys': 'expiration_date IS NULL OR expiration_date > now()',
        'pos_config': 'baseer_direct_print_enabled OR baseer_native_receipt_enabled OR baseer_print_session_close_report',
    }
    installed = set(read_query("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").splitlines())
    for table, condition in predicates.items():
        if table in installed:
            require(read_query(f'SELECT NOT EXISTS (SELECT FROM "{table}" WHERE {condition})') == 't',
                    'preview outgoing integration is enabled')
    return receipt


def verify_promoted():
    """Verify the exact reviewed composite and both running QA containers."""
    return verify_installed(promoted=True)


def record_promoted():
    """Called only by the protected, policy-checked QA deploy while locked."""
    receipt = verify_installed(promoted=True, allow_unrecorded=True)
    source, confirmed = _promoted_source(Path(BASE) / 'current', allow_unrecorded=True)
    require(all(confirmed[key] == receipt[key] for key in
                ('version', 'database', 'commit', 'custom_tree', 'third_party_tree')),
            'source changed before receipt')
    path = source / RECEIPT
    if os.path.lexists(path):
        require(json.loads(protected_text(path), object_pairs_hook=_object) == receipt,
                'existing source receipt differs')
        return
    data = (json.dumps(receipt, sort_keys=True, separators=(',', ':')) + '\n').encode('ascii')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    directory_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def boot_promoted():
    """Start only previously verified preview containers; never change routes."""
    import fcntl
    with ExitStack() as stack:
        for lock in ('baseer-qa-refresh', 'baseer-qa-deploy', 'baseer-qa-release-poller'):
            fd = os.open('/var/lock/' + lock + '.lock', os.O_CREAT | os.O_NOFOLLOW | os.O_RDWR, 0o600)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                    'unsafe QA lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run(['/usr/bin/systemctl', 'is-active', '--quiet', PROJECT + '-firewall.service'],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        verify_installed(promoted=True, phase='static')
        db, app = PROJECT + '-db-1', PROJECT + '-odoo-1'
        states = json.loads(docker('inspect', db, app))
        require(len(states) == 2, 'preview containers missing')
        db_was_running, app_was_running = (item['State']['Running'] for item in states)
        if not db_was_running:
            docker('start', db)
        for attempt in range(30):
            try:
                verify_installed(promoted=True, phase='db')
                break
            except (ValueError, subprocess.SubprocessError):
                if attempt == 29:
                    raise
                time.sleep(1)
        try:
            if not app_was_running:
                docker('start', app)
            verify_promoted()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(30):
                try:
                    with opener.open('http://127.0.0.1:18140/web/login', timeout=3) as response:
                        require(response.status == 200, 'preview login unavailable')
                    break
                except (OSError, ValueError):
                    if attempt == 29:
                        raise
                    time.sleep(1)
        except BaseException:
            if not app_was_running:
                docker('stop', app)
            raise


if __name__ == '__main__':
    os.umask(0o077)
    if os.geteuid() != 0 or sys.argv[1:] not in (['--verify-installed'], ['--verify-promoted'], ['--record-promoted'], ['--boot-promoted'], ['--provision']):
        sys.exit('preview verification requires the protected QA wrapper')
    try:
        if sys.argv[1] == '--provision':
            provision()
        elif sys.argv[1] == '--verify-promoted':
            verify_promoted()
        elif sys.argv[1] == '--record-promoted':
            record_promoted()
        elif sys.argv[1] == '--boot-promoted':
            boot_promoted()
        else:
            verify_installed()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not expose Docker inspect or configuration bytes on a failure.
        sys.exit('preview verification failed')
