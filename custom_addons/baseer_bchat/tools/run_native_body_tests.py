"""Run native controller regressions under Odoo without a database or server.

Load only the two pure contracts, real controller, and focused test module.
The addon's model registration and unrelated database-backed tests are skipped.
"""
import argparse
import importlib.util
from pathlib import Path
import sys
import types
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--addon-root', type=Path, required=True)
    addon = parser.parse_args().addon_root.resolve()
    root = 'odoo.addons.baseer_bchat'
    for name, path in ((root, addon), (root + '.controllers', addon / 'controllers'),
                       (root + '.tests', addon / 'tests')):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
    for suffix in ('contracts', 'media_contracts', 'controllers.media_api',
                   'tests.test_native_upload_body'):
        path = addon.joinpath(*suffix.split('.')).with_suffix('.py')
        spec = importlib.util.spec_from_file_location(root + '.' + suffix, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    tests = sys.modules[root + '.tests.test_native_upload_body']
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests.BChatNativeUploadBodyCase)
    if suite.countTestCases() < 9:
        raise RuntimeError('The native controller regression suite is incomplete')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
