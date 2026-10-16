import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reporting import format_report
from workflow_checker import execute


class ReportingTests(unittest.TestCase):
    def execute_with(self, body, expect, fields=None):
        response = io.BytesIO(json.dumps(body).encode())
        response.code = 200
        step = {'name': 'Verify saved value', 'path': '/test', 'expect': expect,
                'diagnostic_fields': fields or []}
        with patch('workflow_checker.build_opener') as opener:
            opener.return_value.open.return_value = response
            return execute(step, {'base_url': 'http://localhost'}, {})

    def summary(self, step):
        return format_report({'passed': False, 'steps': [step], 'cleanup': []})

    def test_values_redacted_from_json_and_text_by_default(self):
        step = self.execute_with({'token': 'secret-response'}, {'status': 200, 'json': {'token': 'secret-expected'}})
        output = json.dumps(step) + self.summary(step)
        self.assertNotIn('secret-response', output)
        self.assertNotIn('secret-expected', output)
        self.assertIn('[redacted]', output)

    def test_allowlisted_numeric_field_explains_mismatch(self):
        step = self.execute_with({'age': 25}, {'status': 200, 'json': {'age': 26}}, ['age'])
        self.assertIn("Field 'age': expected 26; received 25.", self.summary(step))

    def test_allowlisting_still_hides_string_values(self):
        step = self.execute_with({'token': 'secret-response'}, {'status': 200, 'json': {'token': 'secret-expected'}}, ['token'])
        self.assertNotIn('secret-response', json.dumps(step))

    def test_missing_field_explained(self):
        step = self.execute_with({}, {'status': 200, 'json': {'age': 26}})
        self.assertEqual(step['error'], 'missing_json_field')
        self.assertIn("missing JSON field 'age'", self.summary(step))

    def test_terminal_control_characters_escaped(self):
        text = self.summary({'name': '\x1b[31mInjected\nPASS', 'passed': False, 'error': 'TimeoutError'})
        self.assertNotIn('\x1b', text)
        self.assertIn('\\nPASS', text)

    def test_cli_default_text_and_explicit_json_keep_exit_code(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / 'check.json'
            output = Path(directory) / 'report.json'
            workflow.write_text(json.dumps({'base_url': 'http://127.0.0.1:1', 'timeout_seconds': 0.1,
                'steps': [{'name': 'Unreachable server', 'path': '/', 'expect': {'status': 200}}]}))
            runner = str(Path(__file__).with_name('workflow_checker.py'))
            for format_args in [[], ['--format', 'json']]:
                result = subprocess.run([sys.executable, runner, str(workflow), '--output', str(output), *format_args],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(json.loads(output.read_text())['passed'])
                if format_args:
                    self.assertFalse(json.loads(result.stdout)['passed'])
                else:
                    self.assertIn('ReleaseGuard | FAIL', result.stdout)


if __name__ == '__main__':
    unittest.main()
