import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deployment import atomic_write, compare, fingerprint, promote, read_baseline, tag


class DeploymentTests(unittest.TestCase):
    def report(self, spec=None, release='v1', environment='local', passed=True):
        return tag({'passed': passed, 'steps': [{'name': 'Save record', 'passed': passed}], 'cleanup': []}, spec or {'base_url': 'http://localhost:8002', 'steps': []}, environment, release)

    def test_fingerprint_ignores_formatting_and_key_order(self):
        self.assertEqual(fingerprint({'a': 1, 'b': 2}), fingerprint(json.loads('{ "b": 2, "a": 1 }')))

    def test_changed_workflow_or_environment_not_comparable(self):
        baseline = self.report()
        for current in [self.report(spec={'different': True}), self.report(environment='production')]:
            self.assertEqual(compare(current, baseline)['status'], 'not_comparable')

    def test_regression_identifies_step(self):
        result = compare(self.report(release='v2', passed=False), self.report())
        self.assertEqual(result['status'], 'regression')
        self.assertEqual(result['first_failing_step'], 'Save record')
        self.assertEqual(compare(self.report(release='v2'), self.report())['status'], 'passed')

    def test_failed_promotion_preserves_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            promote(path, self.report())
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                promote(path, self.report(passed=False))
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(read_baseline(path)['release'], 'v1')

    def test_interrupted_replace_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            promote(path, self.report())
            before = path.read_bytes()
            with patch('deployment.os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    promote(path, self.report(release='v2'))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_skipped_cleanup_cannot_be_promoted(self):
        report = self.report()
        report['cleanup'] = [{'name': 'Cleanup', 'skipped': True}]
        with self.assertRaises(ValueError):
            promote('unused.json', report)

    def test_corrupt_baseline_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.json'
            atomic_write(path, {'passed': False})
            with self.assertRaises(ValueError):
                read_baseline(path)


if __name__ == '__main__':
    unittest.main()
