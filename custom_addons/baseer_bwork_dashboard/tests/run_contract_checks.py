"""Standalone pure checks, explicitly not an Odoo runtime or ORM test runner."""
import importlib.util
import pathlib
import sys
import types
import unittest


def main():
    addons = pathlib.Path(__file__).resolve().parents[2]
    for name in ('odoo', 'odoo.addons', 'odoo.addons.baseer_bchat',
                 'odoo.addons.baseer_bwork_dashboard', 'odoo.addons.baseer_bwork_dashboard.tests'):
        package = types.ModuleType(name)
        package.__path__ = []
        sys.modules[name] = package

    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    load('odoo.addons.baseer_bchat.contracts', addons / 'baseer_bchat/contracts.py')
    load('odoo.addons.baseer_bwork_dashboard.contracts', addons / 'baseer_bwork_dashboard/contracts.py')
    test_module = load('odoo.addons.baseer_bwork_dashboard.tests.test_contracts',
                       addons / 'baseer_bwork_dashboard/tests/test_contracts.py')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(test_module))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
