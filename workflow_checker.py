"""Small, sequential HTTP workflow runner. No implicit retries of side effects."""
import argparse
import json
import math
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Do not forward credentials to a redirected destination.


def diagnostic_value(value, path, step):
    # Only explicitly allowlisted numeric/boolean fields may expose values.
    if path in step.get('diagnostic_fields', []) and (type(value) is bool or type(value) in (int, float) and math.isfinite(value)):
        return value
    return '[redacted]'


def lookup(value, path):
    for part in path.split(".") if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def render(value, variables):
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    if not isinstance(value, str):
        return value
    pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}"
    match = re.fullmatch(pattern, value)
    if match:
        return variables[match[1]]
    return re.sub(pattern, lambda m: str(variables[m[1]]), value)


def validate(spec):
    if not isinstance(spec, dict):
        raise ValueError("Workflow must be an object")
    base = urlsplit(spec.get("base_url", ""))
    if base.scheme not in ("http", "https") or not base.netloc or base.username or base.password:
        raise ValueError("base_url must be HTTP(S), without embedded credentials")
    if base.query or base.fragment:
        raise ValueError("base_url must not contain a query or fragment")
    timeout = spec.get("timeout_seconds", 10)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 120:
        raise ValueError("timeout_seconds must be in (0, 120]")
    if not isinstance(spec.get("steps"), list) or not spec["steps"]:
        raise ValueError("steps must be a non-empty list")
    if not isinstance(spec.get("cleanup", []), list):
        raise ValueError("cleanup must be a list")
    names = set()
    for step in spec["steps"] + spec.get("cleanup", []):
        if not isinstance(step, dict) or not isinstance(step.get("name"), str) or not step["name"]:
            raise ValueError("Every step needs a name")
        if step["name"] in names:
            raise ValueError("Step names must be unique")
        names.add(step["name"])
        fields = step.get('diagnostic_fields', [])
        if not isinstance(fields, list) or any(not isinstance(field, str) for field in fields):
            raise ValueError('diagnostic_fields must be a list of non-sensitive JSON paths')
        path = step.get("path", "")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Step paths must begin with a single slash")
        if step.get("method", "GET") not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}:
            raise ValueError("Unsupported HTTP method")
        expect = step.get("expect")
        if not isinstance(expect, dict) or type(expect.get("status")) is not int:
            raise ValueError("Every step needs expect.status")
        if not isinstance(expect.get("json", {}), dict) or not isinstance(step.get("capture", {}), dict):
            raise ValueError("JSON assertions and captures must be mappings")
        ranges = expect.get("json_ranges", {})
        if not isinstance(ranges, dict):
            raise ValueError("json_ranges must be a mapping")
        for bounds in ranges.values():
            if not isinstance(bounds, list) or len(bounds) != 2 or any(type(x) not in (int, float) or not math.isfinite(x) for x in bounds) or bounds[0] > bounds[1]:
                raise ValueError("Each JSON range needs finite [minimum, maximum] bounds")


def execute(step, spec, variables):
    started = time.monotonic()
    result = {"name": step["name"], "passed": False}
    try:
        resolved = render(step, variables)
        base = spec["base_url"].rstrip("/")
        path = resolved["path"]
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Invalid rendered path")
        headers = render(spec.get("headers", {}), variables) | resolved.get("headers", {})
        body = None
        if "json" in resolved:
            body = json.dumps(resolved["json"]).encode()
            headers.setdefault("Content-Type", "application/json")
        request = Request(base + path, data=body, headers=headers, method=resolved.get("method", "GET"))
        opener = build_opener(NoRedirect())
        try:
            response = opener.open(request, timeout=spec.get("timeout_seconds", 10))
        except HTTPError as exc:
            response = exc  # HTTP errors are responses and can be asserted.
        with response:
            result["status"] = response.code
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            result["error"] = "response_too_large"
            return result
        if result["status"] != resolved["expect"]["status"]:
            result["error"] = "status_mismatch"
            result['details'] = {'expected_status': resolved['expect']['status']}
            return result
        assertions = resolved["expect"].get("json", {})
        captures = resolved.get("capture", {})
        ranges = resolved["expect"].get("json_ranges", {})
        if assertions or captures or ranges:
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                result['error'] = 'invalid_json_response'
                return result
            for path, expected in assertions.items():
                try:
                    actual = lookup(data, path)
                except (KeyError, IndexError, TypeError, ValueError):
                    result['error'] = 'missing_json_field'
                    result['details'] = {'field': path}
                    return result
                if type(actual) is not type(expected) or actual != expected:
                    result["error"] = "json_assertion_mismatch"
                    result['details'] = {'field': path, 'expected': diagnostic_value(expected, path, step), 'actual': diagnostic_value(actual, path, step)}
                    return result
            for path, bounds in ranges.items():
                try:
                    actual = lookup(data, path)
                except (KeyError, IndexError, TypeError, ValueError):
                    result['error'] = 'missing_json_field'
                    result['details'] = {'field': path}
                    return result
                if type(actual) not in (int, float) or not math.isfinite(actual) or not bounds[0] <= actual <= bounds[1]:
                    result["error"] = "json_range_mismatch"
                    result['details'] = {'field': path, 'minimum': diagnostic_value(bounds[0], path, step), 'maximum': diagnostic_value(bounds[1], path, step), 'actual': diagnostic_value(actual, path, step)}
                    return result
            try:
                captured = {name: lookup(data, path) for name, path in captures.items()}
            except (KeyError, IndexError, TypeError, ValueError):
                result['error'] = 'capture_failed'
                return result
            variables.update(captured)
        result["passed"] = True
    except Exception as exc:
        # Exception messages can contain URLs, tokens, and payloads. Keep reports redacted.
        result["error"] = type(exc).__name__
    finally:
        result["duration_ms"] = round((time.monotonic() - started) * 1000, 2)
    return result


