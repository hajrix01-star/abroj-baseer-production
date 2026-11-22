#!/usr/bin/env python3
"""Pure parser for the existing private QA Tailscale Serve route.

The schema follows Tailscale's ipn.ServeConfig: TCP, Web/Handlers and
AllowFunnel. This module does not contact Tailscale or make route changes.
"""
import json


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
