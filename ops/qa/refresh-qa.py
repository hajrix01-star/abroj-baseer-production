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
import stat
import subprocess
import sys
import tarfile
import time
import urllib.request
import uuid

BASE = Path('/srv/baseer-qa')
CONFIG = Path('/etc/baseer-qa')
LIVE = Path('/srv/abroj-baseer-production/current')
LPG, LODOO = 'baseer-odoo-prod-db-1', 'baseer-odoo-prod-odoo-1'
QPG = 'baseer-qa-refresh-20261023-db-1'
QODOO = 'baseer-qa-refresh-20261023-odoo-1'
QDB = 'baseer_qa_20261023'
QVO = 'baseer-qa-refresh-20261023-odoo'
GENERATION = '20261121b'
SNAPSHOT = '20261121-44938924993'
PROJECT, DB = 'baseer-qa-refresh-' + GENERATION, 'baseer_qa_' + GENERATION
PREVIEW_PORT, QA_PORT = 18140, 18134
PG, ODOO = PROJECT + '-db-1', PROJECT + '-odoo-1'
NETWORK, SUBNET, PGIP = PROJECT + '-isolated', '172.31.136.0/28', '172.31.136.2'
ODOO_IMAGE = 'sha256:f99ffac95cb39a0924622ea4118481c95651d9c84187e5b30a21c2cc4419c7dd'
PG_IMAGE = 'sha256:f1c3376c26f2609ab9f29f71f824103fe2fcd8ee0346485cb6122a4f93df6f94'
SOURCE_DIRS = ('custom_addons', 'third_party_addons')
TIMER = 'baseer-qa-release-poller.timer'
FIREWALL_PATH = Path('/usr/local/sbin') / (PROJECT + '-firewall')
FIREWALL_UNIT = Path('/etc/systemd/system') / (PROJECT + '-firewall.service')
BOOT_UNIT = Path('/etc/systemd/system') / (PROJECT + '.service')
SNAPSHOT_PINS = {'live.dump': 'QA_REFRESH_SNAPSHOT_DUMP_SHA',
                 'live-filestore.tar': 'QA_REFRESH_SNAPSHOT_FILESTORE_SHA'}
REPORT_FILES = {'baseer_profit_loss_report/models/profit_loss.py',
                'baseer_profit_loss_report/__manifest__.py'}
VERIFIER = Path('/usr/local/lib/baseer-qa-refresh/verify-qa-refresh-odoo.py')
CONNECTOR_SECRETS = ['gmail_token', 'gmail_refresh_token', 'gmail_access_token',
                         'microsoft_outlook_token', 'microsoft_outlook_refresh_token',
                         'google_calendar_token', 'google_calendar_rtoken', 'oauth_access_token',
                         'oauth_refresh_token', 'token_ciphertext', 'token_nonce', 'token_key_version',
                         'token_expires_at', 'smtp_user', 'smtp_pass']
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


def tree_hash(root, *, ignore_cache=False):
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), 'missing or unsafe addon root')
    values = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        mode = path.lstat().st_mode
        require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), 'unexpected addon file type')
        if ignore_cache and ('__pycache__' in relative.parts or path.suffix in {'.pyc', '.pyo'}):
            continue
        if stat.S_ISREG(mode):
            values[relative.as_posix()] = [digest(path), bool(mode & 0o111)]
    return values


def protected_file(path, mode=0o600):
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == 0
            and stat.S_IMODE(metadata.st_mode) == mode, 'unsafe snapshot file: ' + path.name)


def verify_filestore_archive(path):
    seen = set()
    with tarfile.open(path, 'r:') as archive:
        for member in archive:
            name = member.name.removeprefix('./')
            if member.isdir():
                valid = name in {'.', 'checklist'} or re.fullmatch(r'(checklist/)?[0-9a-f]{2}', name)
            else:
                blob = re.fullmatch(r'(checklist/)?[0-9a-f]{2}/[0-9a-f]{40}', name)
                valid = member.isfile() and blob and (not blob[1] or member.size == 0)
            require(valid and name not in seen and not member.mode & 0o7000,
                    'unsafe snapshot filestore member')
            seen.add(name)
    require('.' in seen, 'snapshot filestore root missing')


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


