# Third-party API integration: FastAPI Heroes

This is the official FastAPI SQL database tutorial example, not an application authored by us. It exercises real HTTP requests against SQLite persistence. It is a tutorial target, not proof of real users or production readiness.

Source: https://github.com/fastapi/fastapi/blob/bb7f314287bf36e04539c572a2256d94ea45f0d6/docs_src/sql_databases/tutorial002_an_py310.py

MIT license is preserved in `LICENSE`; `source.json` records provenance. `upstream_api.py` is unmodified. `serve.py` binds to loopback and optionally injects a local bug in memory: PATCH requests silently ignore age changes. No changes are sent upstream. There is no authentication in this example.

Verified in this workspace: healthy workflow passed; injected update fault was detected despite an HTTP 200 response; both cleanup steps passed in both cases; both SQLite databases had zero remaining records. `requirements-lock.txt` records the tested environment. A `.venv` has already been prepared locally; you can skip installation on this machine.

## Setup in VS Code

Open the `workflow-checker` folder. All commands below run from that folder.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r integrations/fastapi-heroes/requirements.txt
.\.venv\Scripts\python.exe integrations/fastapi-heroes/serve.py
```

The API uses port 8002 so it does not conflict with the earlier demo. In a second terminal:

```powershell
python workflow_checker.py heroes.json --output report.json
```

Expected: the workflow and both cleanup steps pass. It creates a unique record, retrieves it, updates age, checks persistence through another request, rejects invalid input, deletes the record, and verifies deletion.

## Demonstrate a broken release

Stop the API with Ctrl+C, then restart:

```powershell
.\.venv\Scripts\python.exe integrations/fastapi-heroes/serve.py --broken
```

Run the same checker command again. Expected: PATCH returns HTTP 200, but `Verify the update persisted` fails with `json_assertion_mismatch`. Cleanup still deletes the record and confirms 404. This shows why a successful HTTP status alone is insufficient. Restart without `--broken` to recover.

The test does not claim to have discovered an upstream bug: the failure is deliberately injected into our local process.

## Automated integration verification

```powershell
.\.venv\Scripts\python.exe verify_heroes.py
```

This starts temporary healthy and faulty servers on available local ports, runs the workflow, asserts expected outcomes, verifies both SQLite databases contain zero remaining records, and stops the servers. Reports are written to `integrations/fastapi-heroes/verification.json`.

## Limits

Only run against your disposable local instance. The public repository is a source download, not a deployed testing target. A crash between creation and capture can orphan a record; this integration does not solve that runner limitation. Runtime data lives in `runtime/` unless an explicit `--data-dir` is supplied.
