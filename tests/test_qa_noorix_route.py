import importlib.util
import json
from pathlib import Path
import unittest
from contextlib import contextmanager
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'qa_route', Path(__file__).resolve().parents[1] / 'ops/qa/noorix-qa-route.py')
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


class PrivateRouteTest(unittest.TestCase):
    def setUp(self):
        self.host = route.QA_HOSTPORT
        self.config = {'TCP': {'8443': {'HTTPS': True}},
                       'Web': {self.host: {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:18134'}}}}}

    def test_both_private_backends_and_unrelated_ports(self):
        self.config['AllowFunnel'] = {self.host: False, 'other.tail.ts.net:443': True}
        self.config['TCP']['443'] = {'HTTPS': True}
        self.config['Web']['other.tail.ts.net:443'] = {'Handlers': {'/': {'Proxy': 'http://127.0.0.1:1234'}}}
        self.assertEqual(route.pick_backend(json.dumps(self.config)), 18134)
        self.config['Web'][self.host]['Handlers']['/']['Proxy'] = 'http://127.0.0.1:18140'
        self.assertEqual(route.pick_backend(json.dumps(self.config)), 18140)

    def test_rejects_public_ambiguous_or_unexpected_configuration(self):
        for defect in ('funnel', 'otherhost_funnel', 'tcp', 'numeric', 'extra_host', 'extra_handler',
                       'remote', 'scheme', 'extra_path', 'foreground', 'service', 'proxy_object', 'unknown'):
            with self.subTest(defect=defect):
                self.setUp()
                root = self.config['Web'][self.host]['Handlers']['/']
                if defect == 'funnel': self.config['AllowFunnel'] = {self.host: True}
                if defect == 'otherhost_funnel': self.config['AllowFunnel'] = {'evil.ts.net:8443': True}
                if defect == 'tcp': self.config['TCP']['8443'] = {'TCPForward': 'localhost:18134'}
                if defect == 'numeric': self.config['TCP']['8443'] = {'HTTPS': 1}
                if defect == 'extra_host': self.config['Web']['other.ts.net:8443'] = self.config['Web'][self.host]
                if defect == 'extra_handler': self.config['Web'][self.host]['Handlers']['/websocket'] = root
                if defect == 'remote': root['Proxy'] = 'http://192.0.2.1:18134'
                if defect == 'scheme': root['Proxy'] = 'https://127.0.0.1:18134'
                if defect == 'extra_path': root['Proxy'] = 'http://127.0.0.1:18134/path'
                if defect == 'foreground': self.config['Foreground'] = {'other': {}}
                if defect == 'service': self.config['Services'] = {'other': {}}
                if defect == 'proxy_object': root['Proxy'] = {}
                if defect == 'unknown': self.config['NewUnknown'] = {}
                with self.assertRaises(ValueError): route.pick_backend(json.dumps(self.config))

    def test_rejects_duplicate_keys_and_invalid_json(self):
        for invalid in ('{"TCP":{},"TCP":{}}', 'null', '{}', '[1]', '{'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                route.pick_backend(invalid)


class CutoverTest(unittest.TestCase):
    def setUp(self):
        self.port = 18134
        self.events = []
        self.fail_after_apply = False
        self.unexpected = False
        self.unhealthy = set()

    @contextmanager
    def locks(self):
        self.events.append('lock')
        try:
            yield {'refresh', 'deploy', 'release-poller'}
        finally:
            self.events.append('unlock')

    def runner(self, argv):
        self.events.append(tuple(argv))
        if argv[-2:] == ['status', '--json']:
            return json.dumps({'TCP': {'8443': {'HTTPS': True}},
                               'Web': {route.QA_HOSTPORT: {'Handlers': {'/': {'Proxy':
                                   'http://127.0.0.1:' + str(self.port)}}}},
                               'AllowFunnel': {route.QA_HOSTPORT: self.unexpected}})
        self.assertEqual(argv[:4], ['/usr/bin/tailscale', 'serve', '--bg', '--https=8443'])
        self.port = int(argv[-1].split(':')[-1])
        if self.fail_after_apply and self.port == 18140:
            raise RuntimeError('synthetic failure after route changed')
        return ''

    def health(self, port):
        self.events.append(('health', port))
        return port not in self.unhealthy

    def change(self, **kwargs):
        args = dict(locks=self.locks, run=self.runner, verify_backend=self.health,
                    verify_boot_guard=lambda old, new: True, verify_receipt=lambda target: True)
        args.update(kwargs)
        return route.change_route(18134, 18140, **args)

    def test_switches_only_after_checks_and_verifies(self):
        self.assertEqual(self.change(), 18140)
        self.assertEqual(self.port, 18140)
        mutation = self.events.index(('/usr/bin/tailscale', 'serve', '--bg', '--https=8443',
                                      'http://127.0.0.1:18140'))
        self.assertIn(('health', 18134), self.events[:mutation])
        self.assertIn(('health', 18140), self.events[:mutation])
        self.assertIn(('health', 18140), self.events[mutation + 1:])
        self.assertEqual(self.events[-1], 'unlock')

    def test_after_command_failure_restores_only_healthy_previous(self):
        self.fail_after_apply = True
        with self.assertRaises(route.RouteChangeError) as error: self.change()
        self.assertEqual(error.exception.state, 'restored')
        self.assertEqual(self.port, 18134)
        self.assertIn(('/usr/bin/tailscale', 'serve', '--bg', '--https=8443',
                       'http://127.0.0.1:18134'), self.events)

    def test_failed_health_or_missing_contract_never_changes_route(self):
        self.unhealthy.add(18134)
        with self.assertRaises(ValueError): self.change()
        self.assertEqual(self.port, 18134)
        self.assertFalse(any(isinstance(e, tuple) and '--bg' in e for e in self.events))
        with self.assertRaises(ValueError): self.change(verify_receipt=None)
        with self.assertRaises(ValueError): self.change(verify_boot_guard=lambda a, b: 1)

    def test_unrecognized_postfailure_or_unhealthy_previous_never_overwritten(self):
        original_run = self.runner
        def unsafe(argv):
            if '--bg' in argv:
                self.port = 18140
                self.unexpected = True
                raise RuntimeError('failed')
            return original_run(argv)
        with self.assertRaises(route.RouteChangeError) as error: self.change(run=unsafe)
        self.assertEqual(error.exception.state, 'unresolved')
        self.assertEqual(self.port, 18140)
        self.setUp()
        def failed_with_old_down(argv):
            if '--bg' in argv:
                self.port = 18140
                self.unhealthy.add(18134)
                raise RuntimeError('failed')
            return original_run(argv)
        with self.assertRaises(route.RouteChangeError) as error: self.change(run=failed_with_old_down)
        self.assertEqual(error.exception.state, 'unresolved')
        self.assertEqual(self.port, 18140)

    def test_incomplete_locks_refuse_to_run_any_command(self):
        @contextmanager
        def partial():
            yield {'deploy'}
        with self.assertRaises(ValueError): self.change(locks=partial)
        self.assertEqual(self.events, [])

    def test_cold_restart_keeps_previous_route_and_records_both_restarted_containers(self):
        original_run = self.runner
        stamp = [{'id': name, 'started_at': 'before'} for name in route.PREVIEW_CONTAINERS]

        def restart_commands(argv, **kwargs):
            if argv[0] == route.TAILSCALE:
                return original_run(argv)
            self.events.append(tuple(argv))
            if argv[1] == 'inspect':
                return json.dumps([{'State': {'Running': False, 'ExitCode': 0}}] * 2)
            if argv[1] == 'start':
                for item in stamp:
                    item['started_at'] = 'after'
            return ''

        def read_stamp():
            return [item.copy() for item in stamp]

        with patch.object(route, 'host_locks', self.locks), patch.object(route, 'host_command', restart_commands), \
                patch.object(route, 'backend_ready', self.health), patch.object(route, 'boot_ready', return_value=True), \
                patch.object(route, 'runtime_stamp', read_stamp), patch.object(route, 'write_restart_proof') as proof:
            route.rehearse_restart()
        self.assertEqual(self.port, 18134)
        stopped = [x[-1] for x in self.events if isinstance(x, tuple) and x[:2] == ('/usr/bin/docker', 'stop')]
        self.assertEqual(stopped, list(reversed(route.PREVIEW_CONTAINERS)))
        proof.assert_called_once_with(stamp)
        self.assertFalse(any(isinstance(e, tuple) and '--bg' in e for e in self.events))


if __name__ == '__main__':
    unittest.main()