def run(spec):
    validate(spec)
    variables = {"run_id": uuid.uuid4().hex}
    for name, env_name in spec.get("env", {}).items():
        variables[name] = os.environ[env_name]
    report = {"run_id": variables["run_id"], "passed": False, "steps": [], "cleanup": []}
    try:
        for step in spec["steps"]:
            result = execute(step, spec, variables)
            report["steps"].append(result)
            if not result["passed"]:
                break
    finally:
        for step in spec.get("cleanup", []):
            if all(name in variables for name in step.get("requires", [])):
                report["cleanup"].append(execute(step, spec, variables))
            else:
                report["cleanup"].append({"name": step["name"], "skipped": True, "reason": "missing_capture"})
    report["passed"] = all(r["passed"] for r in report["steps"]) and all(
        r.get("passed", r.get("skipped", False)) for r in report["cleanup"]
    )
    report['steps_not_run'] = len(spec['steps']) - len(report['steps'])
    return report


def load(path):
    source = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() == ".json":
        return json.loads(source)
    try:
        import yaml
    except ImportError:
        raise ValueError("Install the project dependencies to read YAML, or use a JSON workflow") from None
    return yaml.safe_load(source)


def main():
    from deployment import atomic_write, compare, promote, read_baseline, tag
    from reporting import format_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow")
    parser.add_argument("--output", help="Write a redacted JSON report")
    parser.add_argument('--format', choices=['text', 'json'], default='text', help='Terminal output format (default: text)')
    parser.add_argument("--release", help="Release identifier, such as a commit SHA")
    parser.add_argument("--environment", help="Target environment, such as local or staging")
    parser.add_argument("--baseline", help="Compare against this successful report; never implicitly overwrite it")
    parser.add_argument("--set-baseline", help="Explicitly promote this run if it succeeds")
    args = parser.parse_args()
    if bool(args.release) != bool(args.environment) or ((args.baseline or args.set_baseline) and not args.release):
        parser.error('--release and --environment are required together and for baseline operations')
    try:
        baseline = read_baseline(args.baseline) if args.baseline else None
        if args.output and any(Path(args.output).resolve() == Path(p).resolve() for p in (args.baseline, args.set_baseline) if p):
            raise ValueError('Output report must not overwrite a baseline')
        if any(Path(p).resolve() == Path(args.workflow).resolve() for p in (args.output, args.set_baseline) if p):
            raise ValueError('Reports and baselines must not overwrite the workflow')
        spec = load(args.workflow)
        # Fingerprinting happens before any requests so invalid definitions fail safely.
        if args.release:
            tag({}, spec, args.environment, args.release)
        report = run(spec)
        if args.release:
            report = tag(report, spec, args.environment, args.release)
        if baseline:
            report['comparison'] = compare(report, baseline)
        if args.set_baseline:
            if report['passed']:
                promote(args.set_baseline, report)
            else:
                report['baseline_update'] = 'refused_failed_run'
        if args.output:
            atomic_write(args.output, report)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Configuration error ({type(exc).__name__}); check workflow and required environment variables", file=sys.stderr)
        return 2
    output = json.dumps(report, indent=2) if args.format == 'json' else format_report(report)
    print(output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
