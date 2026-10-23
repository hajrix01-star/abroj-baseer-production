#!/usr/bin/env python3
"""Bounded root-only QA refresh engine. Invoked only by the signed request wrapper.

Resumes only a reviewed checkpoint before neutralization, with an unchanged baseline;
old volumes and every protected archive are retained. No network/provider calls.
"""
import contextlib
import base64
import configparser
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

BASE = Path('/srv/baseer-qa')
CONFIG = Path('/etc/baseer-qa')
LIVE = Path('/srv/abroj-baseer-production/current')
LPG, LODOO = 'baseer-odoo-prod-db-1', 'baseer-odoo-prod-odoo-1'
QPG = 'baseer-live-qa-clean-20260928-db-1'
QODOO = 'baseer-live-qa-clean-20260928-odoo-1'
LDB, QDB = 'baseer_prod', 'baseer_live_qa_clean_20260928'
LVO, QVO = 'baseer-odoo-prod-odoo-data', 'baseer-live-qa-clean-20260928-odoo'
PROJECT, DB = 'baseer-qa-refresh-20261023', 'baseer_qa_20261023'
PG, ODOO = PROJECT + '-db-1', PROJECT + '-odoo-1'
NETWORK, SUBNET, PGIP = PROJECT + '-isolated', '172.31.134.0/28', '172.31.134.2'
ODOO_IMAGE = 'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
PG_IMAGE = 'sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'
TIMER = 'baseer-qa-release-poller.timer'
ADDONS = '/usr/lib/python3/dist-packages/odoo/addons,/mnt/baseer-addons,/mnt/third-party-addons/erp_heritage_19,/mnt/third-party-addons/odoomates_19,/mnt/third-party-addons/oca_dms_19'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(args, data=None, output=None, timeout=1800, check=True):
    """No shell; stderr may contain credentials, so never echo it to callers."""
    with contextlib.ExitStack() as stack:
        target = stack.enter_context(open(output, 'wb')) if output else subprocess.PIPE
        result = subprocess.run([str(x) for x in args], input=data, stdout=target,
                                stderr=subprocess.PIPE, timeout=timeout)
    require(not check or result.returncode == 0, 'command failed: ' + str(args[0]))
    if output:
        os.chmod(output, 0o600)
        return None
    return result.stdout.decode() if result.returncode == 0 else None


