# ReleaseGuard

ReleaseGuard checks that critical API workflows still work after a deployment and compares results against an explicit successful baseline. Current scope: a local CLI with a tested third-party API integration; no AWS deployment yet.

## Third-party API integration

The official FastAPI SQLite example is included with its MIT license under `integrations/fastapi-heroes/`. See its `README.md` for setup. `heroes.json` checks create, read, update, persistence, invalid input, deletion, and cleanup. `verify_heroes.py` verifies healthy and deliberately faulty local instances. Provenance and verification results are saved with the integration. This validates the checker against third-party code; it does not establish user adoption.

## Run the demo

Requires Python 3.11+. In this directory, start the disposable demo API:

```powershell
python demo_api.py
```

In another terminal in this directory:

```powershell
python workflow_checker.py example.json --output report.json
```

This creates a task, reads it back, checks its contents, and deletes it. Each run uses a unique identifier.

JSON runs with Python's standard library. For YAML and the installed CLI:

```powershell
python -m pip install -e .
workflow-check example.yaml
```

To demonstrate a broken deployment, stop the demo server and restart it with:

```powershell
$env:DEMO_BROKEN = '1'
python demo_api.py
```

The read step now returns an incorrect title. The checker fails and still deletes the task. Remove the environment variable and restart to restore normal behavior.

## Workflow format

- `base_url`: trusted API target, HTTP or HTTPS.
- `timeout_seconds`: socket timeout per operation; default 10, maximum 120. This is not a hard overall workflow deadline.
- `env`: optional mapping of variable names to required environment variable names, e.g. `{"token": "CHECKER_TOKEN"}`.
- `headers`: optional shared headers, e.g. `{"Authorization": "Bearer ${token}"}`.
- `steps`: ordered requests; execution stops on the first failure.
- `expect.status`: required exact HTTP status.
- `expect.json`: optional mapping of dotted JSON paths to expected values; numeric path components index arrays. Keys containing literal dots are unsupported.
- `expect.json_ranges`: optional mapping of dotted JSON paths to inclusive `[minimum, maximum]` numeric bounds. Rejects strings, booleans, and non-finite values.
- `capture`: mapping of variable names to response JSON paths.
- `${variable}`: substitutes captured values or the built-in `run_id`. A whole-value substitution preserves its JSON type.
- `cleanup`: requests attempted after success or failure. Optional `requires` lists variables that must exist; otherwise that cleanup step is explicitly skipped.

Use separate test accounts and test data. Do not point write workflows at valuable records. Cleanup is best effort: a killed process or lost network can leave data behind. Prefer client-generated IDs, as in the demo, so cleanup does not depend on receiving a create response. Skipped cleanup is visible but does not fail the run; failed cleanup does.

## Results and limits

Exit codes: 0 passed, 1 workflow/cleanup failed, 2 invalid configuration. Reports include step names, HTTP status, timings, and error categories. They omit URLs, headers, payloads, and exception messages. Do not put secrets in step names. Protect workflow files and reports appropriately.

There are no implicit retries. Redirects are not followed. Responses are capped at 1 MiB. TLS verification remains enabled. Run only trusted workflow files locally: targets are not isolated, and this is not safe as a public multi-tenant executor. Captures inserted into paths are literal; use URL-safe IDs. No polling, browser execution, concurrent runs, deployment comparison, persistence service, or alerting yet.

## Verify

```powershell
python -m unittest -v
```

Tests cover a successful workflow, a broken response, early stopping, cleanup after capture failure, cleanup failure, invalid targets, and timeout reporting.

## Next milestones

1. Point this at one of your own APIs and add a meaningful workflow.
2. Run it from CI and tag reports with a deployment identifier.
3. Validate deployment comparisons on your own release workflow.
4. Add scheduled AWS execution and incident alerts after validating personal use.

## Compare deployments

The included `.github/workflows/check.yml` runs unit tests and the healthy/faulty API integration on pushes and pull requests, then uploads generated reports. It takes effect only after this folder is published as the root of its own GitHub repository. The integration succeeds when the healthy API passes and the deliberately faulty API is correctly detected. The Linux Actions job has not yet been executed on GitHub.

With the Heroes API running, explicitly establish a successful baseline:

```powershell
python workflow_checker.py heroes.json --environment local --release v1 --set-baseline baseline.json --output v1.json
```

Run a later release against that baseline:

```powershell
python workflow_checker.py heroes.json --environment local --release v2 --baseline baseline.json --output v2.json
```

The report includes a comparison: `passed`, `regression` with the first failing step, or `not_comparable` if the environment or workflow fingerprint changed. This is evidence of changed behavior, not proof that deployment caused the failure. Release labels are provided by the caller.

The SHA-256 fingerprint covers the whole parsed workflow, including base URL, step order, assertions, and cleanup. Object key order and JSON whitespace do not matter. Runtime environment variable values are not stored or fingerprinted; changed credentials or dependencies can affect results even with the same fingerprint. Keep workflow files free of literal credentials.

Baseline creation is always explicit with `--set-baseline`; ordinary comparisons never update it. Failed runs cannot replace it, and skipped cleanup blocks promotion. A changed workflow needs an explicitly established new baseline. Writes use a temporary file, flush/fsync, and atomic replacement on the same filesystem. This local implementation assumes one writer per baseline; it has no concurrent-writer locking or cross-machine storage. Comparison reports preserve the normal exit code: 0 for a passing current workflow (including not-comparable results), 1 for failure, 2 for configuration errors.

Run `.\.venv\Scripts\python.exe verify_heroes.py` to exercise baseline creation and regression detection against healthy and faulty instances automatically. The generated integration baseline is demonstration data for the verifier's temporary port, not a baseline for the manually started API on port 8002.
