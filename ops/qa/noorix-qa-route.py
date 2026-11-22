#!/usr/bin/env python3
"""Validate and manage the fixed private QA route and its restart rehearsal."""
from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


QA_HOSTPORT = 'baseer-live-qa.tail938958.ts.net:8443'
BACKENDS = {'http://127.0.0.1:18134': 18134, 'http://127.0.0.1:18140': 18140}
LOCKS = frozenset({'refresh', 'deploy', 'release-poller'})
TAILSCALE = '/usr/bin/tailscale'


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate configuration key')
        result[key] = value
    return result


def pick_backend(serve_json):
    """Return the exact QA backend port, or fail closed for an unsafe route.

    The caller must get fresh status from the intended host and prove the
    selected listener's identity separately; this parser is not a lock or a
    cutover operation. Unrelated ports are permitted and never changed.
    """
    if not isinstance(serve_json, str) or len(serve_json) > 1024 * 1024:
        raise ValueError('invalid serve configuration')
    try:
        config = json.loads(serve_json, object_pairs_hook=_object)
    except (ValueError, TypeError):
        raise ValueError('invalid serve configuration') from None
    if not isinstance(config, dict) or set(config) - {'TCP', 'Web', 'AllowFunnel', 'Services', 'Foreground'}:
        raise ValueError('unsupported serve configuration')
    if config.get('Foreground') or config.get('Services'):
        raise ValueError('unsupported concurrent serve configuration')
    tcp, web, funnel = config.get('TCP'), config.get('Web'), config.get('AllowFunnel', {})
    if not isinstance(tcp, dict) or not isinstance(web, dict) or not isinstance(funnel, dict):
        raise ValueError('invalid serve configuration')
    handler = tcp.get('8443')
    if not isinstance(handler, dict) or set(handler) != {'HTTPS'} or handler['HTTPS'] is not True:
        raise ValueError('QA port is not private HTTPS')
    if any(not isinstance(value, bool) for value in funnel.values()):
        raise ValueError('invalid funnel configuration')
    if any(name.endswith(':8443') and value for name, value in funnel.items()):
        raise ValueError('QA port permits public funnel')
    routes = [name for name in web if name.endswith(':8443')]
    if routes != [QA_HOSTPORT]:
        raise ValueError('QA host is missing or ambiguous')
    server = web[QA_HOSTPORT]
    if not isinstance(server, dict) or set(server) != {'Handlers'}:
        raise ValueError('unsupported QA web server')
    handlers = server['Handlers']
    if not isinstance(handlers, dict) or set(handlers) != {'/'}:
        raise ValueError('unsupported QA handlers')
    root = handlers['/']
    if (not isinstance(root, dict) or set(root) != {'Proxy'} or
            not isinstance(root['Proxy'], str) or root['Proxy'] not in BACKENDS):
        raise ValueError('unsupported QA backend')
    return BACKENDS[root['Proxy']]


class RouteChangeError(RuntimeError):
    def __init__(self, state):
        self.state = state
        super().__init__('QA route change failed; state=' + state)


def change_route(previous, target, *, locks, run, verify_backend, verify_boot_guard, verify_receipt):
    """Switch only port 8443, retaining both applications and their databases.

    The trusted host supplies ALL contracts: ``locks()`` returns a context
    yielding the names of the three held QA locks; ``run(argv)`` runs without
    a shell, checks exit status and returns stdout as text; ``verify_backend``
    proves exact protected DB identity and health for its port;
    ``verify_boot_guard`` proves safe restart ordering; and ``verify_receipt``
    authenticates the financial acceptance for this exact target and data.
    Only a literal True from each verifier is accepted. These injected
    contracts must themselves be secured and independently reviewed.

    Existing data is never copied or restored. Returning to a prior backend
    after exposure may hide writes made on the target; caller must prevent or
    reconcile them. An unrecognized post-failure route is never overwritten.
    """
    if (type(previous) is not int or type(target) is not int or
            {previous, target} != {18134, 18140}):
        raise ValueError('expected the two distinct QA backends')
    if not all(callable(x) for x in (locks, run, verify_backend, verify_boot_guard, verify_receipt)):
        raise ValueError('all host safety contracts are required')

    def status():
        return pick_backend(run([TAILSCALE, 'serve', 'status', '--json']))

    def set_port(port):
        run([TAILSCALE, 'serve', '--bg', '--https=8443', 'http://127.0.0.1:' + str(port)])

    with locks() as held:
        if not isinstance(held, (set, frozenset)) or held != LOCKS:
            raise ValueError('all three QA locks must be held')
        if status() != previous:
            raise ValueError('previous QA route changed')
        if (verify_boot_guard(previous, target) is not True or
                verify_receipt(target) is not True or
                verify_backend(previous) is not True or verify_backend(target) is not True):
            raise ValueError('QA safety gate failed')

        try:
            set_port(target)
            if (status() != target or verify_backend(target) is not True or
                    verify_boot_guard(previous, target) is not True):
                raise ValueError('target postcondition failed')
        except Exception:
            # A CLI failure may occur after the route changed. Inspect before
            # acting and never overwrite an unknown or public configuration.
            try:
                current = status()
                if verify_backend(previous) is not True:
                    raise ValueError('previous backend is not healthy')
                if current != previous:
                    set_port(previous)
                    if status() != previous or verify_backend(previous) is not True:
                        raise ValueError('previous route not verified')
            except Exception:
                raise RouteChangeError('unresolved') from None
            raise RouteChangeError('restored') from None
    return target