def save(path, value):
    path = Path(path)
    require(not path.is_symlink(), 'unsafe output symlink')
    content = json.dumps(value, sort_keys=True, indent=2) if not isinstance(value, str) else value
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(content + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def tree_hash(root):
    values = {}
    for path in sorted(Path(root).rglob('*')):
        require(not path.is_symlink(), 'source symlink rejected')
        if path.is_file():
            values[str(path.relative_to(root))] = digest(path)
    return values


def inspect(name, kind='container'):
    return json.loads(run(['docker', kind, 'inspect', name]))[0]


def network_ranges(network):
    # Docker's host/none networks explicitly return Config=null.
    return (network.get('IPAM') or {}).get('Config') or []


def volume(name):
    item = inspect(name, 'volume')
    require(item['Driver'] == 'local', 'nonlocal volume')
    path = Path(item['Mountpoint'])
    require(path.is_dir() and path.is_absolute(), 'missing volume directory')
    return path


def env_file(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if line and not line.startswith('#'):
            key, value = line.split('=', 1)
            require(re.fullmatch(r'[A-Z_][A-Z_0-9]*', key), 'unsafe env key')
            # Existing deploy.env is a shell file; values may be simply quoted.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            require('\n' not in value and not any(c in value for c in '`$'), 'unsafe env value')
            result[key] = value
    return result


def pg_user(container):
    entries = inspect(container)['Config']['Env']
    return dict(entry.split('=', 1) for entry in entries if '=' in entry)['POSTGRES_USER']


def sql(container, database, statement):
    require(re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*', database), 'unsafe database name')
    return run(['docker', 'exec', '-i', container, 'psql', '-X', '-v', 'ON_ERROR_STOP=1',
                '-U', pg_user(container), '-d', database, '-At', '-c', statement])


def schema(container, database):
    rows = sql(container, database, "SELECT table_name,column_name,is_nullable FROM information_schema.columns WHERE table_schema='public' ORDER BY 1,2")
    result = {}
    for line in rows.splitlines():
        table, column, nullable = line.split('|')
        require(all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name) for name in (table, column)),
                'unsafe schema identifier')
        result.setdefault(table, {})[column] = nullable == 'YES'
    return result


def fingerprints(container, database, protected=True):
    """Ordered hashes and counts; secret/user rows never leave PostgreSQL."""
    tables = schema(container, database)
    selected = [t for t in tables if not protected or t.startswith(
        ('account_', 'pos_', 'purchase_', 'stock_', 'hr_', 'res_company', 'abroj_',
         'baseer_bwork_membership', 'baseer_bwork_binding',
         'res_users', 'res_groups', 'res_partner', 'ir_module_module', 'ir_attachment'))]
    excluded = {
        'pos_config': ['baseer_direct_print_enabled', 'baseer_native_receipt_enabled',
                       'baseer_print_session_close_report', 'access_token'],
        'res_company': ['baseer_receipt_profile_enabled', 'baseer_receipt_profile_close_report'],
        'res_users': ['oauth_access_token', 'oauth_refresh_token'],
        'res_users_settings': ['google_calendar_rtoken', 'google_calendar_token', 'google_synchronization_stopped'],
        'res_users_apikeys': ['expiration_date'],
    } if protected else {}
    values = {}
    for table in sorted(selected):
        keys = excluded.get(table, [])
        minus = ''.join(" - '" + key + "'" for key in keys)
        query = (f"SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM "
                 f"(SELECT md5((to_jsonb(t){minus})::text) h FROM \"{table}\" t) s")
        values[table] = sql(container, database, query).strip()
    return values


def neutral_sql(tables):
    changes = []
    def update(table, fields, where='TRUE'):
        if table not in tables:
            return
        assignments = []
        for field, expression in fields.items():
            if field in tables[table]:
                if expression == 'NULL' and not tables[table][field]:
                    expression = "'qa-revoked-' || id::text"  # required unique token
                assignments.append('"' + field + '"=' + expression)
        if assignments:
            changes.append(f'UPDATE "{table}" SET ' + ','.join(assignments) + ' WHERE ' + where + ';')
    for table in ('ir_cron', 'ir_mail_server', 'fetchmail_server', 'auth_oauth_provider'):
        update(table, {'active': 'FALSE'})
    update('payment_provider', {'state': "'disabled'"})
    update('baseer_print_agent', {'active': 'FALSE', 'state': "'revoked'", **dict.fromkeys(
        ['token_fingerprint', 'pairing_fingerprint', 'pairing_expires_at',
         'runtime_instance_id', 'runtime_lease_expires_at'], 'NULL')})
    update('baseer_print_job', {'state': "'cancelled'", 'lease_token': 'NULL',
                              'lease_expires_at': 'NULL'}, "state IN ('pending','leased')")
    update('baseer_bwork_push_device', {'active': 'FALSE', 'fcm_token': 'NULL'})
    update('baseer_bank_sms_device', {'active': 'FALSE', 'secret_salt': 'NULL', 'secret_hash': 'NULL'})
    update('baseer_bank_sms_pairing', {'token': "'qa-revoked-' || id::text", 'state': "'expired'",
                                     'expires_at': "'2000-01-01'::timestamp"})
    update('baseer_bwork_mobile_upload_grant', {'secret_hash': "repeat('0',64)"})
    update('pos_config', dict.fromkeys(['baseer_direct_print_enabled', 'baseer_native_receipt_enabled',
                                      'baseer_print_session_close_report'], 'FALSE'))
    update('pos_config', {'access_token': "'qa-revoked-' || id::text"})
    update('res_company', dict.fromkeys(['baseer_receipt_profile_enabled',
                                       'baseer_receipt_profile_close_report'], 'FALSE'))
    update('res_users_apikeys', {'expiration_date': "'2000-01-01'::timestamp"})
    update('res_users_settings', {'google_synchronization_stopped': 'TRUE'})
    credential_fields = ['gmail_token', 'gmail_refresh_token', 'gmail_access_token',
                         'microsoft_outlook_token', 'microsoft_outlook_refresh_token',
                         'google_calendar_token', 'google_calendar_rtoken', 'oauth_access_token',
                         'oauth_refresh_token', 'token_ciphertext', 'token_nonce', 'token_key_version',
                         'token_expires_at', 'smtp_user', 'smtp_pass']
    for table in ('res_users', 'res_users_settings', 'ir_mail_server', 'fetchmail_server',
                  'baseer_gads_connection', 'baseer_gbp_connection'):
        update(table, dict.fromkeys(credential_fields, 'NULL'))
    for table in ('baseer_gads_connection', 'baseer_gbp_connection'):
        update(table, {'state': "'disabled'", 'writer_enabled': 'FALSE'})
    # Business fingerprint/HMAC parameters are deliberately preserved.
    changes.append("UPDATE ir_config_parameter SET value='' WHERE key ~* "
                   "'(^|[._])(webhook|api_token|access_token|refresh_token|client_secret)([._]|$)';")
    for key, value in {'database.uuid': str(uuid.uuid4()), 'database.secret': secrets.token_hex(32),
                       'web.base.url': 'https://baseer-live-qa.tail938958.ts.net',
                       'web.base.url.freeze': 'True'}.items():
        changes.append("INSERT INTO ir_config_parameter(key,value) VALUES ('" + key + "','" + value +
                       "') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;")
    return 'BEGIN;\n' + '\n'.join(changes) + '\nCOMMIT;'


class Refresh:
    def __init__(self, run_id, live_sha, qa_sha):
        require(re.fullmatch(r'[1-9][0-9]{0,19}', run_id), 'invalid run id')
        require(all(re.fullmatch('[0-9a-f]{40}', x) for x in (live_sha, qa_sha)), 'invalid source SHA')
        self.state = BASE / 'refresh' / ('20261023-' + run_id)
        self.live_sha, self.qa_sha = live_sha, qa_sha
        self.release = BASE / 'releases' / ('qa-refresh-20261023-' + run_id)
        self.compose = self.state / 'compose.json'
        self.config = self.state / 'odoo.conf'

    def start(self, stage):
        if stage == 'prepare':
            self.state.mkdir(mode=0o700, parents=True, exist_ok=False)
        require(self.state.is_dir() and not self.state.is_symlink(), 'missing protected state')
        require(self.state.stat().st_uid == 0 and self.state.stat().st_mode & 0o777 == 0o700,
                'state owner/mode invalid')
        if stage == 'switch':
            require((self.state / 'prepare.receipt.json').exists(), 'prepare not accepted')
            review = self.state / 'review.accepted'
            require(review.stat().st_uid == 0 and review.stat().st_mode & 0o777 == 0o600 and not review.is_symlink(), 'unsafe review receipt')
            require(review.read_text().strip() == digest(self.state / 'prepare.receipt.json'),
                    'independent review receipt missing')
            prepared = json.loads((self.state / 'prepare.receipt.json').read_text())
            require(prepared['reviewed_revision'] == os.environ['QA_REFRESH_REVIEWED_REVISION'] and
                    prepared['signed_tag'] == os.environ['QA_REFRESH_SIGNED_TAG'], 'reviewed request changed')
        intent = self.state / (stage + '.intent.json')
        require(not intent.exists(), 'stage already attempted; no automatic replay')
        save(intent, {'live_sha': self.live_sha, 'qa_sha': self.qa_sha, 'time': time.time()})

    def receipt(self, stage, value):
        require(not (self.state / (stage + '.receipt.json')).exists(), 'receipt already exists')
        value.update(reviewed_revision=os.environ.get('QA_REFRESH_REVIEWED_REVISION'),
                     signed_tag=os.environ.get('QA_REFRESH_SIGNED_TAG'))
        save(self.state / (stage + '.receipt.json'), value)

    def guards(self, switched=False):
        require((LIVE / 'RELEASE_COMMIT').read_text().strip() == self.live_sha, 'LIVE source moved')
        require((BASE / 'current' / 'RELEASE_COMMIT').read_text().strip() ==
                (self.live_sha if switched else self.qa_sha), 'QA source moved')
        for name, expected in ((LPG, PG_IMAGE), (LODOO, ODOO_IMAGE), (QPG, PG_IMAGE), (QODOO, ODOO_IMAGE)):
            item = inspect(name)
            require(item['Image'] == expected, 'runtime image mismatch')
            if name != QODOO or not switched:
                require(item['State']['Running'], 'source container not running')

    def archive(self, name, path):
        target = self.state / (name + '.tar')
        run(['tar', '--numeric-owner', '-C', path, '-cf', target, '.'])
        os.chmod(target, 0o600)
        return digest(target)

    def dump(self, container, database, name):
        target = self.state / (name + '.dump')
        run(['docker', 'exec', container, 'pg_dump', '-Fc', '--no-owner', '--no-privileges',
             '-U', pg_user(container), '-d', database], output=target)
        run(['docker', 'exec', '-i', container, 'pg_restore', '--list'], data=target.read_bytes())
        return digest(target)

    def restore(self, database, dump):
        run(['docker', 'exec', PG, 'createdb', '-U', pg_user(PG), '-O', 'qa_runner', database])
        run(['docker', 'exec', '-i', PG, 'pg_restore', '-U', pg_user(PG), '--role=qa_runner',
             '--no-owner', '--no-privileges', '--exit-on-error', '-d', database], data=Path(dump).read_bytes())

    def compose_run(self, *args):
        return run(['docker', 'compose', '-p', PROJECT, '-f', self.compose, *args])

    def firewall(self):
        # Only this new subnet is matched. No existing network/LIVE rule is changed.
        script = '#!/bin/sh\nset -eu\n'
        for parent, chain in (('DOCKER-USER', 'BAS_QAR_FWD'), ('INPUT', 'BAS_QAR_HOST')):
            script += f'iptables -w -N {chain} 2>/dev/null || true\niptables -w -F {chain}\n'
            script += f'iptables -w -A {chain} -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN\n'
            if parent == 'DOCKER-USER':
                script += f'iptables -w -A {chain} -d {PGIP} -p tcp --dport 5432 -j RETURN\n'
            script += f'iptables -w -A {chain} -j DROP\n'
            script += f'iptables -w -C {parent} -s {SUBNET} -j {chain} 2>/dev/null || iptables -w -I {parent} 1 -s {SUBNET} -j {chain}\n'
        path = Path('/usr/local/sbin/baseer-qa-refresh-firewall')
        save(path, script)
        os.chmod(path, 0o700)
        save('/etc/systemd/system/baseer-qa-refresh-firewall.service',
             '[Unit]\nRequires=docker.service\nAfter=docker.service\nBefore=baseer-qa-refresh.service\n'
             '[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=' + str(path) + '\n'
             '[Install]\nWantedBy=multi-user.target')
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', 'baseer-qa-refresh-firewall.service'])
        run([path])

    def compose_config(self, source, port, config):
        def service(image, address):
            return {'image': image, 'restart': 'no', 'networks': {'isolated': {'ipv4_address': address}},
                    'sysctls': {'net.ipv6.conf.all.disable_ipv6': '1',
                                'net.ipv6.conf.default.disable_ipv6': '1'}}
        pg = service(PG_IMAGE, PGIP)
        pg.update(container_name=PG, env_file=[str(self.state / 'pg.env')],
                  volumes=[PROJECT + '-postgres:/var/lib/postgresql/data'])
        odoo = service(ODOO_IMAGE, '172.31.134.3')
        odoo.update(container_name=ODOO, entrypoint=['odoo'],
                    env_file=[str(CONFIG / 'runtime.env') if port == 18134 else str(self.state / 'app.env')],
                    command=['--config=/etc/odoo/odoo.conf'],
                    ports=[f'127.0.0.1:{port}:8069', f'127.0.0.1:{port+1}:8072'],
                    volumes=[PROJECT + '-odoo:/var/lib/odoo',
                             str(config) + ':/etc/odoo/odoo.conf:ro',
                             str(source) + '/custom_addons:/mnt/baseer-addons:ro',
                             str(source) + '/third_party_addons:/mnt/third-party-addons:ro'])
        return {'services': {'db': pg, 'odoo': odoo},
                'volumes': {PROJECT + '-postgres': {'external': True}, PROJECT + '-odoo': {'external': True}},
                'networks': {'isolated': {'external': True, 'name': NETWORK}}}

    def attachments(self):
        rows = sql(PG, DB, "SELECT json_build_array(id,store_fname,checksum,file_size)::text FROM ir_attachment WHERE store_fname IS NOT NULL ORDER BY id")
        root = volume(PROJECT + '-odoo') / 'filestore' / DB
        values = []
        for row in rows.splitlines():
            ident, name, checksum, size = json.loads(row)
            require(isinstance(name, str) and re.fullmatch('[0-9a-f]{2}/[0-9a-f]{40}', name), 'unsafe attachment path')
            path = root / name
            require(path.is_file() and not path.is_symlink(), 'referenced attachment missing')
            sha1 = hashlib.sha1(path.read_bytes()).hexdigest()
            require(size is not None and path.stat().st_size == size, 'attachment size mismatch')
            require(checksum is None or sha1 == checksum, 'attachment checksum mismatch')
            values.append([ident, name, sha1, size, checksum is None])
        save(self.state / 'attachments.json', values)
        return len(values)

    def namespace_test(self, proof_name='network-proof.json'):
        live_ip = next(iter(inspect(LPG)['NetworkSettings']['Networks'].values()))['IPAddress']
        require(not inspect(NETWORK, 'network').get('EnableIPv6'), 'network IPv6 enabled')
        helper = PROJECT + '-tcp-control'
        require(run(['docker', 'container', 'inspect', helper], check=False) is None, 'TCP control already exists')
        with socket.socket() as listener:
            listener.bind(('172.31.134.1', 0))
            listener.listen(4)
            host_port = listener.getsockname()[1]
            server = 'import socket; s=socket.socket(); s.bind(("0.0.0.0",16443)); s.listen(8)\nwhile True: c,a=s.accept(); c.close()'
            run(['docker', 'run', '-d', '--name', helper, '--network', NETWORK, '--ip', '172.31.134.5',
                 '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1', '--entrypoint', 'python3', ODOO_IMAGE, '-c', server])
            try:
                targets = [('host', '172.31.134.1', host_port), ('public', '1.1.1.1', 443),
                           ('live_pg', live_ip, 5432), ('internal_qa_peer', '172.31.134.5', 16443)]
                for name, host, port in targets:
                    for attempt in range(10):
                        try:
                            # The host's gateway belongs to the blocked QA subnet.
                            # Bind this local positive control to loopback so it
                            # proves the listener without exercising container rules.
                            source = ('127.0.0.1', 0) if name == 'host' else None
                            with socket.create_connection((host, port), timeout=3, source_address=source):
                                break
                        except OSError:
                            require(attempt < 9, 'host TCP positive control unavailable: ' + name)
                            time.sleep(0.2)
                self.namespace_probe([('database', PGIP, 5432, True)] +
                                     [(name, host, port, name == 'internal_qa_peer') for name, host, port in targets], proof_name)
            finally:
                run(['docker', 'rm', '-f', helper])

    def namespace_probe(self, targets, proof_name='network-proof.json'):
        code = ("import socket,json,pathlib; r={}; targets=" + repr(targets) + ";\n"
            "for name,host,port,expected in targets:\n"
            " s=socket.socket(); s.settimeout(2)\n"
            " try: s.connect((host,port)); ok=True\n"
            " except OSError: ok=False\n"
            " finally: s.close()\n"
            " r[name]=ok; assert ok==expected,name\n"
            "assert pathlib.Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip()=='1'\n"
            "r['ipv6_disabled']=True\n"
            "print(json.dumps(r))")
        result = run(['docker', 'run', '--rm', '--network', NETWORK, '--ip', '172.31.134.4',
                      '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1', '--entrypoint', 'python3', ODOO_IMAGE, '-c', code])
        path = self.state / proof_name
        if path.exists():
            require(json.loads(path.read_text()) == json.loads(result), 'recorded network proof changed')
        else:
            save(path, json.loads(result))

    def neutral_guard(self):
        tables = schema(PG, DB)
        predicates = {'ir_cron': 'active', 'ir_mail_server': 'active', 'fetchmail_server': 'active',
                      'baseer_print_agent': 'active', 'baseer_bwork_push_device': 'active',
                      'baseer_bank_sms_device': 'active', 'payment_provider': "state <> 'disabled'",
                      'res_users_apikeys': "expiration_date IS NULL OR expiration_date > now()",
                      'pos_config': 'baseer_direct_print_enabled OR baseer_native_receipt_enabled OR baseer_print_session_close_report'}
        for table, where in predicates.items():
            if table in tables:
                require(sql(PG, DB, 'SELECT count(*) FROM "' + table + '" WHERE ' + where).strip() == '0',
                        'neutralization drift: ' + table)

    def health(self, port):
        for _ in range(60):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/web/login?db={DB}', timeout=3) as response:
                    require(response.status == 200, 'login HTTP status')
                    return
            except (OSError, RuntimeError):
                time.sleep(2)
        raise RuntimeError('QA HTTP unavailable on internal network')

    def prepare(self):
        try:
            self.prepare_impl()
        except BaseException:
            inventory = self.state / 'inventory.json'
            if inventory.exists() and json.loads(inventory.read_text())['poller_active']:
                run(['systemctl', 'start', TIMER])
            raise

    def prepare_impl(self):
        self.start('prepare')
        self.guards()
        require(shutil.disk_usage(BASE).free > 12 * 1024**3, 'insufficient guarded recovery space')
        old_source = (BASE / 'current').resolve(strict=True)
        live_source = LIVE.resolve(strict=True)
        require(str(old_source).startswith(str(BASE / 'releases') + '/'), 'QA source outside releases')
        manifest = {'old_source': str(old_source), 'live_source': str(live_source), 'archives': {}}
        manifest['poller_active'] = run(['systemctl', 'is-active', TIMER], check=False) is not None
        save(self.state / 'inventory.json', manifest)
        run(['systemctl', 'stop', TIMER])
        # Lock is held by main. Odoo stopped before every old QA DB/filestore backup.
        run(['docker', 'stop', QODOO])
        try:
            databases = [QDB]
            manifest['old_databases'] = databases
            for index, database in enumerate(databases):
                name = 'old-db-' + str(index)
                manifest['archives'][name + '.dump'] = self.dump(QPG, database, name)
            for name, path in [('old-odoo', volume(QVO)), ('old-config', CONFIG), ('old-source', old_source)]:
                manifest['archives'][name + '.tar'] = self.archive(name, path)
        finally:
            run(['docker', 'start', QODOO])
        # Live dump is an MVCC snapshot. Only live SELECT/pg_dump and filestore reads.
        manifest['archives']['live.dump'] = self.dump(LPG, LDB, 'live')
        manifest['archives']['live-filestore.tar'] = self.archive('live-filestore', volume(LVO) / 'filestore' / LDB)
        self.release.mkdir(mode=0o755, exist_ok=False)
        os.chmod(self.release, 0o755)
        before = {name: tree_hash(live_source / name) for name in ('custom_addons', 'third_party_addons')}
        for name in before:
            shutil.copytree(live_source / name, self.release / name, symlinks=False)
        save(self.release / 'RELEASE_COMMIT', self.live_sha)
        os.chmod(self.release / 'RELEASE_COMMIT', 0o644)
        require(before == {name: tree_hash(self.release / name) for name in before}, 'copied source differs')
        save(self.state / 'source-manifest.json', before)
        self.guards()
        require(before == {name: tree_hash(live_source / name) for name in before}, 'LIVE source changed during copy')
        # No preexisting candidate resource can be silently reused.
        require(run(['docker', 'ps', '-aq', '--filter', 'name=^/' + PG + '$']) == '', 'candidate exists')
        for suffix in ('postgres', 'odoo'):
            name = PROJECT + '-' + suffix
            require(run(['docker', 'volume', 'inspect', name], check=False) is None, 'candidate volume exists')
            run(['docker', 'volume', 'create', name])
        require(run(['docker', 'network', 'inspect', NETWORK], check=False) is None, 'candidate network exists')
        for network_id in run(['docker', 'network', 'ls', '-q']).split():
            for item in network_ranges(inspect(network_id, 'network')):
                if item.get('Subnet'):
                    net = ipaddress.ip_network(item['Subnet'])
                    require(net.version != 4 or not net.overlaps(ipaddress.ip_network(SUBNET)), 'candidate subnet overlaps')
        run(['docker', 'network', 'create', '--subnet', SUBNET, NETWORK])
        admin_pw, runner_pw = secrets.token_hex(32), secrets.token_hex(32)
        save(self.state / 'pg.env', 'POSTGRES_USER=qa_refresh_admin\nPOSTGRES_PASSWORD=' + admin_pw + '\nPOSTGRES_DB=postgres')
        save(self.state / 'app.env', 'POSTGRES_USER=qa_runner\nPOSTGRES_PASSWORD=' + runner_pw +
             '\nPOSTGRES_DB=' + DB + '\nHOST=db\nUSER=qa_runner\nPASSWORD=' + runner_pw)
        salt = secrets.token_bytes(16)
        encoded = lambda v: base64.b64encode(v).decode().rstrip('=').replace('+', '.')
        admin_hash = '$pbkdf2-sha512$600000$' + encoded(salt) + '$' + encoded(
            hashlib.pbkdf2_hmac('sha512', secrets.token_bytes(32), salt, 600000))
        config = ('[options]\naddons_path=' + ADDONS + '\ndata_dir=/var/lib/odoo\n'
                  'db_host=db\ndb_port=5432\ndb_user=qa_runner\ndb_password=' + runner_pw + '\n'
                  'db_name=' + DB + '\ndbfilter=^' + DB + '$\nlist_db=False\nproxy_mode=True\n'
                  'workers=2\nmax_cron_threads=0\nlimit_time_cpu=120\nlimit_time_real=240\n'
                  'http_port=8069\ngevent_port=8072\nadmin_passwd=' + admin_hash)
        save(self.config, config)
        # Odoo image runs UID100/GID101. Config group read only; archives remain0600.
        os.chown(self.config, 0, 101)
        os.chmod(self.config, 0o640)
        save(self.compose, self.compose_config(self.release, 18136, self.config))
        self.firewall()
        self.compose_run('up', '-d', 'db')
        for _ in range(60):
            if run(['docker', 'exec', PG, 'pg_isready', '-h', '127.0.0.1', '-U', 'qa_refresh_admin', '-d', 'postgres'], check=False):
                break
            time.sleep(1)
        sql(PG, 'postgres', "CREATE ROLE qa_runner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '" + runner_pw + "'")
        self.restore(DB, self.state / 'live.dump')
        target = volume(PROJECT + '-odoo')
        (target / 'filestore' / DB).mkdir(parents=True)
        (target / 'sessions').mkdir()
        run(['tar', '--no-same-owner', '-C', target / 'filestore' / DB, '-xf', self.state / 'live-filestore.tar'])
        run(['chown', '-R', '100:101', target])
        self.finish_prepare(manifest)

    def resume(self):
        """One reviewed recovery point: restore completed, no neutralization begun."""
        stage = self.recovery_stage()
        self.start(stage)
        self.guards()
        neutralized = (self.state / 'protected-after.json').exists()
        require(not (self.state / 'prepare.receipt.json').exists() and
                (neutralized or not (self.state / 'network-proof.json').exists()),
            'recovery point already crossed')
        if not neutralized:
            require(run(['docker', 'container', 'inspect', ODOO], check=False) is None, 'candidate Odoo already exists')
        target_pg = inspect(PG)
        require(target_pg['Image'] == PG_IMAGE and target_pg['State']['Running'], 'candidate PostgreSQL mismatch')
        archives = ('old-db-0.dump', 'old-odoo.tar', 'old-config.tar', 'old-source.tar',
                    'live.dump', 'live-filestore.tar')
        required = archives + ('prepare.intent.json', 'inventory.json', 'attachments.json',
                               'source-manifest.json', 'pg.env', 'app.env', 'compose.json', 'odoo.conf')
        if (self.state / 'protected-before.json').exists():
            required += ('protected-before.json',)
        if neutralized:
            required += ('protected-before.json', 'protected-after.json', 'network-proof.json')
        for name in required:
            path = self.state / name
            require(path.is_file() and not path.is_symlink() and path.stat().st_uid == 0 and
                    path.stat().st_mode & 0o777 == (0o640 if name == 'odoo.conf' else 0o600),
                    'unsafe recovery file: ' + name)
        intent = json.loads((self.state / 'prepare.intent.json').read_text())
        require(intent['live_sha'] == self.live_sha and intent['qa_sha'] == self.qa_sha, 'recovery source mismatch')
        manifest = json.loads((self.state / 'inventory.json').read_text())
        require(manifest['old_source'] == str((BASE / 'current').resolve(strict=True)) and
                manifest['live_source'] == str(LIVE.resolve(strict=True)), 'recovery source path changed')
        source = json.loads((self.state / 'source-manifest.json').read_text())
        require(set(source) == {'custom_addons', 'third_party_addons'} and
                (self.release / 'RELEASE_COMMIT').read_text().strip() == self.live_sha,
                'recovery release identity mismatch')
        require(source == {name: tree_hash(self.release / name) for name in source} ==
                {name: tree_hash(LIVE / name) for name in source}, 'recovery source bytes changed')
        require(json.loads(self.compose.read_text()) == self.compose_config(self.release, 18136, self.config),
                'recovery compose changed')
        config = configparser.ConfigParser()
        config.read(self.config)
        require(config['options']['db_name'] == DB and config['options']['db_user'] == 'qa_runner' and
                config['options']['db_host'] == 'db' and config['options']['max_cron_threads'] == '0',
                'recovery database config mismatch')
        require(sql(PG, DB, "SELECT coalesce((SELECT lower(value) FROM ir_config_parameter WHERE key='database.is_neutralized'),'false')").strip() == ('true' if neutralized else 'false'),
                'database neutralization checkpoint mismatch')
        manifest.update(old_databases=[QDB], archives={name: digest(self.state / name) for name in archives})
        run(['systemctl', 'stop', TIMER])
        try:
            if neutralized:
                self.recover_http(manifest, stage)
            else:
                self.finish_prepare(manifest)
            self.receipt(stage, {'state': str(self.state), 'resumed': 'neutralized-http' if neutralized else 'restored-before-neutralization'})
        except BaseException:
            run(['docker', 'stop', ODOO], check=False)
            require(inspect(QODOO)['State']['Running'], 'old QA is not running')
            if manifest['poller_active']:
                run(['systemctl', 'start', TIMER])
            raise

    def recovery_stage(self):
        request = re.fullmatch(r'qa-refresh-20261023-([1-9][0-9]{0,19})',
                               os.environ.get('QA_REFRESH_SIGNED_TAG', ''))
        require(request is not None, 'invalid signed recovery request')
        return 'resume-' + request.group(1)

    def recover_http(self, manifest, stage):
        baseline = json.loads((self.state / 'protected-before.json').read_text())
        require(baseline == json.loads((self.state / 'protected-after.json').read_text()) == fingerprints(PG, DB),
                'neutralized recovery protected data mismatch')
        network, pg, odoo = inspect(NETWORK, 'network'), inspect(PG), inspect(ODOO)
        require(network['Name'] == NETWORK and network['Driver'] == 'bridge' and network['Internal'] and
                not network.get('EnableIPv6') and network_ranges(network) == [{'Subnet': SUBNET, 'Gateway': '172.31.134.1'}] and
                set(network.get('Containers', {})) <= {pg['Id'], odoo['Id']}, 'unexpected QA network checkpoint')
        for item, image, env, mounts in (
            (pg, PG_IMAGE, 'pg.env', {'/var/lib/postgresql/data': ('volume', PROJECT + '-postgres', True)}),
            (odoo, ODOO_IMAGE, 'app.env', {'/var/lib/odoo': ('volume', PROJECT + '-odoo', True),
             '/etc/odoo/odoo.conf': ('bind', str(self.config), False),
             '/mnt/baseer-addons': ('bind', str(self.release / 'custom_addons'), False),
             '/mnt/third-party-addons': ('bind', str(self.release / 'third_party_addons'), False)})):
            actual_env = dict(v.split('=', 1) for v in item['Config']['Env'] if '=' in v)
            actual_mounts = {v['Destination']: (v['Type'], v.get('Name') if v['Type'] == 'volume' else v['Source'], v['RW']) for v in item['Mounts']}
            require(item['Image'] == image and item['HostConfig']['RestartPolicy']['Name'] == 'no' and
                    set(item['NetworkSettings']['Networks']) == {NETWORK} and actual_mounts == mounts and
                    all(actual_env.get(k) == v for k, v in env_file(self.state / env).items()), 'candidate runtime changed')
        require(not odoo['State']['Running'], 'candidate Odoo must be stopped for network recovery')
        artifacts = ('protected-before.json', 'protected-after.json', 'network-proof.json', 'pg.env', 'app.env', 'odoo.conf', 'compose.json')
        unchanged = {name: digest(self.state / name) for name in artifacts}
        prior = self.state / (stage + '.prior-network-proof.json')
        require(not prior.exists(), 'prior network proof already exists')
        shutil.copyfile(self.state / 'network-proof.json', prior)
        os.chmod(prior, 0o600)
        run(['docker', 'stop', PG])
        run(['docker', 'rm', PG, ODOO])  # No -v: retain both external data volumes.
        run(['docker', 'network', 'rm', NETWORK])
        run(['docker', 'network', 'create', '--subnet', SUBNET, NETWORK])
        self.firewall()
        self.compose_run('up', '-d', '--force-recreate', 'db')
        for _ in range(60):
            if run(['docker', 'exec', PG, 'pg_isready', '-h', '127.0.0.1', '-U', 'qa_refresh_admin', '-d', 'postgres'], check=False):
                break
            time.sleep(1)
        self.compose_run('up', '-d', '--force-recreate', 'odoo')
        proof = stage + '.network-proof.json'
        self.namespace_test(proof)
        self.neutral_guard()
        self.health(18136)
        require(baseline == fingerprints(PG, DB) and unchanged == {name: digest(self.state / name) for name in artifacts},
                'HTTP recovery changed protected evidence')
        self.receipt(stage + '-network-migration', {'from_internal': True, 'to_internal': False,
                     'prior_proof': str(prior), 'prior_sha256': digest(prior), 'new_proof': str(self.state / proof), 'http': 200})
        self.complete_prepare(manifest, self.attachments())

    def finish_prepare(self, manifest):
        attachments = self.attachments()
        baseline = fingerprints(PG, DB)
        previous = self.state / 'protected-before.json'
        if previous.exists():
            require(baseline == json.loads(previous.read_text()), 'protected data changed before recovery')
        else:
            save(previous, baseline)
        self.namespace_test()
        # Native command loads neutralize SQL only, no registry/HTTP/cron process.
        cli = ("import configparser,os; c=configparser.ConfigParser(); c.read('/etc/odoo/odoo.conf'); "
               "v=c['options']; os.execvp('odoo',['odoo','neutralize','--db_host=db',"
               "'--db_user=qa_runner','--db_password='+v['db_password'],'-d','" + DB + "'])")
        self.compose_run('run', '--rm', '--no-deps', '--entrypoint', 'python3', 'odoo', '-c', cli)
        sql(PG, DB, neutral_sql(schema(PG, DB)))
        self.neutral_guard()
        require(baseline == fingerprints(PG, DB), 'protected data changed during neutralization')
        save(self.state / 'protected-after.json', fingerprints(PG, DB))
        self.compose_run('up', '-d', 'odoo')
        self.health(18136)
        require(baseline == fingerprints(PG, DB), 'protected data changed after HTTP')
        self.complete_prepare(manifest, attachments)

    def complete_prepare(self, manifest, attachments):
        manifest['attachments'] = attachments
        manifest['source_sha'] = self.live_sha
        manifest['release'] = str(self.release)
        save(self.state / 'inventory.json', manifest)
        self.receipt('prepare', {'state': str(self.state), 'source_sha': self.live_sha,
                                'archives': len(manifest['archives']), 'attachments': attachments,
                                'old_databases': len(manifest['old_databases']), 'network': NETWORK, 'http': 200})

    def verify(self, switched=False):
        self.guards(switched)
        inventory = json.loads((self.state / 'inventory.json').read_text())
        for name, checksum in inventory['archives'].items():
            require(digest(self.state / name) == checksum, 'archive checksum mismatch')
        source = json.loads((self.state / 'source-manifest.json').read_text())
        require(source == {name: tree_hash(self.release / name) for name in source}, 'candidate source drift')
        require(json.loads((self.state / 'protected-before.json').read_text()) == fingerprints(PG, DB), 'protected data drift')
        self.namespace_test()
        self.neutral_guard()
        self.attachments()
        self.health(18134 if switched else 18136)
        return {'source_sha': self.live_sha, 'http': 200, 'archives_verified': len(inventory['archives'])}

    def switch(self):
        self.start('switch')
        self.verify()
        previous = (BASE / 'current').resolve(strict=True)
        require(str(previous) == json.loads((self.state / 'inventory.json').read_text())['old_source'], 'old QA source moved')
        files = {name: ((CONFIG / name).read_bytes(), (CONFIG / name).stat())
                 for name in ('compose.yaml', 'runtime.env', 'odoo.conf', 'deploy.env')}
        run(['docker', 'stop', QODOO])
        try:
            run(['docker', 'stop', ODOO])
            link = BASE / ('refresh-current-' + self.state.name)
            link.symlink_to(self.release)
            os.replace(link, BASE / 'current')
            save(CONFIG / 'odoo.conf', self.config.read_text())
            os.chown(CONFIG / 'odoo.conf', 0, 101)
            os.chmod(CONFIG / 'odoo.conf', 0o640)
            save(CONFIG / 'runtime.env', (self.state / 'app.env').read_text())
            values = env_file(CONFIG / 'deploy.env')
            values.update(QA_DATABASE=DB, QA_DB_CONTAINER=PG, QA_ODOO_VOLUME=PROJECT + '-odoo',
                          QA_COMPOSE_PROJECT=PROJECT, QA_LOGIN_URL='http://127.0.0.1:18134/web/login',
                          QA_ADDONS_PATH=ADDONS)
            save(CONFIG / 'deploy.env', '\n'.join(k + '=' + v for k, v in values.items()))
            config = self.compose_config(BASE / 'current', 18134, CONFIG / 'odoo.conf')
            save(CONFIG / 'compose.yaml', config)
            save(self.compose, config)
            self.compose_run('up', '-d', 'odoo')
            result = self.verify(True)
            # Reboot starts firewall first; Docker restart policies remain disabled.
            save('/etc/systemd/system/baseer-qa-refresh.service',
                 '[Unit]\nRequires=docker.service baseer-qa-refresh-firewall.service\n'
                 'After=docker.service baseer-qa-refresh-firewall.service\n[Service]\nType=oneshot\n'
                 'RemainAfterExit=yes\nExecStart=/usr/bin/docker compose -p ' + PROJECT +
                 ' -f /etc/baseer-qa/compose.yaml up -d\n[Install]\nWantedBy=multi-user.target')
            run(['systemctl', 'daemon-reload'])
            run(['systemctl', 'enable', 'baseer-qa-refresh.service'])
            if json.loads((self.state / 'inventory.json').read_text())['poller_active']:
                run(['systemctl', 'start', TIMER])
            self.receipt('switch', result)
        except BaseException:
            run(['docker', 'stop', ODOO], check=False)
            run(['systemctl', 'disable', 'baseer-qa-refresh.service'], check=False)
            for name, (value, metadata) in files.items():
                (CONFIG / name).write_bytes(value)
                os.chown(CONFIG / name, metadata.st_uid, metadata.st_gid)
                os.chmod(CONFIG / name, metadata.st_mode & 0o777)
            link = BASE / ('rollback-current-' + self.state.name)
            link.symlink_to(previous)
            os.replace(link, BASE / 'current')
            run(['docker', 'start', QODOO])
            if json.loads((self.state / 'inventory.json').read_text())['poller_active']:
                run(['systemctl', 'start', TIMER])
            save(self.state / 'rollback.receipt.json', {'old_source': str(previous), 'old_odoo_restarted': True})
            raise


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    require(len(args) == 4 and args[0] in ('prepare', 'resume', 'switch', 'verify'), 'expected stage RUNID LIVE_SHA QA_SHA')
    require(os.geteuid() == 0, 'root required')
    require(os.name == 'posix', 'Linux required')
    os.umask(0o077)
    require(os.environ.get('QA_REFRESH_REVIEWED_REVISION') and os.environ.get('QA_REFRESH_SIGNED_TAG'),
            'signed wrapper invocation required')
    # The fixed root wrapper owns all three flock descriptors; do not relock them.
    engine = Refresh(*args[1:])
    if args[0] == 'verify':
        result = engine.verify((engine.state / 'switch.receipt.json').exists())
        print(json.dumps(result, sort_keys=True))
    else:
        getattr(engine, args[0])()
        stage = engine.recovery_stage() if args[0] == 'resume' else args[0]
        print((engine.state / (stage + '.receipt.json')).read_text())


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('QA_REFRESH=FAILED ' + str(error), file=sys.stderr)
        sys.exit(1)
