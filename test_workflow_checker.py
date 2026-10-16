import copy
import json
import io
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from demo_api import make_server
from workflow_checker import run, execute


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def workflow(self):
        spec = json.loads(Path(__file__).with_name("example.json").read_text())
        spec["base_url"] = f"http://127.0.0.1:{self.server.server_port}"
        return spec

    def assert_removed(self, spec, report):
        with self.assertRaises(HTTPError) as caught:
            urlopen(spec["base_url"] + "/tasks/" + report["run_id"])
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

    def test_success_and_cleanup(self):
        spec = self.workflow()
        report = run(spec)
        self.assertTrue(report["passed"])
        self.assert_removed(spec, report)

    def test_broken_release_stops_and_cleans_up(self):
        spec = self.workflow()
        extra = copy.deepcopy(spec["steps"][1])
        extra["name"] = "Must not run"
        spec["steps"].append(extra)
        with patch.dict(os.environ, {"DEMO_BROKEN": "1"}):
            report = run(spec)
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["steps"]), 2)
        self.assertEqual(report["steps"][-1]["error"], "json_assertion_mismatch")
        self.assertTrue(report["cleanup"][0]["passed"])
        self.assert_removed(spec, report)

    def test_cleanup_failure_fails_run(self):
        spec = self.workflow()
        spec["cleanup"].append({"name": "Fail cleanup", "path": "/missing", "expect": {"status": 200}})
        self.assertFalse(run(spec)["passed"])

    def test_numeric_range_accepts_and_rejects(self):
        for value, expected in [(0.9, True), (1.1, False), ('0.9', False), (True, False)]:
            response = io.BytesIO(json.dumps({'soh': value}).encode())
            response.code = 200
            step = {'name': 'Predict', 'path': '/predict', 'expect': {'status': 200, 'json_ranges': {'soh': [0, 1]}}}
            with patch('workflow_checker.build_opener') as opener:
                opener.return_value.open.return_value = response
                self.assertEqual(execute(step, self.workflow(), {})['passed'], expected)

    def test_capture_failure_still_cleans_known_id(self):
        spec = self.workflow()
        spec["steps"][0]["capture"] = {"task_id": "missing"}
        report = run(spec)
        self.assertFalse(report["passed"])
        self.assertTrue(report["cleanup"][0]["passed"])
        self.assert_removed(spec, report)

    def test_invalid_config_rejected_before_requests(self):
        spec = self.workflow()
        spec["steps"][0]["path"] = "//other-host/"
        with self.assertRaises(ValueError):
            run(spec)

    def test_timeout_report_has_no_secret_exception_text(self):
        spec = self.workflow()
        with patch("workflow_checker.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError("secret-token")
            report = run(spec)
        self.assertFalse(report["passed"])
        self.assertNotIn("secret-token", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