PREVIEW = Path('/srv/baseer-qa/noorix-preview')
PROTECTED_HELPER = '/usr/local/lib/baseer-qa-refresh/prepare-noorix-preview.py'
BOOT_UNIT = 'baseer-qa-noorix-preview.service'
STAGING_RUN = '45045444123'
REPORT_COMMIT = '4a4f06cda34a5a6e2817e9e118f95c9945c4f2ab'
RESTART_PROOF = PREVIEW / 'restart-proof.json'
PREVIEW_CONTAINERS = ('baseer-qa-refresh-20261121b-db-1', 'baseer-qa-refresh-20261121b-odoo-1')


def host_command(argv, timeout=60):
    return subprocess.run(argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, timeout=timeout).stdout


@contextmanager
def host_locks():
    import fcntl

    with ExitStack() as stack:
        for name in ('baseer-qa-refresh', 'baseer-qa-deploy', 'baseer-qa-release-poller'):
            fd = os.open('/var/lock/' + name + '.lock', os.O_NOFOLLOW | os.O_RDWR)
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError('unsafe QA operation lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield LOCKS


def proof_lines(path):
    if path.resolve(strict=True) != path:
        raise ValueError('invalid QA acceptance path')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or info.st_size > 1024 * 1024:
        raise ValueError('unprotected QA acceptance result')
    return [line for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('QA_ACCEPT_')]


def staged_acceptance(port, log_name):
    if port != 18140 or not re.fullmatch(r'[.]acceptance[.][A-Za-z0-9]{6}', log_name):
        return False
    source = (PREVIEW / 'current').resolve(strict=True)
    if not re.fullmatch('/srv/baseer-qa/releases/4a4f06cda34a-run-' + STAGING_RUN + r'-[0-9]{8}T[0-9]{6}Z',
                        str(source)):
        return False
    if (source / 'RELEASE_COMMIT').read_text().strip() != REPORT_COMMIT:
        return False
    backup = Path('/srv/baseer-qa/backups') / ('pre-' + source.name)
    result = (backup / 'result.env').read_text().splitlines()
    expected = {'QA_DEPLOY=GO', 'RELEASE=' + str(source), 'BACKUP=' + str(backup),
                'COMMIT=' + REPORT_COMMIT, 'MODULES=baseer_profit_loss_report',
                'RELEASE_ID=baseer-2026-11-22-noorix-net-estimate-preview'}
    if not expected.issubset(result):
        return False
    log = PREVIEW / log_name
    if log.stat().st_mtime_ns < (backup / 'result.env').stat().st_mtime_ns:
        return False
    lines = proof_lines(log)
    return len(lines) == 3 and all(re.fullmatch(pattern, line) for pattern, line in zip((
        r'QA_ACCEPT_NOORIX=18 unique gross=[0-9]+[.][0-9]{2} net=[0-9]+[.][0-9]{2} difference=0[.]00',
        r'QA_ACCEPT_RECONCILED=gross report_excel_pdf_rows=[1-9][0-9]* difference=0[.]00',
        r'QA_ACCEPT_RECONCILED=net report_excel_pdf_rows=[1-9][0-9]* difference=0[.]00',
    ), lines))


def backend_ready(port):
    if port == 18140:
        host_command(['/usr/bin/python3', '-I', PROTECTED_HELPER, '--verify-promoted'])
        db = 'baseer_qa_20261121b'
    elif port == 18134:
        config = Path('/etc/baseer-qa/deploy.env').read_text().splitlines()
        if 'QA_DATABASE=baseer_qa_20261023' not in config:
            return False
        app = json.loads(host_command(['/usr/bin/docker', 'inspect', 'baseer-qa-refresh-20261023-odoo-1']))[0]
        if not app['State']['Running'] or (app['HostConfig']['PortBindings'] or {}).get('8069/tcp') != [
            {'HostIp': '127.0.0.1', 'HostPort': '18134'}
        ]:
            return False
        db = 'baseer_qa_20261023'
    else:
        return False
    return host_command(['/usr/bin/curl', '--silent', '--fail', '--max-time', '6', '--output', '/dev/null',
                         '--write-out', '%{http_code}', f'http://127.0.0.1:{port}/web/login?db={db}']) == '200'


def boot_ready(_old, _new):
    return (host_command(['/usr/bin/systemctl', 'is-enabled', BOOT_UNIT]).strip() == 'enabled'
            and host_command(['/usr/bin/systemctl', 'is-active', BOOT_UNIT]).strip() == 'active')


def runtime_stamp():
    items = json.loads(host_command(['/usr/bin/docker', 'inspect', *PREVIEW_CONTAINERS]))
    if len(items) != 2 or any(item['Name'] != '/' + name or not item['State']['Running']
                             for item, name in zip(items, PREVIEW_CONTAINERS)):
        raise ValueError('the two preview containers must be running')
    return [{'id': item['Id'], 'started_at': item['State']['StartedAt']} for item in items]


def write_restart_proof(stamp):
    fd, name = tempfile.mkstemp(prefix='.restart-proof-', dir=PREVIEW)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(stamp, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, RESTART_PROOF)
        directory = os.open(PREVIEW, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


def restart_rehearsed():
    if RESTART_PROOF.is_symlink() or not RESTART_PROOF.is_file():
        return False
    info = RESTART_PROOF.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
        return False
    return json.loads(RESTART_PROOF.read_text()) == runtime_stamp()


def rehearse_restart():
    read_route = lambda: pick_backend(host_command([TAILSCALE, 'serve', 'status', '--json']))
    service_stopped = False
    try:
        with host_locks():
            if read_route() != 18134 or not backend_ready(18134) or not backend_ready(18140):
                raise ValueError('both QA backends must pass before rehearsal')
            before = runtime_stamp()
            host_command(['/usr/bin/systemctl', 'stop', BOOT_UNIT])
            service_stopped = True
            for name in reversed(PREVIEW_CONTAINERS):
                host_command(['/usr/bin/docker', 'stop', '--time', '35', name], timeout=45)
            items = json.loads(host_command(['/usr/bin/docker', 'inspect', *PREVIEW_CONTAINERS]))
            if len(items) != 2 or any(item['State']['Running'] for item in items) or items[0]['State']['ExitCode'] != 0:
                raise ValueError('preview did not stop cleanly')
    finally:
        if service_stopped:
            # The systemd unit reacquires the locks and verifies PostgreSQL
            # before starting Odoo. The existing QA service remains in place.
            host_command(['/usr/bin/systemctl', 'start', BOOT_UNIT], timeout=185)
    with host_locks():
        after = runtime_stamp()
        if (read_route() != 18134 or not boot_ready(18134, 18140) or
                not backend_ready(18134) or not backend_ready(18140) or
                any(a['id'] != b['id'] or a['started_at'] == b['started_at'] for a, b in zip(after, before))):
            raise ValueError('preview cold restart did not pass')
        write_restart_proof(after)


def rollback_route():
    with host_locks():
        read_route = lambda: pick_backend(host_command([TAILSCALE, 'serve', 'status', '--json']))
        current = read_route()
        if not backend_ready(18134):
            raise ValueError('original QA backend is not healthy')
        if current == 18140:
            host_command([TAILSCALE, 'serve', '--bg', '--https=8443', 'http://127.0.0.1:18134'])
        if read_route() != 18134 or not backend_ready(18134):
            raise RouteChangeError('unresolved')


if __name__ == '__main__':
    if sys.argv[1:] == ['--backend']:
        try:
            print(pick_backend(sys.stdin.read(1048577)))
        except ValueError:
            sys.exit('invalid private QA route')
    elif len(sys.argv) == 3 and sys.argv[1] == '--switch' and os.geteuid() == 0:
        try:
            change_route(18134, 18140, locks=host_locks, run=host_command, verify_backend=backend_ready,
                         verify_boot_guard=lambda old, new: boot_ready(old, new) and restart_rehearsed(),
                         verify_receipt=lambda port: staged_acceptance(port, sys.argv[2]))
            print('QA_NOORIX_SWITCH=GO')
        except RouteChangeError as exc:
            sys.exit(str(exc))
        except (ValueError, KeyError, OSError, subprocess.SubprocessError):
            sys.exit('QA switch did not pass the required checks')
    elif sys.argv[1:] == ['--rehearse'] and os.geteuid() == 0:
        try:
            rehearse_restart()
            print('QA_NOORIX_RESTART=GO')
        except (ValueError, KeyError, OSError, subprocess.SubprocessError):
            sys.exit('QA restart rehearsal did not pass')
    elif sys.argv[1:] == ['--rollback'] and os.geteuid() == 0:
        try:
            rollback_route()
            print('QA_NOORIX_SWITCH=ROLLED_BACK')
        except (ValueError, KeyError, OSError, subprocess.SubprocessError, RouteChangeError):
            sys.exit('QA route rollback did not pass the required checks')
    else:
        sys.exit('expected protected QA route operation')
