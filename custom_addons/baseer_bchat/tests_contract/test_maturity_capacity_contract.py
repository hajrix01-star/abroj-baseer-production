"""Pure metric/output checks, not evidence of an executed Odoo capacity run."""
import importlib.util
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'tests' / 'maturity_capacity_probe.py'
SPEC = importlib.util.spec_from_file_location('maturity_capacity_pure_helpers', SOURCE)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class MaturityCapacityOutputCase(unittest.TestCase):
    def test_json_size_counts_utf8_not_characters(self):
        self.assertGreater(PROBE._json_size({'label': 'عربي'}), len('{"label": "عربي"}'))

    def test_summary_uses_only_successful_nonwarmup_raw_values(self):
        def sample(value, *, warmup=False, result='ok'):
            return {'operation': 'history', 'warmup': warmup, 'result': result,
                    'elapsed_ms': value, 'row_count': 30, 'response_utf8_bytes': 4096}
        summary = PROBE._aggregate([sample(999, warmup=True), sample(1), sample(3),
                                    sample(1000, result='error')])
        self.assertEqual(summary['history'], {
            'samples': 2, 'median_ms': 2.0, 'max_ms': 3,
            'row_count_min': 30, 'row_count_max': 30, 'response_utf8_bytes_max': 4096,
        })

    def test_failure_metadata_never_exports_exception_body(self):
        error = RuntimeError('Do not export SQL or private request text')
        self.assertEqual(PROBE._safe_error(error), {'class': 'RuntimeError', 'sqlstate': None})

    def test_empty_samples_do_not_invent_metrics(self):
        self.assertEqual(PROBE._aggregate([]), {})

    def test_declared_plan_is_small_and_fixed(self):
        self.assertEqual(PROBE.SEQUENTIAL_SAMPLES, 10)
        self.assertEqual(PROBE.CONCURRENT_ROUNDS, 10)
        self.assertEqual(PROBE.MAX_ATTEMPTS, 6)
        self.assertEqual(PROBE.STATEMENT_TIMEOUT_MS, 10000)
        self.assertEqual(PROBE.LOCK_TIMEOUT_MS, 2000)
        self.assertEqual(PROBE.TOTAL_BUDGET_SECONDS, 300)


if __name__ == '__main__':
    unittest.main()