def fingerprints(container, database, protected=True, upgrading=False):
    """Ordered hashes and counts; secret/user rows never leave PostgreSQL."""
    tables = schema(container, database)
    selected = [t for t in tables if not protected or t.startswith(
        ('account_', 'pos_', 'purchase_', 'stock_', 'hr_', 'res_company', 'abroj_',
         'baseer_', 'product_', 'sale_', 'payment_transaction',
         'res_users', 'res_groups', 'res_partner', 'ir_module_module', 'ir_attachment'))]
    excluded = {
        'pos_config': ['baseer_direct_print_enabled', 'baseer_native_receipt_enabled',
                       'baseer_print_session_close_report', 'access_token'],
        'res_company': ['baseer_receipt_profile_enabled', 'baseer_receipt_profile_close_report', 'l10n_sa_api_mode'],
        'res_users': CONNECTOR_SECRETS,
        'res_users_settings': CONNECTOR_SECRETS + ['google_synchronization_stopped'],
        'baseer_gads_connection': CONNECTOR_SECRETS + ['state', 'writer_enabled'],
        'baseer_gbp_connection': CONNECTOR_SECRETS + ['state', 'writer_enabled'],
        'res_users_apikeys': ['expiration_date'],
        'baseer_print_agent': ['active', 'state', 'token_fingerprint', 'pairing_fingerprint',
                               'pairing_expires_at', 'runtime_instance_id', 'runtime_lease_expires_at'],
        'baseer_print_job': ['state', 'lease_token', 'lease_expires_at'],
        'baseer_bwork_push_device': ['active', 'fcm_token'],
        'baseer_bank_sms_device': ['active', 'secret_salt', 'secret_hash'],
        'baseer_bank_sms_pairing': ['token', 'state', 'expires_at'],
        'baseer_bwork_mobile_upload_grant': ['secret_hash'],
    } if protected else {}
    values = {}
    for table in sorted(selected):
        keys = excluded.get(table, [])
        minus = ''.join(" - '" + key + "'" for key in keys)
        row = 'to_jsonb(t)'
        where = ''
        if upgrading and table == 'ir_module_module':
            # Odoo refreshes the registry timestamps. Every other field remains
            # protected except the expected version update on the target row.
            row = "(CASE WHEN name = 'baseer_profit_loss_report' THEN to_jsonb(t) - 'latest_version' ELSE to_jsonb(t) END)"
            minus = " - 'write_date'"
        elif upgrading and table == 'ir_attachment':
            where = (" WHERE NOT (coalesce(url, '') ~ '^/web/assets/([0-9]+/)?[a-f0-9]{7,64}/[^/]+[.](js|css|map)$'"
                     " AND coalesce(res_model, '') = 'ir.ui.view' AND coalesce(res_id, 0) = 0"
                     " AND (coalesce(mimetype, '') IN ('text/css', 'application/javascript', 'text/javascript', 'application/json')))")
        query = (f"SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM "
                 f"(SELECT md5(({row}{minus})::text) h FROM \"{table}\" t{where}) s")
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
    for table in ('res_users', 'res_users_settings', 'ir_mail_server', 'fetchmail_server',
                  'baseer_gads_connection', 'baseer_gbp_connection'):
        update(table, dict.fromkeys(CONNECTOR_SECRETS, 'NULL'))
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
        self.source_sha = os.environ.get('QA_REFRESH_SOURCE_COMMIT', '')
        require(re.fullmatch('[0-9a-f]{40}', self.source_sha), 'invalid runtime source SHA')
        self.state = BASE / 'refresh' / (GENERATION + '-' + run_id)
        self.snapshot = BASE / 'refresh' / SNAPSHOT
        self.live_sha, self.qa_sha = live_sha, qa_sha
        self.release = BASE / 'releases' / ('qa-refresh-' + GENERATION + '-' + run_id)
        self.compose = self.state / 'compose.json'
        self.config = self.state / 'odoo.conf'

    def start(self, stage):
        if stage == 'prepare':
            self.state.mkdir(mode=0o700, parents=True, exist_ok=False)
        require(self.state.is_dir() and not self.state.is_symlink(), 'missing protected state')
        require(self.state.stat().st_uid == 0 and self.state.stat().st_mode & 0o777 == 0o700,
                'state owner/mode invalid')
        if stage in ('finance', 'switch'):
            self.prepared()
        if stage == 'switch':
            review = self.state / 'review.accepted'
            require(review.is_file() and review.stat().st_uid == 0 and review.stat().st_mode & 0o777 == 0o600 and not review.is_symlink(), 'unsafe review receipt')
            financial = self.state / 'financial.receipt.json'
            require(financial.is_file() and not financial.is_symlink() and financial.stat().st_uid == 0 and
                    financial.stat().st_mode & 0o777 == 0o600, 'unsafe financial receipt')
            prepare_hash = digest(self.state / 'prepare.receipt.json')
            require(review.read_text().strip() == prepare_hash + ' ' + digest(financial),
                    'independent review receipt missing')
            result = json.loads(financial.read_text())
            require(all(result.get(key) == value for key, value in {
                'prepared_sha256': prepare_hash, 'source_sha': self.source_sha, 'database': DB,
                'arz': 'PASS', 'shami': 'PASS', 'repeat': 'PASS', 'company_guard': 'PASS',
                'read_only': True, 'verifier_sha256': digest(VERIFIER),
                'input_sha256': digest(self.state / 'financial-input.json'),
                'workbook_sha256': digest(self.state / 'financial-workbook.xlsx'),
            }.items()), 'financial acceptance mismatch')
        intent = self.state / (stage + '.intent.json')
        require(not intent.exists(), 'stage already attempted; no automatic replay')
        save(intent, {'live_sha': self.live_sha, 'qa_sha': self.qa_sha, 'source_sha': self.source_sha, 'time': time.time()})

    def prepared(self):
        receipt = self.state / 'prepare.receipt.json'
        require(receipt.is_file() and not receipt.is_symlink() and receipt.stat().st_uid == 0
                and receipt.stat().st_mode & 0o777 == 0o600, 'prepare not accepted')
        prepared = json.loads(receipt.read_text())
        require(prepared.get('reviewed_revision') == os.environ['QA_REFRESH_REVIEWED_REVISION'] and
                prepared.get('signed_tag') == os.environ['QA_REFRESH_SIGNED_TAG'] and
                prepared.get('source_sha') == self.source_sha and prepared.get('live_sha') == self.live_sha
                and prepared.get('previous_qa_sha') == self.qa_sha and prepared.get('snapshot') == SNAPSHOT,
                'reviewed request changed')
        return receipt

    def finance(self):
        self.start('finance')
        self.verify()
        paths = [self.state / name for name in ('financial-input.json', 'financial-workbook.xlsx')]
        for path in paths:
            require(path.is_file() and not path.is_symlink() and path.stat().st_uid == 0
                    and path.stat().st_mode & 0o777 == 0o600 and path.stat().st_size < 100_000,
                    'unsafe private financial input')
        evidence, workbook = (path.read_bytes() for path in paths)
        value = json.loads(evidence)
        value['prepared_sha256'] = digest(self.prepared())
        workbook_hash = hashlib.sha256(workbook).hexdigest()
        require(value['shami']['workbook_sha256'] == workbook_hash, 'workbook evidence mismatch')
        source = VERIFIER.read_bytes()
        payload = ("import json\nQA_INPUT = json.loads(" + repr(json.dumps(value)) + ")\n"
                   + 'QA_EXPECTED_SOURCE = ' + repr(self.source_sha) + '\n'
                   + 'QA_WORKBOOK = ' + repr(workbook) + '\n').encode() + source
        out = run(['docker', 'exec', '-i', '-e', 'PGOPTIONS=-c default_transaction_read_only=on',
                   ODOO, 'odoo', 'shell', '--config=/etc/odoo/odoo.conf',
                   '-d', DB, '--no-http', '--workers=0', '--max-cron-threads=0'], data=payload)
        prefix = 'QA_REFRESH_ODOO='
        reports = [line[len(prefix):] for line in out.splitlines() if line.startswith(prefix)]
        require(len(reports) == 1, 'financial verifier did not return one result')
        result = json.loads(reports[0])
        require(all(result.get(key) == expected for key, expected in {
            'prepared_sha256': value['prepared_sha256'], 'source_sha': self.source_sha, 'database': DB,
            'arz': 'PASS', 'shami': 'PASS', 'repeat': 'PASS', 'company_guard': 'PASS', 'read_only': True,
        }.items()), 'financial verifier did not pass all guards')
        require(json.loads((self.state / 'protected-after.json').read_text()) == fingerprints(PG, DB),
                'protected data drift during financial checks')
        result.update(input_sha256=hashlib.sha256(evidence).hexdigest(),
                      verifier_sha256=hashlib.sha256(source).hexdigest(),
                      workbook_sha256=workbook_hash)
        self.receipt('financial', result)

    def receipt(self, stage, value):
        require(not (self.state / (stage + '.receipt.json')).exists(), 'receipt already exists')
        value.update(reviewed_revision=os.environ.get('QA_REFRESH_REVIEWED_REVISION'),
                     signed_tag=os.environ.get('QA_REFRESH_SIGNED_TAG'))
        save(self.state / (stage + '.receipt.json'), value)

    def guards(self, switched=False):
        require((LIVE / 'RELEASE_COMMIT').read_text().strip() == self.live_sha, 'LIVE source moved')
        require((BASE / 'current' / 'RELEASE_COMMIT').read_text().strip() ==
                (self.source_sha if switched else self.qa_sha), 'QA source moved')
        identity = {'QA_DATABASE': DB if switched else QDB, 'QA_DB_CONTAINER': PG if switched else QPG,
                    'QA_ODOO_VOLUME': PROJECT + '-odoo' if switched else QVO,
                    'QA_COMPOSE_PROJECT': PROJECT if switched else 'baseer-qa-refresh-20261023'}
        actual = env_file(CONFIG / 'deploy.env')
        require(all(actual.get(key) == value for key, value in identity.items()), 'QA deploy identity mismatch')
        if switched:
            require((BASE / 'current').resolve(strict=True) == self.release.resolve(strict=True), 'QA release link mismatch')
        for name, expected in ((LPG, PG_IMAGE), (LODOO, ODOO_IMAGE), (QPG, PG_IMAGE), (QODOO, ODOO_IMAGE)):
            item = inspect(name)
            require(item['Image'] == expected, 'runtime image mismatch')
            if name != QODOO or not switched:
                require(item['State']['Running'], 'source container not running')

    def snapshot_archives(self):
        metadata = self.snapshot.lstat()
        require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0
                and stat.S_IMODE(metadata.st_mode) == 0o700, 'unsafe snapshot directory')
        for name in ('prepare.intent.json', 'inventory.json', *SNAPSHOT_PINS):
            protected_file(self.snapshot / name)
        intent = json.loads((self.snapshot / 'prepare.intent.json').read_text())
        require(intent['live_sha'] == self.live_sha and intent['qa_sha'] == self.qa_sha,
                'snapshot source identity mismatch')
        inventory = json.loads((self.snapshot / 'inventory.json').read_text())
        expected = {name: os.environ.get(key, '') for name, key in SNAPSHOT_PINS.items()}
        require(all(re.fullmatch('[a-f0-9]{64}', value) for value in expected.values()),
                'missing signed snapshot checksum')
        require(inventory['archives'] == expected and
                all(digest(self.snapshot / name) == value for name, value in expected.items()),
                'snapshot archive checksum mismatch')
        return expected

    def verify_live_baseline(self, live_source):
        active = inspect(LODOO)
        pid = active['State']['Pid']
        require(type(pid) is int and pid > 0 and active['State']['Running'], 'LIVE Odoo source not mounted')
        baseline = Path(os.environ['QA_REFRESH_RUNTIME_BASELINE_DIR'])
        resolved = {}
        for name, destination in zip(SOURCE_DIRS, ('/mnt/baseer-addons', '/mnt/third-party-addons')):
            bound = [mount for mount in active['Mounts'] if mount['Destination'] == destination]
            require(len(bound) == 1 and bound[0]['Type'] == 'bind'
                    and Path(bound[0]['Source']).resolve(strict=True) == live_source / name,
                    'unexpected deployed addon mount: ' + name)
            expected = tree_hash(baseline / name)
            mounted = Path('/proc') / str(pid) / 'root' / destination.lstrip('/')
            require(expected and tree_hash(mounted, ignore_cache=True) == expected,
                    'deployed addon content or executable mode differs from signed baseline: ' + name)
            resolved[name] = expected
        checked = inspect(LODOO)
        require(active['Id'] == checked['Id'] and pid == checked['State']['Pid']
                and active['State']['StartedAt'] == checked['State']['StartedAt']
                and LIVE.resolve(strict=True) == live_source, 'LIVE source moved during baseline verification')
        return resolved

    def restore(self, database, dump):
        run(['docker', 'exec', PG, 'createdb', '-U', pg_user(PG), '-O', 'qa_runner', database])
        run(['docker', 'exec', '-i', PG, 'pg_restore', '-U', pg_user(PG), '--role=qa_runner',
             '--no-owner', '--no-privileges', '--exit-on-error', '-d', database], data=Path(dump).read_bytes())

    def compose_run(self, *args):
        return run(['docker', 'compose', '-p', PROJECT, '-f', self.compose, *args])

    def firewall(self):
        # Only this new subnet is matched. No existing network/LIVE rule is changed.
        script = '#!/bin/sh\nset -eu\n'
        for parent, chain in (('DOCKER-USER', 'BAS_QA1121B_FWD'), ('INPUT', 'BAS_QA1121B_HOST')):
            script += f'iptables -w -N {chain} 2>/dev/null || true\niptables -w -F {chain}\n'
            script += f'iptables -w -A {chain} -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN\n'
            if parent == 'DOCKER-USER':
                script += f'iptables -w -A {chain} -d {PGIP} -p tcp --dport 5432 -j RETURN\n'
            script += f'iptables -w -A {chain} -j DROP\n'
            script += f'iptables -w -C {parent} -s {SUBNET} -j {chain} 2>/dev/null || iptables -w -I {parent} 1 -s {SUBNET} -j {chain}\n'
        save(FIREWALL_PATH, script)
        os.chmod(FIREWALL_PATH, 0o700)
        save(FIREWALL_UNIT,
             f'[Unit]\nRequires=docker.service\nAfter=docker.service\nBefore={BOOT_UNIT.name}\n'
             '[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=' + str(FIREWALL_PATH) + '\n'
             '[Install]\nWantedBy=multi-user.target')
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'enable', '--now', FIREWALL_UNIT.name])

    def compose_config(self, source, port, config):
        def service(image, address):
            return {'image': image, 'restart': 'no', 'networks': {'isolated': {'ipv4_address': address}},
                    'dns': [PGIP], 'sysctls': {'net.ipv6.conf.all.disable_ipv6': '1',
                                'net.ipv6.conf.default.disable_ipv6': '1'}}
        pg = service(PG_IMAGE, PGIP)
        pg.update(container_name=PG, env_file=[str(self.state / 'pg.env')],
                  volumes=[PROJECT + '-postgres:/var/lib/postgresql/data'])
        odoo = service(ODOO_IMAGE, '172.31.136.3')
        odoo.update(container_name=ODOO, entrypoint=['odoo'],
                    env_file=[str(CONFIG / 'runtime.env') if port == QA_PORT else str(self.state / 'app.env')],
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
        network = inspect(NETWORK, 'network')
        require(network['Name'] == NETWORK and network['Driver'] == 'bridge'
                and not network.get('EnableIPv6')
                and network_ranges(network) == [{'Subnet': SUBNET, 'Gateway': '172.31.136.1'}]
                and all(endpoint['Name'] in {PG, ODOO} for endpoint in network.get('Containers', {}).values()),
                'candidate network identity mismatch')
        helper = PROJECT + '-tcp-control'
        require(run(['docker', 'container', 'inspect', helper], check=False) is None, 'TCP control already exists')
        with socket.socket() as listener:
            listener.bind(('172.31.136.1', 0))
            listener.listen(4)
            host_port = listener.getsockname()[1]
            server = 'import socket; s=socket.socket(); s.bind(("0.0.0.0",16443)); s.listen(8)\nwhile True: c,a=s.accept(); c.close()'
            run(['docker', 'run', '-d', '--name', helper, '--network', NETWORK, '--ip', '172.31.136.5',
                 '--dns', PGIP, '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1', '--entrypoint', 'python3', ODOO_IMAGE, '-c', server])
            try:
                targets = [('host', '172.31.136.1', host_port), ('public', '1.1.1.1', 443),
                           ('live_pg', live_ip, 5432), ('internal_qa_peer', '172.31.136.5', 16443)]
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
        result = run(['docker', 'run', '--rm', '--network', NETWORK, '--ip', '172.31.136.4',
                      '--dns', PGIP, '--sysctl', 'net.ipv6.conf.all.disable_ipv6=1', '--entrypoint', 'python3', ODOO_IMAGE, '-c', code])
        path = self.state / proof_name
        if path.exists():
            require(json.loads(path.read_text()) == json.loads(result), 'recorded network proof changed')
        else:
            save(path, json.loads(result))

    def neutral_guard(self):
        require(sql(PG, DB, "SELECT value FROM ir_config_parameter WHERE key='database.is_neutralized'").strip()
                == 'true', 'database is not neutralized')
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
        self.start('prepare')
        try:
            self.prepare_impl()
        except BaseException:
            if (self.state / 'inventory.json').exists():
                run(['docker', 'stop', ODOO], check=False)
            raise

    def prepare_impl(self):
        self.guards()
        for port in (PREVIEW_PORT, PREVIEW_PORT + 1):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
        old_source = (BASE / 'current').resolve(strict=True)
        live_source = LIVE.resolve(strict=True)
        require(str(old_source).startswith(str(BASE / 'releases') + '/'), 'QA source outside releases')
        require(not self.release.exists() and not self.release.is_symlink(), 'candidate release exists')
        for name in (PG, ODOO):
            require(run(['docker', 'container', 'inspect', name], check=False) is None, 'candidate container exists')
        for suffix in ('postgres', 'odoo'):
            require(run(['docker', 'volume', 'inspect', PROJECT + '-' + suffix], check=False) is None,
                    'candidate volume exists')
        require(run(['docker', 'network', 'inspect', NETWORK], check=False) is None, 'candidate network exists')
        for path in (FIREWALL_PATH, FIREWALL_UNIT, BOOT_UNIT):
            require(not path.exists() and not path.is_symlink(), 'candidate unit or firewall exists')
        for chain in ('BAS_QA1121B_FWD', 'BAS_QA1121B_HOST'):
            require(run(['iptables', '-w', '-S', chain], check=False) is None, 'candidate firewall chain exists')
        for network_id in run(['docker', 'network', 'ls', '-q']).split():
            for item in network_ranges(inspect(network_id, 'network')):
                if item.get('Subnet'):
                    net = ipaddress.ip_network(item['Subnet'])
                    require(net.version != 4 or not net.overlaps(ipaddress.ip_network(SUBNET)), 'candidate subnet overlaps')
        archives = self.snapshot_archives()
        baseline = self.verify_live_baseline(live_source)
        signed_source = Path(os.environ['QA_REFRESH_SOURCE_DIR'])
        source = {name: tree_hash(signed_source / name) for name in SOURCE_DIRS}
        require(all(source.values()) and source['third_party_addons'] == baseline['third_party_addons'],
                'signed runtime source incomplete or vendor source changed')
        differences = {name for name in source['custom_addons'].keys() | baseline['custom_addons'].keys()
                       if source['custom_addons'].get(name) != baseline['custom_addons'].get(name)}
        require(differences == REPORT_FILES, 'source change exceeds reviewed report files')
        source_bytes = sum(int(run(['du', '-sb', '--', signed_source / name]).split()[0])
                           for name in SOURCE_DIRS)
        dump = self.snapshot / 'live.dump'
        filestore = self.snapshot / 'live-filestore.tar'
        restore_bytes = max(4 * 1024**3, 8 * dump.stat().st_size)
        require(shutil.disk_usage(BASE).free > filestore.stat().st_size + restore_bytes + source_bytes + 2 * 1024**3,
                'insufficient space for isolated restore and reserve')
        require(os.statvfs(BASE).f_favail > 20000, 'insufficient inodes for retained QA and candidate')
        verify_filestore_archive(filestore)
        manifest = {'old_source': str(old_source), 'live_source': str(live_source), 'archives': archives,
                    'snapshot': SNAPSHOT, 'previous_qa_sha': self.qa_sha}
        manifest['poller_active'] = run(['systemctl', 'is-active', TIMER], check=False) is not None
        # Existing QA resources and the previous failed candidate remain intact.
        manifest['old_databases'] = [QDB]
        save(self.state / 'inventory.json', manifest)
        self.release.mkdir(mode=0o755, exist_ok=False)
        os.chmod(self.release, 0o755)
        for name in SOURCE_DIRS:
            shutil.copytree(signed_source / name, self.release / name, symlinks=False)
        require(source == {name: tree_hash(self.release / name) for name in SOURCE_DIRS},
                'copied source differs from signed source')
        save(self.release / 'RELEASE_COMMIT', self.source_sha)
        os.chmod(self.release / 'RELEASE_COMMIT', 0o644)
        save(self.state / 'source-manifest.json', source)
        self.guards()
        for suffix in ('postgres', 'odoo'):
            run(['docker', 'volume', 'create', PROJECT + '-' + suffix])
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
        save(self.compose, self.compose_config(self.release, PREVIEW_PORT, self.config))
        self.firewall()
        self.compose_run('up', '-d', 'db')
        for _ in range(60):
            if run(['docker', 'exec', PG, 'pg_isready', '-h', '127.0.0.1', '-U', 'qa_refresh_admin', '-d', 'postgres'], check=False):
                break
            time.sleep(1)
        sql(PG, 'postgres', "CREATE ROLE qa_runner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD '" + runner_pw + "'")
        self.restore(DB, dump)
        require(shutil.disk_usage(BASE).free > filestore.stat().st_size + 2 * 1024**3, 'insufficient space for filestore restore')
        target = volume(PROJECT + '-odoo')
        (target / 'filestore' / DB).mkdir(parents=True)
        (target / 'sessions').mkdir()
        run(['tar', '--no-same-owner', '-C', target / 'filestore' / DB, '-xf', filestore])
        run(['chown', '-R', '100:101', target])
        self.finish_prepare(manifest)

    def resume(self):
        """One reviewed recovery point: restore completed, no neutralization begun."""
        stage = self.recovery_stage()
        self.start(stage)
        self.guards()
        require(not any((self.state / name).exists() for name in
                        ('prepare.receipt.json', 'neutralization.intent.json', 'protected-after.json', 'network-proof.json')),
                'recovery point already crossed')
        require(run(['docker', 'container', 'inspect', ODOO], check=False) is None,
                'candidate Odoo already exists')
        target_pg = inspect(PG)
        require(target_pg['Image'] == PG_IMAGE and target_pg['State']['Running'], 'candidate PostgreSQL mismatch')
        required = ('prepare.intent.json', 'inventory.json', 'attachments.json',
                               'source-manifest.json', 'pg.env', 'app.env', 'compose.json', 'odoo.conf')
        if (self.state / 'protected-before.json').exists():
            required += ('protected-before.json',)
        for name in required:
            path = self.state / name
            require(path.is_file() and not path.is_symlink() and path.stat().st_uid == 0 and
                    path.stat().st_mode & 0o777 == (0o640 if name == 'odoo.conf' else 0o600),
                    'unsafe recovery file: ' + name)
        intent = json.loads((self.state / 'prepare.intent.json').read_text())
        require(intent['live_sha'] == self.live_sha and intent['qa_sha'] == self.qa_sha
                and intent['source_sha'] == self.source_sha, 'recovery source mismatch')
        manifest = json.loads((self.state / 'inventory.json').read_text())
        require(manifest['old_source'] == str((BASE / 'current').resolve(strict=True)) and
                manifest['live_source'] == str(LIVE.resolve(strict=True)), 'recovery source path changed')
        source = json.loads((self.state / 'source-manifest.json').read_text())
        require(set(source) == {'custom_addons', 'third_party_addons'} and
                (self.release / 'RELEASE_COMMIT').read_text().strip() == self.source_sha,
                'recovery release identity mismatch')
        self.verify_source()
        require(json.loads(self.compose.read_text()) == self.compose_config(self.release, PREVIEW_PORT, self.config),
                'recovery compose changed')
        config = configparser.ConfigParser()
        config.read(self.config)
        require(config['options']['db_name'] == DB and config['options']['db_user'] == 'qa_runner' and
                config['options']['db_host'] == 'db' and config['options']['max_cron_threads'] == '0',
                'recovery database config mismatch')
        require(sql(PG, DB, "SELECT coalesce((SELECT lower(value) FROM ir_config_parameter WHERE key='database.is_neutralized'),'false')").strip() == 'false',
                'database neutralization checkpoint mismatch')
        require(manifest['old_databases'] == [QDB] and manifest['snapshot'] == SNAPSHOT
                and manifest['archives'] == self.snapshot_archives(),
                'recovery archive checksum mismatch')
        try:
            self.finish_prepare(manifest)
            self.receipt(stage, {'state': str(self.state), 'resumed': 'restored-before-neutralization'})
        except BaseException:
            run(['docker', 'stop', ODOO], check=False)
            require(inspect(QODOO)['State']['Running'], 'old QA is not running')
            raise

    def recovery_stage(self):
        request = re.fullmatch(r'qa-refresh-' + GENERATION + r'-([1-9][0-9]{0,19})',
                               os.environ.get('QA_REFRESH_SIGNED_TAG', ''))
        require(request is not None, 'invalid signed recovery request')
        return 'resume-' + request.group(1)

    def finish_prepare(self, manifest):
        attachments = self.attachments()
        baseline = fingerprints(PG, DB)
        previous = self.state / 'protected-before.json'
        if previous.exists():
            require(baseline == json.loads(previous.read_text()), 'protected data changed before recovery')
        else:
            save(previous, baseline)
        self.namespace_test()
        save(self.state / 'neutralization.intent.json', {'database': DB})
        # Native command loads neutralize SQL only, no registry/HTTP/cron process.
        cli = ("import configparser,os; c=configparser.ConfigParser(); c.read('/etc/odoo/odoo.conf'); "
               "v=c['options']; os.execvp('odoo',['odoo','neutralize','--db_host=db',"
               "'--db_user=qa_runner','--db_password='+v['db_password'],'-d','" + DB + "'])")
        self.compose_run('run', '--rm', '--no-deps', '--entrypoint', 'python3', 'odoo', '-c', cli)
        sql(PG, DB, neutral_sql(schema(PG, DB)))
        self.neutral_guard()
        require(baseline == fingerprints(PG, DB), 'protected data changed during neutralization')
        self.check_report_version('19.0.1.1.2')
        upgrade_before = fingerprints(PG, DB, upgrading=True)
        self.compose_run('run', '--rm', '--no-deps', 'odoo', '--config=/etc/odoo/odoo.conf',
                         '-d', DB, '-u', 'baseer_profit_loss_report', '--stop-after-init',
                         '--workers=0', '--max-cron-threads=0')
        require(upgrade_before == fingerprints(PG, DB, upgrading=True), 'protected data changed during module upgrade')
        self.check_report_version('19.0.1.1.4')
        self.neutral_guard()
        self.attachments()
        save(self.state / 'protected-after.json', fingerprints(PG, DB))
        self.compose_run('up', '-d', 'odoo')
        self.health(PREVIEW_PORT)
        require(json.loads((self.state / 'protected-after.json').read_text()) == fingerprints(PG, DB),
                'protected data changed after HTTP')
        self.complete_prepare(manifest, attachments)

    def check_report_version(self, expected):
        actual = sql(PG, DB, "SELECT state,latest_version FROM ir_module_module "
                             "WHERE name='baseer_profit_loss_report'").strip()
        require(actual == 'installed|' + expected, 'unexpected report module version')

    def complete_prepare(self, manifest, attachments):
        manifest['attachments'] = attachments
        manifest['source_sha'] = self.source_sha
        manifest['live_sha'] = self.live_sha
        manifest['release'] = str(self.release)
        save(self.state / 'inventory.json', manifest)
        self.receipt('prepare', {'state': str(self.state), 'source_sha': self.source_sha, 'live_sha': self.live_sha,
                                'previous_qa_sha': self.qa_sha, 'snapshot': SNAPSHOT,
                                'archive_sha256': manifest['archives'], 'attachments': attachments,
                                'old_databases': len(manifest['old_databases']), 'network': NETWORK, 'http': 200})

    def verify_source(self):
        signed = Path(os.environ['QA_REFRESH_SOURCE_DIR'])
        source = json.loads((self.state / 'source-manifest.json').read_text())
        require(set(source) == set(SOURCE_DIRS)
                and (self.release / 'RELEASE_COMMIT').read_text().strip() == self.source_sha
                and source == {name: tree_hash(signed / name) for name in SOURCE_DIRS}
                and source == {name: tree_hash(self.release / name) for name in SOURCE_DIRS},
                'candidate source drift')

    def verify_runtime(self, switched):
        require(run(['systemctl', 'is-active', FIREWALL_UNIT.name]).strip() == 'active',
                'candidate firewall service inactive')
        expected_source = BASE / 'current' if switched else self.release
        expected_config = CONFIG / 'odoo.conf' if switched else self.config
        config = configparser.ConfigParser()
        config.read(expected_config)
        options = config['options']
        require(all(options.get(key) == value for key, value in {
            'db_host': 'db', 'db_name': DB, 'dbfilter': '^' + DB + '$',
            'db_user': 'qa_runner', 'max_cron_threads': '0',
        }.items()), 'candidate Odoo connected to an unexpected database')
        for name, image, mounts in (
            (PG, PG_IMAGE, {'/var/lib/postgresql/data': ('volume', PROJECT + '-postgres', True)}),
            (ODOO, ODOO_IMAGE, {'/var/lib/odoo': ('volume', PROJECT + '-odoo', True),
             '/etc/odoo/odoo.conf': ('bind', str(expected_config), False),
             '/mnt/baseer-addons': ('bind', str(expected_source / 'custom_addons'), False),
             '/mnt/third-party-addons': ('bind', str(expected_source / 'third_party_addons'), False)})):
            item = inspect(name)
            actual = {m['Destination']: (m['Type'], m.get('Name') if m['Type'] == 'volume' else m['Source'], m['RW'])
                      for m in item['Mounts']}
            if name == ODOO and '/mnt/extra-addons' in actual:
                kind, volume_name, writable = actual.pop('/mnt/extra-addons')
                require(kind == 'volume' and writable and not any(volume(volume_name).iterdir()),
                        'unexpected vendor extra-addons volume')
            ports = item['HostConfig']['PortBindings'] or {}
            offset = QA_PORT if switched else PREVIEW_PORT
            expected_ports = {f'{target}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(offset + index)}]
                              for index, target in enumerate((8069, 8072))} if name == ODOO else {}
            require(item['Image'] == image and item['State']['Running']
                    and item['HostConfig']['RestartPolicy']['Name'] == 'no'
                    and item['HostConfig']['Dns'] == [PGIP]
                    and set(item['NetworkSettings']['Networks']) == {NETWORK}
                    and ports == expected_ports and actual == mounts, 'candidate runtime identity mismatch')

    def verify(self, switched=False):
        self.guards(switched)
        self.verify_runtime(switched)
        inventory = json.loads((self.state / 'inventory.json').read_text())
        require(inventory['snapshot'] == SNAPSHOT and inventory['archives'] == self.snapshot_archives()
                and inventory['source_sha'] == self.source_sha and inventory['live_sha'] == self.live_sha
                and inventory['previous_qa_sha'] == self.qa_sha, 'candidate inventory identity mismatch')
        self.verify_source()
        require(json.loads((self.state / 'protected-after.json').read_text()) == fingerprints(PG, DB), 'protected data drift')
        self.namespace_test()
        self.neutral_guard()
        self.check_report_version('19.0.1.1.4')
        self.attachments()
        self.health(QA_PORT if switched else PREVIEW_PORT)
        return {'source_sha': self.source_sha, 'live_sha': self.live_sha, 'http': 200, 'archives_verified': len(inventory['archives'])}

    def switch(self):
        self.start('switch')
        self.verify()
        previous = (BASE / 'current').resolve(strict=True)
        require(str(previous) == json.loads((self.state / 'inventory.json').read_text())['old_source'], 'old QA source moved')
        config_names = ('compose.yaml', 'runtime.env', 'odoo.conf', 'deploy.env')
        rollback = self.state / 'previous-config'
        rollback.mkdir(mode=0o700, exist_ok=False)
        for name in config_names:
            path = CONFIG / name
            require(path.is_file() and not path.is_symlink(), 'unexpected QA configuration path')
            metadata = path.stat()
            copy = rollback / name
            shutil.copy2(path, copy)
            os.chown(copy, metadata.st_uid, metadata.st_gid)
            require(digest(path) == digest(copy), 'QA config recovery copy mismatch')
        old_unit = 'baseer-qa-refresh.service'
        new_unit = BOOT_UNIT.name
        unit_path = BOOT_UNIT
        require(not unit_path.exists() and not unit_path.is_symlink(), 'candidate service already exists')
        old_enabled = run(['systemctl', 'is-enabled', old_unit], check=False)
        old_active = run(['systemctl', 'is-active', old_unit], check=False)
        poller_active = run(['systemctl', 'is-active', TIMER], check=False) is not None
        save(self.state / 'previous-boot.json', {'old_unit': old_unit,
             'enabled': old_enabled.strip() if old_enabled else None,
             'active': old_active.strip() if old_active else None,
             'timer_active': poller_active, 'old_source': str(previous),
             'config_hashes': {name: digest(rollback / name) for name in config_names}})
        try:
            if poller_active:
                run(['systemctl', 'stop', TIMER])
            run(['docker', 'stop', QODOO])
            run(['docker', 'stop', ODOO])
            link = BASE / ('refresh-current-' + self.state.name)
            link.symlink_to(self.release)
            os.replace(link, BASE / 'current')
            save(CONFIG / 'odoo.conf', self.config.read_text())
            os.chown(CONFIG / 'odoo.conf', 0, 101)
            os.chmod(CONFIG / 'odoo.conf', 0o640)
            save(CONFIG / 'runtime.env', (self.state / 'app.env').read_text())
            updates = dict(QA_DATABASE=DB, QA_DB_CONTAINER=PG, QA_ODOO_VOLUME=PROJECT + '-odoo',
                           QA_COMPOSE_PROJECT=PROJECT, QA_LOGIN_URL='http://127.0.0.1:18134/web/login',
                           QA_ADDONS_PATH=ADDONS)
            env = (rollback / 'deploy.env').read_text().splitlines()
            lines = []
            for line in env:
                key = line.partition('=')[0]
                lines.append(key + '=' + updates.pop(key) if key in updates else line)
            lines.extend(key + '=' + value for key, value in updates.items())
            save(CONFIG / 'deploy.env', '\n'.join(lines))
            config = self.compose_config(BASE / 'current', QA_PORT, CONFIG / 'odoo.conf')
            save(CONFIG / 'compose.yaml', config)
            save(self.compose, config)
            self.compose_run('up', '-d', 'odoo')
            result = self.verify(True)
            # Reboot starts firewall first; Docker restart policies remain disabled.
            save(unit_path,
                 f'[Unit]\nRequires=docker.service {FIREWALL_UNIT.name}\n'
                 f'After=docker.service {FIREWALL_UNIT.name}\n[Service]\nType=oneshot\n'
                 'RemainAfterExit=yes\nExecStart=/usr/bin/docker compose -p ' + PROJECT +
                 ' -f /etc/baseer-qa/compose.yaml up -d\n[Install]\nWantedBy=multi-user.target')
            run(['systemctl', 'daemon-reload'])
            run(['systemctl', 'disable', old_unit])
            run(['systemctl', 'enable', new_unit])
            if poller_active:
                run(['systemctl', 'start', TIMER])
            self.receipt('switch', result)
        except BaseException:
            run(['docker', 'stop', ODOO], check=False)
            run(['systemctl', 'disable', new_unit], check=False)
            if unit_path.exists():
                unit_path.unlink()
            run(['systemctl', 'daemon-reload'], check=False)
            if old_enabled and old_enabled.strip() == 'enabled':
                run(['systemctl', 'enable', old_unit])
            for name in config_names:
                copy = rollback / name
                shutil.copy2(copy, CONFIG / name)
                metadata = copy.stat()
                os.chown(CONFIG / name, metadata.st_uid, metadata.st_gid)
            link = BASE / ('rollback-current-' + self.state.name)
            link.symlink_to(previous)
            os.replace(link, BASE / 'current')
            run(['docker', 'start', QODOO])
            run(['curl', '-fsSL', '--retry', '10', '--retry-connrefused',
                 '--max-time', '10', 'http://127.0.0.1:18134/web/login'])
            if poller_active:
                run(['systemctl', 'start', TIMER])
            save(self.state / 'rollback.receipt.json', {'old_source': str(previous), 'old_odoo_restarted': True})
            raise


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    require(len(args) == 4 and args[0] in ('prepare', 'resume', 'finance', 'switch', 'verify'), 'expected stage RUNID LIVE_SHA QA_SHA')
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
        stage = args[0]
        if stage == 'resume':
            stage = engine.recovery_stage()
        elif stage == 'finance':
            stage = 'financial'
        print((engine.state / (stage + '.receipt.json')).read_text())


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('QA_REFRESH=FAILED ' + str(error), file=sys.stderr)
        sys.exit(1)
