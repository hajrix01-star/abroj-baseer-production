#!/usr/bin/env python3
"""Prepare and validate configuration for the 20261121b isolated QA preview.

The builder is pure. The verifier reads the protected installed configuration
and inspects the fixed Docker runtime before the deployment wrapper can mutate it.
"""
import configparser
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

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


def verify_installed():
    base = Path(BASE)
    require(base.resolve(strict=True) == base and base.is_dir(), 'redirected preview directory')
    for parent in (base, *base.parents):
        info = parent.stat()
        require(info.st_uid == 0 and not info.st_mode & 0o022, 'writable preview path')
    current = base / 'current'
    original = Path(ORIGINAL)
    require(current.is_symlink() and current.resolve(strict=True) == original and original.is_dir(),
            'unexpected preview source pointer')
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
        mounts = [m for m in item['Mounts'] if m['Destination'] == destination]
        require(item['Name'] == '/' + name and item['Image'] == image and item['State']['Running']
                and set(networks) == {NETWORK} and networks[NETWORK]['IPAddress'] == ip
                and (host['PortBindings'] or {}) == ports
                and host['RestartPolicy']['Name'] == 'no' and host['Dns'] == [DB_IP]
                and not host['Privileged'] and len(mounts) == 1
                and mounts[0].get('Name') == volume and mounts[0]['Type'] == 'volume',
                'unexpected preview container identity')
    query = ("SELECT current_database() = 'baseer_qa_20261121b' "
             "AND EXISTS (SELECT FROM ir_config_parameter "
             "WHERE key = 'database.is_neutralized' AND value = 'true') "
             "AND NOT EXISTS (SELECT FROM ir_cron WHERE active)")
    result = docker('exec', PROJECT + '-db-1', '/bin/sh', '-c',
                    'exec psql -XAt -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "$2"',
                    'sh', DATABASE, query)
    require(result.strip() == 't', 'preview database identity or neutralization mismatch')


if __name__ == '__main__':
    os.umask(0o077)
    if os.geteuid() != 0 or sys.argv[1:] not in (['--verify-installed'], ['--provision']):
        sys.exit('preview verification requires the protected QA wrapper')
    try:
        if sys.argv[1] == '--provision':
            provision()
        else:
            verify_installed()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not expose Docker inspect or configuration bytes on a failure.
        sys.exit('preview verification failed')
